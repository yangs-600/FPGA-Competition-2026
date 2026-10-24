#!/usr/bin/env python3
"""Run unchanged repository checks and separately report root-Yosys metrics.

Do not treat the upstream harness's top-level PASS as an efficiency PASS.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import statistics
import subprocess
import sys
import time

REPO = Path(__file__).resolve().parents[1]
LOCAL = REPO/'local-repro'
ROOT = REPO/'clean-v11'
sys.path.insert(0, str(ROOT))
from run_competition_v11 import environment, counts


def root_measure(cmd, env, logfile):
    """Sample root PID VmHWM only; wait4 CPU includes waited ABC descendants."""
    peak = 0
    samples = 0
    started = time.monotonic()
    with logfile.open('w') as log:
        p = subprocess.Popen(cmd, env=env, stdout=log, stderr=subprocess.STDOUT,
                             start_new_session=True)
        while True:
            try:
                for line in Path(f'/proc/{p.pid}/status').read_text().splitlines():
                    if line.startswith('VmHWM:'):
                        peak = max(peak, int(line.split()[1]))
                        samples += 1
            except (FileNotFoundError, ProcessLookupError):
                pass
            pid, status, usage = os.wait4(p.pid, os.WNOHANG)
            if pid:
                break
            if time.monotonic() - started > 120:
                os.killpg(p.pid, signal.SIGKILL)
                os.waitpid(p.pid, 0)
                raise RuntimeError('Synthesis timeout')
            time.sleep(0.001)
        p.returncode = os.waitstatus_to_exitcode(status)
    if p.returncode or not peak:
        raise RuntimeError('Synthesis failed or missing memory samples: ' + str(logfile))
    return dict(wall_seconds=time.monotonic()-started,
                cpu_seconds=usage.ru_utime+usage.ru_stime,
                root_sampled_vmhwm_kib=peak, samples=samples,
                wait4_peak_rss_kib=usage.ru_maxrss)


def overhead(b, c):
    return 100 * (c / b - 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repeats', type=int, default=21)
    parser.add_argument('--measure-only', action='store_true')
    args = parser.parse_args()
    if args.repeats < 3:
        parser.error('At least 3 repeats required')
    logs = LOCAL/'logs'
    logs.mkdir(exist_ok=True)
    env, manifest = environment()
    env['PATH'] = str(ROOT/'toolchains/yosys-0.69/proof-bin') + ':/usr/bin:/bin'
    stages = [('four-cases', ['scripts/run_current.py', '--repeats', str(args.repeats)]),
              ('postabc', ['scripts/verify_postabc_ilang.py']),
              ('fixtures', ['clean-v11/test_shared_tree.py'])]
    if not args.measure_only:
        for name, arguments in stages:
            print('RUNNING', name, flush=True)
            with (logs/(name+'.log')).open('w') as log:
                subprocess.run(['/usr/bin/python3', '-E', '-u', *arguments],
                               cwd=REPO, env=env, stdout=log,
                               stderr=subprocess.STDOUT, check=True)
            print('FINISHED', name, flush=True)
    original = json.loads((ROOT/'competition-v11-latest.json').read_text())
    fixtures = json.loads((ROOT/'shared-tree-tests-latest.json').read_text())
    postpath = max(ROOT.glob('postabc-*/report.json'), key=lambda p: p.stat().st_mtime)
    post = json.loads(postpath.read_text())
    assert original['status'] == fixtures['status'] == post['status'] == 'PASS'
    report = dict(status='MEASURING', repository_commit=manifest['repository_commit'],
                  functional_status='PASS', original_report=original['report_dir']+'/report.json',
                  postabc_report=str(postpath), fixtures_report=str(ROOT/'shared-tree-tests-latest.json'),
                  mapped_eqy_proofs=8, postabc_eqy_proofs=8,
                  boundary_eqy_proofs=len(fixtures['cases']),
                  negative_controls=[original['negative_control'], post['negative_control']['status']],
                  metric='Per-case LUT plus standalone NOT mean; DFF and other cells nonincrease',
                  average_lut_gain_percent=original['average_lut_gain_percent'],
                  average_logic_gain_percent=original['average_gain_percent'],
                  timing='Each sample is an independent complete read/synth/write run; EQY excluded. Wall time is primary; CPU is supplemental.',
                  memory='Root Yosys PID VmHWM sampled every 1 ms; not a process-tree sum. Sampled value is a lower bound if a higher last-millisecond peak is missed.',
                  efficiency_scope='Local Ubuntu cross-check only, not official Windows or hidden-test acceptance',
                  summary_policy='First raw pair and median of alternating paired runs are both retained; no best-of filtering.',
                  cases=[])
    dest = LOCAL/'result.json'
    def save():
        dest.write_text(json.dumps(report, indent=2)+'\n')
    save()
    measurements = LOCAL/'measurements'
    measurements.mkdir(exist_ok=True)
    keys = ('wall_seconds', 'cpu_seconds', 'root_sampled_vmhwm_kib')
    for prior in original['cases']:
        name = prior['name']
        row = dict(name=name, roles={}, logic_gain_percent=prior['gain_percent'])
        commands = {}
        for role in ('baseline', 'candidate'):
            data = prior['roles'][role]
            row['roles'][role] = dict(lut=data['logic_cells'], dff=data['dff_cells'],
                                     by_type=data['by_type'], samples=[])
            commands[role] = [manifest[role], '-Q', '-T', '-q', '-s', str(Path(data['path'])/'flow.ys')]
            root_measure(commands[role], env, measurements/f'{name}-{role}-warmup.log')
        for n in range(args.repeats):
            for role in (('baseline', 'candidate') if n % 2 == 0 else ('candidate', 'baseline')):
                sample = root_measure(commands[role], env, measurements/f'{name}-{role}-{n:02d}.log')
                row['roles'][role]['samples'].append(sample)
        for role, data in row['roles'].items():
            data['median'] = {k:statistics.median(s[k] for s in data['samples']) for k in keys}
            data['range'] = {k:[min(s[k] for s in data['samples']), max(s[k] for s in data['samples'])] for k in keys}
            assert counts(Path(prior['roles'][role]['path'])/'netlist.json', name)['by_type'] == data['by_type']
        b, c = row['roles']['baseline'], row['roles']['candidate']
        row['median_overhead_percent'] = {k:overhead(b['median'][k], c['median'][k]) for k in keys}
        row['first_pair_overhead_percent'] = {k:overhead(b['samples'][0][k], c['samples'][0][k]) for k in keys}
        row['median_5pct_pass'] = all(row['median_overhead_percent'][k] <= 5 for k in ('wall_seconds', 'root_sampled_vmhwm_kib'))
        row['first_pair_5pct_pass'] = all(row['first_pair_overhead_percent'][k] <= 5 for k in ('wall_seconds', 'root_sampled_vmhwm_kib'))
        report['cases'].append(row)
        save()
        print(name, 'ROOT_METRICS', row['median_overhead_percent'], flush=True)
    report['all_median_5pct_pass'] = all(r['median_5pct_pass'] for r in report['cases'])
    report['all_first_pair_5pct_pass'] = all(r['first_pair_5pct_pass'] for r in report['cases'])
    report['original_harness_5pct_pass'] = original['all_measured_5pct_pass']
    report['status'] = 'FUNCTIONAL_PASS_LOCAL_PERFORMANCE_PASS' if all((report['all_median_5pct_pass'], report['all_first_pair_5pct_pass'], report['original_harness_5pct_pass'])) else 'FUNCTIONAL_PASS_PERFORMANCE_REVIEW'
    environment()  # Revalidate tool and RTL hashes after all tests.
    save()
    print(report['status'], dest, flush=True)


if __name__ == '__main__':
    main()
