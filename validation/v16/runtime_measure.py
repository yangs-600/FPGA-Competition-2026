"""Measure baseline/candidate child CPU time with interleaved warm runs."""
import json
import resource
import statistics
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path('/home/lcx/fpga-build/clean-v11')
BUILD = ROOT / 'toolchains/yosys-0.69/build-repro'
ROLES = {
    'baseline': BUILD / 'yosys-original',
    'candidate': BUILD / 'yosys-competition-reconstructed',
}
OUT = Path(tempfile.mkdtemp(prefix='v16-runtime-', dir=ROOT))
RESULT = {
    'started_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
    'policy': '21 interleaved child-CPU runs after one warm-up; median; waited ABC included',
    'cases': [],
    'output_dir': str(OUT),
}


def run(yosys, flow, log):
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    with log.open('w') as stream:
        proc = subprocess.run([str(yosys), '-Q', '-T', '-s', str(flow)],
                              stdout=stream, stderr=subprocess.STDOUT, text=True)
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    if proc.returncode:
        raise RuntimeError(f'synthesis failed: {log}')
    return after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime


for index in range(1, 5):
    name = f'test{index}'
    case = OUT / name
    case.mkdir()
    source = ROOT / 'competition_case' / name / f'{name}.v'
    flow = case / 'flow.ys'
    flow.write_text(f'read_verilog "{source}"\nsynth_intel -family cycloneiv -top {name}\n')
    for role, yosys in ROLES.items():
        run(yosys, flow, case / f'warm-{role}.log')
    samples = {role: [] for role in ROLES}
    for repeat in range(21):
        order = list(ROLES) if repeat % 2 == 0 else list(reversed(ROLES))
        for role in order:
            samples[role].append(run(ROLES[role], flow, case / f'{repeat:02d}-{role}.log'))
    medians = {role: statistics.median(values) for role, values in samples.items()}
    RESULT['cases'].append({
        'name': name,
        'median_seconds': medians,
        'candidate_overhead_percent': (medians['candidate'] / medians['baseline'] - 1) * 100,
    })

(ROOT / 'v16-runtime-results.json').write_text(json.dumps(RESULT, indent=2))
print(json.dumps(RESULT, indent=2))
