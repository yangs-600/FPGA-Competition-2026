"""Run the frozen EQY entry on this Windows run; never change measurement data."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import time
import uuid


KIT_INDEX_SHA256 = 'ac50f798b70f4a105f8ad42e12ed16b03bb9ed87ce2ff2ad0194cdf66c4c6cd9'
PROOF_TIMEOUT = 1200
CREATE_NO_WINDOW = 0x08000000 if os.name == 'nt' else 0

# This supervisor only bounds and cleans up this attempt's descendant tree. The
# actual proof entry, helper, models and strategy timeout stay byte-identical.
LINUX_SUPERVISOR = r'''import ctypes,json,os,signal,subprocess,sys,time
from pathlib import Path
control=Path(sys.argv[1]); seconds=int(sys.argv[2]); command=sys.argv[3:]
libc=ctypes.CDLL(None,use_errno=True)
if libc.prctl(36,1,0,0,0)!=0:
    raise OSError(ctypes.get_errno(),"PR_SET_CHILD_SUBREAPER failed")
# Adoption is independent of sessions/process groups, including EQY setsid().
root=os.getpid(); p=None; record={}
def stat(pid):
    try:
        text=Path("/proc",str(pid),"stat").read_text()
        fields=text[text.rfind(")")+2:].split()
        return {"pid":pid,"ppid":int(fields[1]),"starttime":int(fields[19]),"state":fields[0]}
    except (OSError,ValueError,IndexError): return None
def family():
    rows={}
    for n in os.listdir("/proc"):
        if n.isdigit():
            item=stat(int(n))
            if item is not None: rows[item["pid"]]=item
    owned=set(); frontier={root}
    while frontier:
        children={pid for pid,item in rows.items() if item["ppid"] in frontier and pid!=root}-owned
        owned.update(children); frontier=children
    return {pid:rows[pid] for pid in owned}
def matches(item):
    now=stat(item["pid"])
    return now is not None and now["starttime"]==item["starttime"]
def send(item,sig):
    if matches(item):
        try: os.kill(item["pid"],sig)
        except ProcessLookupError: pass
def save():
    temp=control.with_suffix(".tmp")
    temp.write_text(json.dumps(record)); os.replace(temp,control)
def reap():
    while True:
        try: pid,status=os.waitpid(-1,os.WNOHANG)
        except ChildProcessError: break
        if pid==0: break
        if p is not None and pid==p.pid: p.returncode=os.waitstatus_to_exitcode(status)
def clean():
    owned={}; started=time.monotonic()
    # Freeze this tree, so setsid/double-fork descendants cannot escape cleanup.
    for i in range(6):
        rows=family(); owned.update(rows)
        for item in rows.values():
            if item["state"]!="Z": send(item,signal.SIGSTOP)
        time.sleep(0.03)
    for item in owned.values():
        send(item,signal.SIGTERM); send(item,signal.SIGCONT)
    while time.monotonic()-started<8:
        reap(); rows=family(); owned.update(rows)
        for item in rows.values():
            if item["state"]!="Z":
                send(item,signal.SIGSTOP)
                send(item,signal.SIGKILL if time.monotonic()-started>0.6 else signal.SIGTERM)
                send(item,signal.SIGCONT)
        if not rows and not any(matches(item) for item in owned.values()):
            return True,sorted(owned)
        time.sleep(0.05)
    reap()
    return not family() and not any(matches(item) for item in owned.values()),sorted(owned)
def stop_signal(signum,frame):
    raise InterruptedError("supervisor signal "+str(signum))
for s in (signal.SIGTERM,signal.SIGINT,signal.SIGHUP): signal.signal(s,stop_signal)
code=125
try:
    p=subprocess.Popen(command,start_new_session=True)
    record.update(supervisor_pid=root,supervisor_starttime=stat(root)["starttime"],
                  supervisor_script=sys.argv[0],entry_pid=p.pid,command=command,status="RUNNING")
    save(); code=p.wait(timeout=seconds)
except (subprocess.TimeoutExpired,InterruptedError,KeyboardInterrupt) as e:
    print("EQY supervision stopped: "+str(e),flush=True); code=124
finally:
    for s in (signal.SIGTERM,signal.SIGINT,signal.SIGHUP): signal.signal(s,signal.SIG_IGN)
    ok,pids=clean()
    record.update(status="STOPPED",cleanup_verified=ok,descendant_pids=pids,entry_exit_code=code)
    save()
    print("EQY descendant cleanup: "+json.dumps({"verified":ok,"count":len(pids)}),flush=True)
    if not ok: code=125
sys.exit(code)
'''



def _now():
    return datetime.now(timezone.utc).isoformat()


def _sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def _read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def _save(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def _need(ok, message):
    if not ok:
        raise RuntimeError(message)


def _inside(root, relative):
    rel = PurePosixPath(str(relative))
    _need(not rel.is_absolute() and '..' not in rel.parts and ':' not in str(relative), 'Unsafe relative proof path')
    value = (root / Path(*rel.parts)).resolve()
    value.relative_to(root)
    return value


def _capture(command, timeout=20):
    return subprocess.run(command, capture_output=True, timeout=timeout,
                          creationflags=CREATE_NO_WINDOW)


def _stop_linux(prefix, python, control, supervisor):
    # Notify the subreaper, which owns all descendant sessions. Both the unique
    # script and Linux starttime guard against signalling a reused PID.
    code = ('import json,os,signal,sys; from pathlib import Path; '
            'd=json.loads(Path(sys.argv[1]).read_text()); pid=int(d["supervisor_pid"]); '
            'p=Path("/proc")/str(pid)/"cmdline"; '
            's=Path("/proc")/str(pid)/"stat"; t=s.read_text() if s.exists() else ""; '
            'valid=p.exists() and sys.argv[2].encode() in p.read_bytes().split(b"\\x00") and '
            'bool(t) and int(t[t.rfind(")")+2:].split()[19])==d["supervisor_starttime"]; '
            'os.kill(pid,signal.SIGTERM) if valid else None; print("signalled" if valid else "already_stopped_or_unmatched")')
    try:
        result = _capture(prefix + [python, '-I', '-S', '-B', '-c', code, control, supervisor], timeout=15)
        return {'exit_code': result.returncode, 'output': result.stdout.decode('utf-8', errors='replace')[-500:]}
    except (OSError, subprocess.TimeoutExpired) as e:
        return {'error': type(e).__name__}


def _logged(command, log_path, stage, timeout, proof_dir=None, stop=None):
    started = time.monotonic()
    print(stage, flush=True)
    with log_path.open('xb') as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                   creationflags=CREATE_NO_WINDOW)
        try:
            while True:
                try:
                    return process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    elapsed = int(time.monotonic() - started)
                    count = 0
                    if proof_dir is not None:
                        progress = proof_dir/'formal/report.json'
                        if progress.is_file():
                            try:
                                data = _read(progress)
                                count = sum(v.get('status') == 'PASS' for r in data.get('cases', [])
                                            for v in r.get('roles', {}).values())
                            except (OSError, ValueError, TypeError):
                                pass
                    print(f'  {stage}：已等待 {elapsed} 秒' + (f'；已记录 {count}/18 项证明' if count else ''), flush=True)
                    if elapsed >= timeout:
                        raise TimeoutError(stage + ' exceeded its supervisory timeout')
        except BaseException:
            if stop is not None:
                cleanup = stop()
                print('本次 Linux 证明后代清理：'+json.dumps(cleanup, ensure_ascii=False), flush=True)
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
            elif process.poll() is None:
                process.kill()
            process.wait()
            raise


def _validate_result(root, report, report_sha, bundle, output, config, entry_sha):
    """Read-only independent binding checks beyond the frozen launcher's exit code."""
    launch = _read(output/'launch.json')
    formal_path = output/'formal/report.json'
    proof = _read(formal_path)
    _need(launch.get('status') == 'PASS' and launch.get('exit_code') == 0, 'Frozen proof launcher did not pass')
    _need(launch.get('source_kit_and_evidence_unchanged') is True, 'Frozen tools or evidence changed')
    _need(launch.get('launcher_sha256') == entry_sha, 'Proof entry identity differs')
    _need(launch.get('report_sha256') == _sha(formal_path), 'Proof report digest differs')
    _need(proof.get('status') == 'PASS' and proof.get('formal_status') == 'PASS', 'Formal proof did not pass')
    _need(launch.get('positive_proof_counts') == proof.get('positive_proof_counts') == {'PASS': 18}, 'Expected eighteen positive proofs')
    _need(launch.get('negative_control') == proof.get('negative_control', {}).get('status') == 'EXPECTED_COUNTEREXAMPLE', 'Negative control did not detect the error')
    _need(launch.get('windows_report_sha256') == proof.get('windows_report_sha256') == report_sha == _sha(bundle/'report.json'), 'Proof refers to a different Windows report')
    _need(launch.get('inventory_sha256') == _sha(bundle/'evidence-inventory.json'), 'Evidence inventory binding differs')
    frozen = output/'inputs/frozen-linux-proof-tool-manifest.json'
    derived = output/'inputs/linux-proof-tool-manifest.json'
    _need(launch.get('frozen_linux_proof_manifest_sha256') == config['manifest_sha256'] == _sha(frozen), 'Parent tool manifest binding differs')
    _need(launch.get('linux_proof_manifest_sha256') == proof.get('linux_proof_manifest_sha256') == _sha(derived), 'Derived tool manifest binding differs')
    f, d = _read(frozen), _read(derived)
    changes = {k for k in set(f) | set(d) if f.get(k) != d.get(k)}
    allowed = {'abc_script', 'abc_script_sha256', 'windows_recipe_binding'}
    _need(changes == allowed == set(launch.get('derived_manifest_changed_fields', [])), 'Unexpected proof strategy/tool changes')
    _need(d['windows_recipe_binding']['windows_report_sha256'] == report_sha and
          d['windows_recipe_binding']['parent_manifest_sha256'] == config['manifest_sha256'], 'Recipe report binding differs')
    manifest = _read(bundle/'manifest.json')
    _need(d['abc_script_sha256'] == manifest['script_sha256'] == proof.get('windows_unified_abc_script', {}).get('sha256'), 'Actual Windows recipe identity differs')
    _need(launch.get('kit_index_sha256') == KIT_INDEX_SHA256 == _sha(output/'inputs/linux-portable-index.json'), 'Frozen kit index differs')
    _need(_sha(bundle/'report.json') == _sha(output/'inputs/report.json'), 'Windows report snapshot differs')
    rows = proof.get('cases', [])
    measured = {r['name']: r for r in report['cases']}
    _need(len(rows) == len(measured) == 9 and {r['name'] for r in rows} == set(measured), 'Proof case set differs')
    case_rows = []
    for row in rows:
        source = measured[row['name']]
        _need(row.get('top') == source['top'] and row.get('source_sha256') == source['source_sha256'], 'Proof RTL identity differs')
        result = {'name': row['name']}
        for role in ('baseline', 'candidate'):
            item, original = row['roles'][role], source['roles'][role]
            _need(item.get('status') == 'PASS' and item.get('ilang_sha256') == original['ilang_sha256'] and
                  item.get('windows_executable_sha256') == original['executable_sha256'], 'Per-role proof object identity differs')
            _need(_sha(_inside(root, original['path']+'/postabc.il')) == original['ilang_sha256'] ==
                  _sha(_inside(bundle, original['path']+'/postabc.il')), 'Original Windows proof object changed')
            result[role] = item['status']
        case_rows.append(result)
    return launch, proof, case_rows


