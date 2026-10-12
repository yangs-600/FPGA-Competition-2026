"""Reproducible Linux acceptance: <=1000 input cells, <=60 s, <=2e9 bytes.

Use cgroup v2 memory.peak for the entire Python/Yosys/ABC service. The small
Python worker is included, making memory accounting conservative. No root,
algorithm changes, or pre-existing benchmark results are required.
"""
import argparse
from collections import Counter
import ctypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import re
import resource
import signal
import statistics
import subprocess
import sys
import tempfile
import time
import uuid

LIMIT_BYTES = 2_000_000_000
LIMIT_SECONDS = 60.0
LIMIT_NODES = 1000
TASK_LIMIT = 16
SCRIPT = Path(__file__).resolve()
REPO = SCRIPT.parents[1]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, data):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.writing')
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n')
    temporary.replace(path)


def events(path):
    return {k: int(v) for k, v in (line.split() for line in path.read_text().splitlines())}


def own_cgroup():
    relative = next(line.split(':', 2)[2] for line in Path('/proc/self/cgroup').read_text().splitlines()
                    if line.startswith('0::'))
    root = Path('/sys/fs/cgroup').resolve()
    path = (root / relative.lstrip('/')).resolve()
    if root not in path.parents:
        raise RuntimeError('Unexpected cgroup path: ' + str(path))
    return path


def observe_children(root_pid, expected_cgroup, seen):
    todo = [root_pid]
    visited = set()
    while todo:
        pid = todo.pop()
        if pid in visited:
            continue
        visited.add(pid)
        try:
            p = Path('/proc') / str(pid)
            todo.extend(int(x) for x in (p / 'task' / str(pid) / 'children').read_text().split())
            group = next(line.split(':', 2)[2] for line in (p / 'cgroup').read_text().splitlines()
                         if line.startswith('0::'))
            if group != expected_cgroup:
                raise RuntimeError('Measured child escaped its cgroup')
            seen.add((p / 'comm').read_text().strip())
        except (FileNotFoundError, ProcessLookupError):
            pass


