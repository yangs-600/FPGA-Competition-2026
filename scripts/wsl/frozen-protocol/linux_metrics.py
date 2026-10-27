"""Independent WSL/Linux root RSS and complete-run wall/CPU measurement.

The field peak_working_set_bytes is retained for runner compatibility, but its
value is root-only VmHWM KiB*1024 at PTRACE_EVENT_EXIT. It is not Windows working
set and not wait4 ru_maxrss (which can include a larger reaped child).
"""
import hashlib
import json
import math
import os
from pathlib import Path
import select
import signal
import subprocess
import time

HERE = Path(__file__).resolve().parent
METER = HERE / 'linux_root_meter'
CONTROL = HERE / 'linux_meter_control'


class MeasurementError(RuntimeError):
    def __init__(self, message, result=None):
        super().__init__(message)
        self.result = result


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _session_processes(session):
    """Only processes in the unique session created for this invocation."""
    result = []
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit():
            continue
        try:
            # After ')' the fields are state, ppid, pgrp, session, ... .
            fields = (entry / 'stat').read_text().rsplit(')', 1)[1].split()
            if int(fields[3]) == session:
                result.append(dict(pid=int(entry.name), pgid=int(fields[2]), state=fields[0]))
        except (FileNotFoundError, ProcessLookupError, PermissionError, ValueError, IndexError):
            continue
    return result


def _terminate_owned_session(process):
    """Fallback after the C timeout failed: stop and kill only our new session.

    The still-owned Popen child pins the session-leader PID until reap.  pidfds
    pin every signalled member against PID reuse; no system-wide name matching.
    Keep stopped members stopped and scan until no new member is found.
    """
    evidence = dict(session_id=process.pid, members=[], used_sigkill=True)
    handles = {}
    try:
        for _ in range(16):
            added = False
            for member in _session_processes(process.pid):
                if member['pid'] in handles:
                    continue
                fd = None
                try:
                    fd = os.pidfd_open(member['pid'])
                    if os.getsid(member['pid']) != process.pid:
                        os.close(fd)
                        continue
                    handles[member['pid']] = fd
                    added = True
                    evidence['members'].append(member)
                    signal.pidfd_send_signal(fd, signal.SIGSTOP)
                except ProcessLookupError:
                    if fd is not None and member['pid'] not in handles:
                        os.close(fd)
                    continue
            if not added:
                break
        for fd in handles.values():
            try:
                signal.pidfd_send_signal(fd, signal.SIGKILL)
            except ProcessLookupError:
                pass
        process.communicate(timeout=5)
        deadline = time.monotonic() + 5
        while True:
            remaining = _session_processes(process.pid)
            # Orphan zombies have no resources or ability to execute; retain
            # their exact state rather than claiming every PID was reaped here.
            active = [p for p in remaining if p['state'] != 'Z']
            if not active or time.monotonic() >= deadline:
                break
            time.sleep(.01)
        evidence.update(remaining=remaining, no_live_session_members=not active,
                        helper_reaped=process.returncode is not None)
        return evidence
    finally:
        for fd in handles.values():
            os.close(fd)


def measure(command, logfile, env=None, cwd=None, timeout=120):
    if os.name != 'posix' or not Path('/proc/self/status').exists():
        raise RuntimeError('Linux /proc and ptrace are required')
    if not math.isfinite(timeout) or timeout <= 0 or timeout > 3600:
        raise ValueError('Invalid measurement timeout')
    command = [str(c) for c in command]
    if not command or not Path(command[0]).is_absolute():
        raise ValueError('Use an explicit absolute program path')
    logfile = Path(logfile).resolve()
    sidecar = logfile.with_name(logfile.name + '.metrics.json')
    if logfile.exists() or sidecar.exists():
        raise FileExistsError('Refuse to overwrite a measured sample: ' + str(logfile))
    logfile.parent.mkdir(parents=True, exist_ok=True)
    process = subprocess.Popen([str(METER), str(sidecar), str(logfile), repr(timeout), *command],
                               env=env, cwd=cwd, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               start_new_session=True)
    try:
        stdout, stderr = process.communicate(timeout=timeout + 15)
    except subprocess.TimeoutExpired:
        # communicate() does not kill the helper first: keep its PID owned
        # while signalling the dedicated session, including nontraced ABC.
        failure = dict(meter_status='FAIL', error='Python external guard timeout',
                       cleanup=_terminate_owned_session(process))
        guard = logfile.with_name(logfile.name + '.external-guard.json')
        with guard.open('x', encoding='utf8') as stream:
            json.dump(failure, stream, indent=2)
            stream.write('\n')
        raise MeasurementError('External guard terminated the owned session', failure)
    if not sidecar.is_file():
        raise MeasurementError('Meter produced no result: ' + stderr.decode('utf8', errors='replace'))
    try:
        result = json.loads(sidecar.read_text(encoding='utf8'))
    except Exception as error:
        raise MeasurementError('Meter result is incomplete: ' + str(sidecar)) from error
    result.update(meter_binary_sha256=sha(METER), meter_source_sha256=sha(HERE / 'linux_root_meter.c'),
                  meter_python_sha256=sha(__file__), meter_result_sha256=sha(sidecar),
                  meter_result=str(sidecar), meter_exit_code=process.returncode)
    if stderr:
        result['meter_stderr'] = stderr.decode('utf8', errors='replace')
    if process.returncode != 0 or result.get('meter_status') != 'PASS':
        raise MeasurementError('External meter failed: ' + str(result.get('error')), result)
    if not (result['final_reaped'] and result['process_group_empty'] and
            result['exec_stop_seen'] and result['exit_stop_seen'] and result['exit_code'] == 0):
        raise MeasurementError('Incomplete process/peak accounting', result)
    for name in ('wall_seconds', 'cpu_seconds', 'root_cpu_seconds', 'peak_working_set_bytes'):
        if not math.isfinite(result[name]) or result[name] < 0:
            raise MeasurementError('Invalid measured ' + name, result)
    if result['wall_seconds'] <= 0 or result['peak_working_set_bytes'] <= 0:
        raise MeasurementError('Invalid primary measurements', result)
    return result