def run_formal(root, report_path):
    root, report_path = Path(root).resolve(), Path(report_path).resolve()
    report_path.relative_to(root)
    report_sha = _sha(report_path)
    report = _read(report_path)
    name = str(report.get('directory', ''))
    _need(re.fullmatch(r'validation-current-[A-Za-z0-9_-]+', name), 'Unexpected Windows result directory')
    _need(report_path == root/name/'report.json', 'Use the immutable per-run report.json, not a latest mirror')
    attempt = root/'tmp/formal-runs'/(name.removeprefix('validation-current-')+'-'+uuid.uuid4().hex[:8])
    attempt.mkdir(parents=True, exist_ok=False)
    bundle, output = attempt/'bundle', attempt/'proof'
    files = {'receipt': attempt/'formal-receipt.json', 'launch': output/'launch.json',
             'formal_report': output/'formal/report.json', 'process_log': output/'process.log',
             'bundle': bundle, 'output': output, 'console_log': attempt/'console.log',
             'bundle_log': attempt/'bundle.log', 'command': attempt/'command.json'}
    result = {'schema': 'windows-demo-formal-v1', 'status': 'ERROR', 'started_at': _now(),
              'windows_report_sha256': report_sha, 'windows_report_path': report_path.relative_to(root).as_posix(),
              'positive_proof_counts': {}, 'negative_control': {'status': 'NOT_RUN'}, 'case_rows': [],
              'paths': {k: p.relative_to(root).as_posix() for k, p in files.items()},
              'performance_retested': False, 'proof_strategy_changed': False,
              'supervisory_timeout_seconds': PROOF_TIMEOUT}
    _save(files['receipt'], result)
    try:
        config_path = root/'tmp/proof-wsl.local.json'
        if os.name != 'nt' or not config_path.is_file():
            result.update(status='UNAVAILABLE', error='需要 Windows WSL 及 tmp/proof-wsl.local.json 配置；本轮形式证明未执行。')
            return result
        config = _read(config_path)
        _need(config.get('schema') == 1, 'Unsupported local proof configuration schema')
        distro, kit, manifest_path = (config[k] for k in ('distro', 'kit', 'manifest'))
        _need(re.fullmatch(r'[A-Za-z0-9_.-]+', distro), 'Unsafe WSL distribution name')
        for path in (kit, manifest_path):
            _need(re.fullmatch(r'/[A-Za-z0-9_./-]+', path) and '..' not in path.split('/'), 'Frozen proof kit requires an ASCII Linux path without spaces')
        _need(PurePosixPath(manifest_path).is_relative_to(PurePosixPath(kit)), 'Parent manifest must be inside the frozen kit')
        _need(re.fullmatch('[0-9a-f]{64}', config['manifest_sha256']), 'Expected parent manifest SHA-256')
        wsl = Path(os.environ.get('SystemRoot', 'C:/Windows'))/'System32/wsl.exe'
        if not wsl.is_file():
            result.update(status='UNAVAILABLE', error='Windows 未找到 wsl.exe；本轮形式证明未执行。')
            return result
        prefix = [str(wsl), '-d', distro, '--exec']
        mapped = _capture(prefix+['/usr/bin/wslpath', '-a', '-u', str(root)], timeout=30)
        (attempt/'wsl-precheck.log').write_bytes(mapped.stdout+b'\n'+mapped.stderr)
        if mapped.returncode:
            result.update(status='UNAVAILABLE', error='无法访问配置的 WSL 发行版或转换目录；见 wsl-precheck.log。')
            return result
        linux_root = mapped.stdout.decode('utf-8', errors='strict').strip()
        _need(re.fullmatch(r'/[A-Za-z0-9_./-]+', linux_root), 'Frozen proof helper requires an ASCII package path without spaces')
        linux_attempt = linux_root+'/'+attempt.relative_to(root).as_posix()
        python = kit+'/runtime/bin/python3'
        ready = _capture(prefix+['/usr/bin/test', '-x', python], timeout=20)
        if ready.returncode:
            result.update(status='UNAVAILABLE', error='配置的冻结 EQY 工具包不存在或不可执行。')
            return result
        package_manifest = _read(root/'manifest.json')
        entry = root/'source/prove_windows_native_once.py'
        bundler = root/'source/bundle_native_evidence.py'
        _need(_sha(entry) == package_manifest['proof_entry_sha256'], 'Frozen proof entry changed')
        _need(_sha(bundler) == package_manifest['evidence_bundler_sha256'], 'Frozen evidence bundler changed')
        copied_entry = attempt/'prove_windows_native_once.py'
        shutil.copyfile(entry, copied_entry)
        entry_sha = _sha(copied_entry)
        _need(entry_sha == _sha(entry), 'Proof entry copy differs')
        result['tool_metadata'] = {'distro': distro, 'kit': kit, 'parent_manifest': manifest_path,
                                   'parent_manifest_sha256': config['manifest_sha256'],
                                   'kit_index_sha256': KIT_INDEX_SHA256, 'proof_entry_sha256': entry_sha}
        code = _logged([str(root/'runtime/python.exe'), '-I', '-S', '-B', '-X', 'utf8', str(bundler),
                        '--package', str(root), '--report', str(report_path), '--output', str(bundle)],
                       files['bundle_log'], '整理本轮 Windows 证明证据', 180)
        _need(code == 0, 'Evidence bundler failed; see bundle.log')
        _need(_sha(report_path) == report_sha == _sha(bundle/'report.json'), 'Windows report changed during evidence copy')
        inventory_sha = _sha(bundle/'evidence-inventory.json')
        supervisor = attempt/'linux_supervisor.py'
        supervisor.write_text(LINUX_SUPERVISOR, encoding='utf-8')
        control = linux_attempt+'/linux-process.json'
        linux_entry = linux_attempt+'/prove_windows_native_once.py'
        command = prefix+[python, '-I', '-S', '-B', linux_attempt+'/linux_supervisor.py', control, str(PROOF_TIMEOUT),
                          python, '-I', '-S', '-B', linux_entry, '--run-proofs', '--kit', kit,
                          '--manifest', manifest_path, '--manifest-sha256', config['manifest_sha256'],
                          '--bundle', linux_attempt+'/bundle', '--windows-report-sha256', report_sha,
                          '--inventory-sha256', inventory_sha, '--output', linux_attempt+'/proof']
        _save(files['command'], command)
        result.update(inventory_sha256=inventory_sha, supervisor_sha256=_sha(supervisor))
        _save(files['receipt'], result)
        code = _logged(command, files['console_log'], '执行本轮 18 项 EQY 证明及负对照',
                       PROOF_TIMEOUT+60, output,
                       stop=lambda: _stop_linux(prefix, python, control, linux_attempt+'/linux_supervisor.py'))
        result['proof_process_exit_code'] = code
        control_record = _read(attempt/'linux-process.json')
        result['descendant_cleanup_verified'] = control_record.get('cleanup_verified') is True
        _need(result['descendant_cleanup_verified'], 'Linux proof descendants were not confirmed stopped')
        _need(_sha(report_path) == report_sha and _sha(entry) == entry_sha, 'Original Windows report or proof entry changed')
        if code != 0:
            if files['formal_report'].is_file():
                failed = _read(files['formal_report'])
                result.update(positive_proof_counts=failed.get('positive_proof_counts', {}),
                              negative_control=failed.get('negative_control', {'status': 'NOT_COMPLETED'}))
            result.update(status='FAIL' if files['formal_report'].exists() else 'ERROR',
                          error='本轮 EQY 未全部通过或执行失败；保留全部证据，请查看 console.log 和 process.log。')
            return result
        launch, proof, case_rows = _validate_result(root, report, report_sha, bundle, output, config, entry_sha)
        result.update(status='PASS', positive_proof_counts={'PASS': 18},
                      negative_control={'status': 'EXPECTED_COUNTEREXAMPLE'}, case_rows=case_rows,
                      source_kit_and_evidence_unchanged=True,
                      launch_sha256=_sha(files['launch']), formal_report_sha256=_sha(files['formal_report']))
        result['tool_metadata']['proof_engine_versions'] = proof.get('proof_engine_versions', {})
        result['tool_metadata']['derived_manifest_sha256'] = launch['linux_proof_manifest_sha256']
        print('本轮 EQY：18/18 PASS；负对照 EXPECTED_COUNTEREXAMPLE。', flush=True)
        return result
    except KeyboardInterrupt:
        result.update(status='ERROR', error='形式验证被中断；当前尝试保留，不能视为通过。')
        return result
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.TimeoutExpired) as e:
        result.update(status='ERROR', error=str(e))
        return result
    finally:
        result['completed_at'] = _now()
        # Failed/unavailable attempts must not publish links to absent files.
        result['paths'] = {k: p.relative_to(root).as_posix() for k, p in files.items()
                           if p.exists() or k == 'receipt'}
        _save(files['receipt'], result)