def worker(config_path):
    cfg = json.loads(Path(config_path).read_text())
    result = {'status': 'RUNNING'}
    cg = own_cgroup()
    result['cgroup'] = str(cg)
    result['memory_max_bytes'] = int((cg / 'memory.max').read_text())
    result['memory_swap_max_bytes'] = int((cg / 'memory.swap.max').read_text())
    page_size = os.sysconf('SC_PAGE_SIZE')
    expected_limit = (LIMIT_BYTES // page_size) * page_size
    if result['memory_max_bytes'] != expected_limit or result['memory_swap_max_bytes'] != 0:
        raise RuntimeError('Unexpected installed kernel limits: ' + str(result))
    if not (cg / 'memory.peak').exists():
        raise RuntimeError('Kernel memory.peak is unavailable; cannot claim an exact tree peak')
    result['task_limit'] = int((cg / 'pids.max').read_text())
    if result['task_limit'] != TASK_LIMIT:
        raise RuntimeError('Unexpected task limit')
    # Adopt and reap any orphaned descendants so their kernel high-water RSS
    # remains available, including descendants that do not exit with Yosys.
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
        raise RuntimeError('Cannot enable child subreaper: ' + str(ctypes.get_errno()))
    before = events(cg / 'memory.events')
    observed = set()
    root = None
    try:
        if cfg.get('allocation_probe'):
            children = [subprocess.Popen([sys.executable, '-E', '-c',
                         'import time; b=bytearray(64*1024*1024); time.sleep(.4)']) for _ in range(2)]
            for child in children:
                if child.wait(timeout=5):
                    raise RuntimeError('Allocation probe failed')
            result.update(status='PASS', exit_code=0, allocation_probe=True)
        else:
            env = dict(os.environ, PATH=cfg['path'])
            start = time.monotonic()
            with Path(cfg['log']).open('w') as log:
                root = subprocess.Popen(cfg['command'], stdout=log, stderr=subprocess.STDOUT,
                                        env=env, start_new_session=True)
                relative = '/' + str(cg.relative_to('/sys/fs/cgroup'))
                while True:
                    pid, status, usage = os.wait4(root.pid, os.WNOHANG)
                    if pid:
                        root.returncode = os.waitstatus_to_exitcode(status)
                        break
                    if time.monotonic() - start > LIMIT_SECONDS:
                        os.killpg(root.pid, signal.SIGKILL)
                        os.waitpid(root.pid, 0)
                        root.returncode = -signal.SIGKILL
                        raise RuntimeError('Full synthesis exceeded 60 seconds')
                    observe_children(root.pid, relative, observed)
                    time.sleep(.002)
            while True:
                try:
                    adopted, adopted_status, adopted_usage = os.wait4(-1, os.WNOHANG)
                except ChildProcessError:
                    break
                if adopted:
                    if os.waitstatus_to_exitcode(adopted_status):
                        raise RuntimeError('An adopted descendant failed')
                else:
                    if time.monotonic() - start > LIMIT_SECONDS:
                        raise RuntimeError('Descendants exceeded the full optimization time limit')
                    time.sleep(.002)
            elapsed = time.monotonic() - start
            result.update(status='PASS' if root.returncode == 0 else 'FAIL',
                          exit_code=root.returncode, wall_seconds=elapsed,
                          cpu_seconds=usage.ru_utime + usage.ru_stime,
                          root_ru_maxrss_kib=usage.ru_maxrss,
                          observed_process_names=sorted(observed))
    except Exception as exc:
        result.update(status='FAIL', error=str(exc))
        if root is not None and root.returncode is None:
            os.killpg(root.pid, signal.SIGKILL)
            root.wait()
    after = events(cg / 'memory.events')
    result['memory_events_delta'] = {k: after[k] - before.get(k, 0) for k in after}
    result['cgroup_memory_peak_bytes'] = int((cg / 'memory.peak').read_text())
    largest_rss = max(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                      resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss)
    result['largest_process_hwm_rss_kib'] = largest_rss
    peak_path = cg / 'pids.peak'
    result['kernel_peak_tasks'] = int(peak_path.read_text()) if peak_path.exists() else None
    bound_tasks = result['kernel_peak_tasks'] or TASK_LIMIT
    result['rss_tree_upper_bound_bytes'] = bound_tasks * largest_rss * 1024
    result['rss_bound_policy'] = 'Kernel peak task count (or enforced 16-task cap) times largest kernel process HWM, including worker; all descendants waited/reaped. Conservative bound on simultaneous summed RSS, including shared mappings.'
    result['pids_events'] = events(cg / 'pids.events')
    result['memory_method'] = 'kernel cgroup-v2 charged memory.peak plus conservative summed-RSS upper bound; all descendants and worker; swap disabled'
    save(cfg['result'], result)
    # Keep the cgroup alive until the controller has read its peak once more.
    deadline = time.monotonic() + 15
    while not Path(cfg['release']).exists() and time.monotonic() < deadline:
        time.sleep(.01)
    return 0 if result['status'] == 'PASS' else 1


class Meter:
    def __init__(self, folder, path):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        runtime = Path('/run/user') / str(os.getuid())
        self.env = dict(os.environ, XDG_RUNTIME_DIR=str(runtime),
                        DBUS_SESSION_BUS_ADDRESS='unix:path=' + str(runtime / 'bus'))
        self.path = path
        check = subprocess.run(['systemctl', '--user', 'show-environment'], env=self.env,
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=10)
        if check.returncode:
            raise RuntimeError('User systemd is required: ' + check.stderr)

    def run(self, command, log, allocation_probe=False, allow_failure=False):
        identity = uuid.uuid4().hex[:16]
        unit = 'pmux-accept-' + identity + '.service'
        config = self.folder / (identity + '.config.json')
        result_path = self.folder / (identity + '.result.json')
        release = self.folder / (identity + '.release')
        save(config, dict(command=command, log=str(log), result=str(result_path),
                          release=str(release), path=self.path, allocation_probe=allocation_probe))
        launch = ['systemd-run', '--user', '--quiet', '--unit=' + unit,
                  '--property=Type=exec', '--property=MemoryAccounting=yes',
                  '--property=MemoryMax=' + str(LIMIT_BYTES), '--property=MemorySwapMax=0',
                  '--property=RuntimeMaxSec=75', '--property=TasksMax=' + str(TASK_LIMIT),
                  '--property=StandardOutput=file:' + str(self.folder / (identity + '.worker.log')),
                  '--property=StandardError=inherit',
                  '/usr/bin/python3', '-E', '-u', str(SCRIPT), '--worker', str(config)]
        try:
            started = subprocess.run(launch, env=self.env, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, text=True, timeout=10)
            if started.returncode:
                raise RuntimeError('Cannot create metered service: ' + started.stdout)
            deadline = time.monotonic() + 80
            next_state_check = time.monotonic() + 1
            while not result_path.exists():
                if time.monotonic() > deadline:
                    raise RuntimeError('Metered worker did not return a result')
                if time.monotonic() >= next_state_check:
                    state = subprocess.check_output(['systemctl', '--user', 'show', unit,
                        '--property=ActiveState', '--value'], env=self.env, text=True, timeout=5).strip()
                    if state in ('failed', 'inactive') and not result_path.exists():
                        message = (self.folder / (identity + '.worker.log')).read_text()
                        raise RuntimeError('Metered worker failed during startup: ' + message)
                    next_state_check = time.monotonic() + 1
                time.sleep(.02)
            result = json.loads(result_path.read_text())
            cg = Path(result['cgroup'])
            result['cgroup_memory_peak_bytes'] = max(result['cgroup_memory_peak_bytes'],
                                                     int((cg / 'memory.peak').read_text()))
            result['memory_events_at_collection'] = events(cg / 'memory.events')
            result['service'] = unit
            result['performance_pass'] = (result['status'] == 'PASS' and
                result.get('wall_seconds', 0) <= LIMIT_SECONDS and
                result['cgroup_memory_peak_bytes'] <= LIMIT_BYTES and
                result['rss_tree_upper_bound_bytes'] <= LIMIT_BYTES and
                result['pids_events'].get('max', 0) == 0 and
                result['memory_events_at_collection'].get('oom', 0) == 0 and
                result['memory_events_at_collection'].get('oom_kill', 0) == 0)
            save(result_path, result)
            release.touch()
            if not allow_failure and not result['performance_pass']:
                raise RuntimeError('Metered command failed: ' + str(log) + ' ' + str(result))
            return result
        finally:
            subprocess.run(['systemctl', '--user', 'stop', unit], env=self.env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
            subprocess.run(['systemctl', '--user', 'reset-failed', unit], env=self.env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)


SPECS = [
    dict(name='full3_many_groups', bits=3, width=8, outputs=2, max_groups=12, mode='full', seed=3101),
    dict(name='full4_mixed_w16', bits=4, width=16, outputs=2, max_groups=4, mode='full', mixed=True, seed=4102),
    dict(name='full5_shared_outputs', bits=5, width=8, outputs=2, max_groups=4, mode='full', seed=5103),
    dict(name='full6_search720', bits=6, width=8, outputs=1, max_groups=2, mode='full', mixed=True, seed=6104),
    dict(name='sparse6_default12', bits=6, width=16, outputs=2, max_groups=6, mode='sparse', seed=6105),
    dict(name='shared6_w32_search720', bits=6, width=32, outputs=2, max_groups=8, mode='shared', seed=6106),
    dict(name='priority6_overlap', bits=6, width=16, outputs=2, max_groups=4, mode='priority', mixed=True, seed=6107),
    dict(name='wide7_safe_skip', bits=7, width=8, outputs=1, max_groups=1, mode='full', pool=8, seed=7108),
]


def generate(spec, groups, triple=0, simple=0, wrong=False):
    bits, width, outputs = spec['bits'], spec['width'], spec['outputs']
    codes = 1 << bits
    pool = spec.get('pool', 4 if spec['mode'] == 'shared' else codes)
    filler = triple + simple
    ports = [f'input [{groups * bits - 1}:0] sel',
             f'input [{groups * pool * width - 1}:0] data',
             f'input [{groups * width - 1}:0] mask',
             f'input [{max(4, triple * 4 + simple * 2) - 1}:0] mix_in',
             f'output [{groups * outputs * width - 1}:0] y',
             f'output [{max(1, filler) - 1}:0] mix']
    lines = ['module stress(' + ','.join(ports) + ');']
    for group in range(groups):
        rng = random.Random(spec['seed'] + group * 100)
        arms = (rng.sample(range(codes), 12) if spec['mode'] == 'sparse'
                else list(range(bits)) if spec['mode'] == 'priority' else list(range(codes)))
        rng.shuffle(arms) if spec['mode'] != 'priority' else None
        permutations = []
        for output in range(outputs):
            order = list(range(pool))
            rng.shuffle(order)
            permutations.append(order)
        for output in range(outputs):
            wire = f'tmp_{group}_{output}'
            def value(code):
                if wrong:
                    return f"{width}'d0"
                if code is None:
                    index = pool - 1
                elif spec['mode'] == 'shared':
                    choose = ((code >> (bits - 1)) & 1 and code & 1) or (
                        not ((code >> (bits - 1)) & 1) and (code >> 1) & 1)
                    index = (int(bool(choose)) + output * 2) % pool
                else:
                    index = permutations[output][code % pool]
                return f'data[{(group * pool + index) * width} +: {width}]'
            lines.extend([f'reg [{width - 1}:0] {wire};',
                          f'always @* begin {wire}={value(None)};',
                          f"{'casez' if spec['mode'] == 'priority' else 'case'}(sel[{group * bits} +: {bits}])"])
            for code in arms:
                label = (f"{bits}'b" + '?' * (bits - 1 - code) + '1' + '?' * code
                         if spec['mode'] == 'priority' else f"{bits}'d{code}")
                lines.append(f'{label}: {wire}={value(code)};')
            lines.extend(['endcase', 'end'])
            expression = wire + (f' ^ mask[{group * width} +: {width}]' if spec.get('mixed') else '')
            lines.append(f'assign y[{(group * outputs + output) * width} +: {width}]={expression};')
    for i in range(triple):
        a = i * 4
        lines.append(f'assign mix[{i}]=(mix_in[{a}] ^ mix_in[{a+1}]) & (mix_in[{a+2}] | mix_in[{a+3}]);')
    for i in range(simple):
        a = triple * 4 + i * 2
        lines.append(f'assign mix[{triple+i}]=mix_in[{a}] & mix_in[{a+1}];')
    if not filler:
        lines.append("assign mix=1'b0;")
    lines.append('endmodule')
    return '\n'.join(lines) + '\n'


def cell_counts(path):
    cells = json.loads(Path(path).read_text())['modules']['stress']['cells']
    by = Counter(c['type'] for c in cells.values() if c['type'] != '$scopeinfo')
    return dict(total=sum(by.values()), by_type=dict(by))


def run_plain(command, log, env, allow_failure=False):
    with Path(log).open('w') as target:
        result = subprocess.run(command, stdout=target, stderr=subprocess.STDOUT,
                                env=env, timeout=120, start_new_session=True)
    if result.returncode and not allow_failure:
        raise RuntimeError('Command failed; inspect ' + str(log))
    return result.returncode


def write_flow(folder, source):
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / 'flow.ys'
    path.write_text(f'read_verilog "{source}"\nsynth_intel -family cycloneiv -top stress\n'
                    f'write_verilog -norename -noattr "{folder}/netlist.v"\n'
                    f'write_json "{folder}/netlist.json"\n')
    return path


def raw_snapshot(source, folder, binary, env, apply_pass=False):
    folder.mkdir(parents=True, exist_ok=True)
    flow = folder / 'snapshot.ys'
    flow.write_text(f'read_verilog "{source}"\nhierarchy -top stress\nproc\nflatten\nopt_clean\n'
                    + ('pmux_competition_opt\n' if apply_pass else '')
                    + f'write_json "{folder}/raw.json"\n')
    run_plain([binary, '-Q', '-T', '-s', str(flow)], folder / 'snapshot.log', env)
    return cell_counts(folder / 'raw.json')


def formal(source, netlist, folder, binary, model, env, expect_counterexample=False):
    folder.mkdir(parents=True, exist_ok=True)
    flow = folder / 'formal.ys'
    flow.write_text(f'read_verilog "{source}"\nhierarchy -top stress\nproc\nflatten\n'
        'rename stress gold\ndesign -stash gold\n'
        f'read_verilog "{model}"\nread_verilog "{netlist}"\nhierarchy -top stress\nproc\nflatten\n'
        'rename stress gate\ndesign -stash gate\n'
        'design -copy-from gold -as gold gold\ndesign -copy-from gate -as gate gate\n'
        'miter -equiv -flatten -make_assert gold gate miter\nhierarchy -top miter\n'
        'flatten\nmemory_map\nopt_clean\n'
        'sat -verify -prove-asserts -set-def-inputs -timeout 90\n')
    code = run_plain([binary, '-Q', '-T', '-s', str(flow)], folder / 'formal.log', env, allow_failure=True)
    log = (folder / 'formal.log').read_text()
    if expect_counterexample:
        valid = code != 0 and 'SAT proof finished - model found: FAIL!' in log
        status = 'EXPECTED_COUNTEREXAMPLE' if valid else 'FAIL'
    else:
        valid = code == 0 and 'SAT proof finished - no model found: SUCCESS!' in log
        status = 'PASS' if valid else 'FAIL'
    if not valid:
        raise RuntimeError('Formal validation failed; inspect ' + str(folder / 'formal.log'))
    return dict(status=status, checker='pinned baseline Yosys 0.69 combinational SAT miter',
                model_sha256=sha(model), flow_sha256=sha(flow), log=str(folder / 'formal.log'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', type=Path)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--only', nargs='*')
    args = parser.parse_args()
    if args.worker:
        return worker(args.worker)
    if args.repeats < 3:
        parser.error('At least three independent full synthesis runs are required')
    sys.path.insert(0, str(REPO / 'clean-v11'))
    from run_competition_v11 import environment, counts
    env, manifest = environment()
    selected = [s for s in SPECS if not args.only or s['name'] in args.only]
    if not selected or (args.only and set(args.only) - {s['name'] for s in SPECS}):
        parser.error('Unknown or empty case selection')
    output = Path(tempfile.mkdtemp(prefix='scale-1000-', dir=REPO / 'clean-v11'))
    report = dict(status='RUNNING', created_utc=datetime.now(timezone.utc).isoformat(),
                  output=str(output), harness_sha256=sha(SCRIPT), repeats=args.repeats,
                  repository_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip(),
                  logical_cpus=os.cpu_count(),
                  manifest=manifest, kernel=platform.release(), platform=platform.platform(),
                  limits=dict(input_nodes=LIMIT_NODES, wall_seconds=LIMIT_SECONDS, memory_bytes=LIMIT_BYTES),
                  node_policy='Both proc/flatten/opt_clean input RTLIL cell count and original default mapped total cell count must be <=1000; $scopeinfo excluded. Actual counts, not generator estimates.',
                  memory_policy='Isolated kernel cgroup-v2 charged memory.peak AND conservative simultaneous summed-RSS upper bound must both be <=2e9 bytes. Includes Python worker, Yosys, ABC and all descendants; swap disabled. RSS bound uses largest reaped process HWM times kernel task peak or enforced 16-task cap; pids-limit events must be zero.',
                  measurement_references=['https://docs.kernel.org/admin-guide/cgroup-v2.html','https://www.kernel.org/pub/linux/docs/man-pages/book/man-pages-6.7.pdf','https://www.man7.org/linux/man-pages/man2/PR_SET_CHILD_SUBREAPER.2const.html'],
                  time_policy='Maximum full read/synth_intel/write wall time across fresh processes; kernel memory setup and formal verification outside the optimization timer.',
                  proof_policy='All new fixtures are combinational; both mapped roles are proved against source with pinned baseline Yosys SAT and the existing restricted Cyclone IV inverse model. Existing four-case EQY proofs are separate evidence.',
                  scope='Current Ubuntu host and explicitly listed fixed-seed structures, not proof for every possible <=1000-node circuit or official eLinx scoring.',
                  cases=[])
    def checkpoint():
        save(output / 'report.json', report)
        save(REPO / 'clean-v11' / 'scale-1000-latest.json', report)
    checkpoint()
    try:
        meter = Meter(output / 'meter', env['PATH'])
        probe = meter.run([], output / 'allocation-probe.log', allocation_probe=True)
        if probe['cgroup_memory_peak_bytes'] < 128 * 1024 * 1024:
            raise RuntimeError('Two-child memory allocation was not accounted as a sum')
        report['memory_meter_positive_control'] = probe
        checkpoint()
        print('METER_PASS', round(probe['cgroup_memory_peak_bytes']/1048576, 2), 'MiB', flush=True)
        for spec in selected:
            case = output / spec['name']
            case.mkdir()
            profile = case / 'calibration'
            profile.mkdir()
            chosen = None
            # Grow actual PMUX content first. Additional observed mixed logic
            # fills both count definitions toward the 1000-cell boundary.
            for groups in range(1, spec['max_groups'] + 1):
                folder = profile / str(groups)
                folder.mkdir()
                source = folder / 'input.v'
                source.write_text(generate(spec, groups))
                raw = raw_snapshot(source, folder / 'raw', manifest['baseline'], env)
                flow = write_flow(folder / 'baseline', source)
                measured = meter.run([manifest['baseline'], '-Q', '-T', '-s', str(flow)], folder / 'baseline.log')
                mapped = cell_counts(folder / 'baseline/netlist.json')
                if max(raw['total'], mapped['total']) > 850:
                    if chosen is None and max(raw['total'], mapped['total']) <= LIMIT_NODES:
                        chosen = (groups, raw, mapped)
                    break
                chosen = (groups, raw, mapped)
            if chosen is None:
                raise RuntimeError('Even one PMUX group exceeds the input-node acceptance scope: ' + spec['name'])
            groups, raw, mapped = chosen
            triple = min(max(0, (mapped['total'] - raw['total']) // 2),
                         (LIMIT_NODES - raw['total']) // 3, LIMIT_NODES - mapped['total'])
            simple = min(LIMIT_NODES - raw['total'] - 3 * triple,
                         LIMIT_NODES - mapped['total'] - triple)
            source = case / 'input.v'
            # ABC ordering can slightly change the mapped PMUX count when
            # unrelated filler is added. Admit only the observed final count.
            for adjustment in range(16):
                source.write_text(generate(spec, groups, triple, simple))
                actual_raw = raw_snapshot(source, case / 'before', manifest['baseline'], env)
                preflight = case / 'preflight'
                preflow = write_flow(preflight, source)
                meter.run([manifest['baseline'], '-Q', '-T', '-s', str(preflow)],
                          preflight / f'adjustment-{adjustment}.log')
                pre_mapped = cell_counts(preflight / 'netlist.json')
                overflow = max(actual_raw['total'], pre_mapped['total']) - LIMIT_NODES
                if overflow <= 0:
                    if max(actual_raw['total'], pre_mapped['total']) >= 950:
                        break
                    # Reducing a triple filler to cure a mapped overflow can
                    # leave too much headroom. Fill that observed headroom
                    # with independent one-cell logic, then measure again.
                    simple += min(LIMIT_NODES - actual_raw['total'],
                                  LIMIT_NODES - pre_mapped['total'])
                    continue
                remove = min(simple, overflow + 2)
                simple -= remove
                if not remove:
                    remove_triple = min(triple, overflow + 2)
                    if not remove_triple:
                        raise RuntimeError('PMUX content exceeds the calibrated input-node scope')
                    triple -= remove_triple
            else:
                raise RuntimeError('Unable to calibrate a <=1000-cell fixture')
            after_raw = raw_snapshot(source, case / 'after', manifest['candidate'], env, apply_pass=True)
            row = dict(name=spec['name'], generator=dict(spec, groups=groups, triple_filler=triple, simple_filler=simple),
                       source=str(source), source_sha256=sha(source), input_rtlil=actual_raw,
                       after_pass_rtlil=after_raw, roles={})
            report['cases'].append(row)
            checkpoint()
            for role in ('baseline', 'candidate'):
                folder = case / role
                flow = write_flow(folder, source)
                row['roles'][role] = dict(samples=[], flow=str(flow))
            for repeat in range(args.repeats):
                for role in (('baseline','candidate') if repeat % 2 == 0 else ('candidate','baseline')):
                    folder = case / role
                    sample = meter.run([manifest[role], '-Q', '-T', '-s', str(folder / 'flow.ys')],
                                       folder / f'run-{repeat}.log')
                    row['roles'][role]['samples'].append(sample)
                    resource = counts(folder / 'netlist.json', 'stress')
                    previous = row['roles'][role].get('counts')
                    if previous is not None and previous != resource:
                        raise RuntimeError('Non-deterministic resource counts')
                    row['roles'][role]['counts'] = resource
                    row['roles'][role]['mapped_total_cells'] = sum(v for k,v in resource['by_type'].items() if k != '$scopeinfo')
                    checkpoint()
                    print('RUN',spec['name'],role,repeat+1,round(sample['wall_seconds'],3),'s',
                          round(sample['cgroup_memory_peak_bytes']/1048576,2),'MiB',flush=True)
            baseline = row['roles']['baseline']
            candidate = row['roles']['candidate']
            if max(actual_raw['total'], baseline['mapped_total_cells']) > LIMIT_NODES:
                raise RuntimeError('Actual input counts exceeded 1000 after calibration')
            if max(actual_raw['total'], baseline['mapped_total_cells']) < 950:
                raise RuntimeError('Fixture did not reach the promised boundary scale')
            row['input_scope_pass'] = True
            for role in ('baseline', 'candidate'):
                data = row['roles'][role]
                data['max_wall_seconds'] = max(s['wall_seconds'] for s in data['samples'])
                data['median_wall_seconds'] = statistics.median(s['wall_seconds'] for s in data['samples'])
                data['max_cgroup_memory_peak_bytes'] = max(s['cgroup_memory_peak_bytes'] for s in data['samples'])
                data['max_rss_tree_upper_bound_bytes'] = max(s['rss_tree_upper_bound_bytes'] for s in data['samples'])
                data['performance_pass'] = all(s['performance_pass'] for s in data['samples'])
                data['formal'] = formal(source, case / role / 'netlist.v', case / role / 'formal',
                                        manifest['baseline'], REPO / 'clean-v11/formal_cycloneiv.v', env)
                logs = '\n'.join((case / role / f'run-{i}.log').read_text() for i in range(args.repeats))
                data['shared_tree_trigger_count'] = len(re.findall(r'^PMUX_SHARED_TREE cells=', logs, re.M))
                data['pass_version_v14_seen'] = 'Executing PMUX_COMPETITION_OPT v14.' in logs
                data['estimated_table_targets_per_run'] = [sum(int(m.group(1)) for m in re.finditer(r'^PMUX_TREE_ESTIMATE cells=(\d+)', (case / role / f'run-{i}.log').read_text(), re.M)) for i in range(args.repeats)]
            if not candidate['pass_version_v14_seen']:
                raise RuntimeError('Wrong candidate algorithm version')
            row['mapped_total_nonincrease'] = candidate['mapped_total_cells'] <= baseline['mapped_total_cells']
            row['status'] = 'PASS'
            checkpoint()
            print('CASE_PASS',spec['name'],'nodes',actual_raw['total'],baseline['mapped_total_cells'],
                  'candidate',candidate['mapped_total_cells'],flush=True)
        first = report['cases'][0]
        wrong = output / 'wrong-output.v'
        g = first['generator']
        wrong.write_text(generate(g, g['groups'], g['triple_filler'], g['simple_filler'], wrong=True))
        report['formal_negative_control'] = formal(Path(first['source']), wrong, output / 'negative',
            manifest['baseline'], REPO / 'clean-v11/formal_cycloneiv.v', env, expect_counterexample=True)
        report['all_performance_pass'] = all(c['roles']['candidate']['performance_pass'] for c in report['cases'])
        report['all_formal_pass'] = all(c['roles'][r]['formal']['status'] == 'PASS' for c in report['cases'] for r in ('baseline','candidate'))
        report['all_mapped_totals_nonincrease'] = all(c['mapped_total_nonincrease'] for c in report['cases'])
        report['max_candidate_wall_seconds'] = max(c['roles']['candidate']['max_wall_seconds'] for c in report['cases'])
        report['max_candidate_memory_bytes'] = max(c['roles']['candidate']['max_cgroup_memory_peak_bytes'] for c in report['cases'])
        report['max_candidate_rss_upper_bound_bytes'] = max(c['roles']['candidate']['max_rss_tree_upper_bound_bytes'] for c in report['cases'])
        report['area_regressions'] = [dict(name=c['name'],baseline=c['roles']['baseline']['mapped_total_cells'],candidate=c['roles']['candidate']['mapped_total_cells']) for c in report['cases'] if not c['mapped_total_nonincrease']]
        report['overall_competition_acceptance'] = 'NOT_ASSESSED; performance and functional scope only, area regressions are reported separately'
        report['status'] = 'PASS' if report['all_performance_pass'] and report['all_formal_pass'] else 'FAIL'
        checkpoint()
        target = REPO / 'validation/scale-1000'
        target.mkdir(parents=True, exist_ok=True)
        save(target / 'report.json', report)
        print('SCALE_ACCEPTANCE', report['status'],len(report['cases']),'cases',
              round(report['max_candidate_wall_seconds'],3),'s',
              round(report['max_candidate_memory_bytes']/1048576,2),'MiB',output,flush=True)
        return 0 if report['status'] == 'PASS' else 1
    except Exception as exc:
        report.update(status='FAIL', error=str(exc))
        checkpoint()
        print('SCALE_ACCEPTANCE FAIL',str(exc),output,flush=True)
        raise


if __name__ == '__main__':
    sys.exit(main())