def self_test(out):
    """Tiny controls, never Yosys or ABC; preserve failed checks and samples."""
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=False)
    report = dict(status='RUNNING', meter_binary_sha256=sha(METER),
                  meter_source_sha256=sha(HERE / 'linux_root_meter.c'),
                  control_binary_sha256=sha(CONTROL), control_source_sha256=sha(HERE / 'linux_meter_control.c'),
                  python_sha256=sha(__file__), controls={},
                  purpose='Root-only last-moment RSS, child CPU, nonzero failure, owned process-group timeout cleanup')

    def save():
        (out / 'meter-self-test.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf8')

    save()
    try:
        child = measure([str(CONTROL), 'child-large-root-small'], out / 'child-large-root-small.log', timeout=10)
        report['controls']['child_large_root_small'] = child
        assert 32 * 2**20 <= child['peak_working_set_bytes'] < 80 * 2**20, child
        assert child['wait4_maxrss_kib_diagnostic_only'] * 1024 >= 120 * 2**20, child
        assert child['cpu_seconds'] - child['root_cpu_seconds'] >= .18, child
        save()
        root = measure([str(CONTROL), 'root-late-peak'], out / 'root-late-peak.log', timeout=10)
        report['controls']['root_late_peak'] = root
        assert 96 * 2**20 <= root['peak_working_set_bytes'] < 128 * 2**20, root
        save()
        for mode, seconds in [('nonzero', 10), ('timeout-group', .15)]:
            try:
                measure([str(CONTROL), mode], out / (mode + '.log'), timeout=seconds)
            except MeasurementError as failure:
                data = failure.result
                assert data and data['process_group_empty'], data
                if mode == 'nonzero':
                    assert data['exit_code'] == 7 and data['exit_stop_seen'], data
                else:
                    assert data['interrupted_signal'] == 14, data
                report['controls'][mode] = dict(expected_failure_detected=True, result=data)
            else:
                raise AssertionError('Negative control unexpectedly passed: ' + mode)
            save()
        guard = subprocess.Popen([str(CONTROL), 'timeout-separate-group'],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, start_new_session=True)
        try:
            # Both processes print only after their group setup is complete.
            deadline, captured = time.monotonic() + 3, b''
            while captured.count(b'\n') < 2:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not select.select([guard.stdout], [], [], remaining)[0]:
                    raise AssertionError('Guard control did not become ready')
                piece = os.read(guard.stdout.fileno(), 4096)
                if not piece:
                    raise AssertionError('Guard control exited before readiness')
                captured += piece
            (out / 'external-guard-control.log').write_bytes(captured)
            result = _terminate_owned_session(guard)
            assert result['helper_reaped'] and result['no_live_session_members'], result
            assert len({m['pgid'] for m in result['members']}) == 2, result
            report['controls']['external_guard_two_groups'] = result
        finally:
            if guard.poll() is None:
                _terminate_owned_session(guard)
        save()
        report['status'] = 'PASS'
    except BaseException as error:
        report.update(status='FAIL', error=repr(error))
        save()
        raise
    save()
    return report


if __name__ == '__main__':
    import sys
    print(json.dumps(self_test(sys.argv[1]), indent=2))
