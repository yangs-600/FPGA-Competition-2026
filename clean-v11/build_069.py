#!/usr/bin/env python3
"""Build exact Yosys v0.69 and a built-in PMUX pass in an isolated directory."""
import argparse
import datetime
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parent
WORK = ROOT / 'toolchains/yosys-0.69'
COMMIT = '9f75ca1f9834a39a863915b5dae0c7b1e33533bc'
SOURCE_SHA = '086045e23253917b93c71fc2d9db495df3c153cdc5d212bac505df7c4ad62e2f'


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for data in iter(lambda: f.read(1048576), b''):
            h.update(data)
    return h.hexdigest()


def status(stage, **extra):
    WORK.mkdir(parents=True, exist_ok=True)
    p = WORK / 'status.tmp'
    p.write_text(json.dumps(dict(stage=stage, time=datetime.datetime.now().isoformat(), **extra), indent=2))
    p.replace(WORK / 'status.json')
    print(stage, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plugin', default='pmux_area_opt_v8.cc')
    parser.add_argument('--jobs', type=int, default=1, choices=[1, 2])
    args = parser.parse_args()
    if sys.platform != 'linux':
        parser.error('Run inside Ubuntu')
    WORK.mkdir(parents=True, exist_ok=True)
    archive = WORK / 'source.tar.gz'
    if sha(archive) != SOURCE_SHA:
        raise RuntimeError('Exact-tag source archive checksum mismatch')
    cmake = ROOT / 'toolchains/cmake-3.31.6/bin/cmake'
    subprocess.run([str(cmake), '--version'], check=True)
    for name in ('git', 'make', 'gcc', 'g++', 'bison', 'flex', 'pkg-config'):
        if not shutil.which(name):
            raise RuntimeError('Missing dependency: ' + name)
    subprocess.run(['pkg-config', '--exists', 'tcl', 'readline', 'libffi', 'zlib'], check=True)
    src = WORK / 'src'
    if not src.exists():
        status('extracting')
        temp = WORK / 'src-extracting'
        temp.mkdir()
        with tarfile.open(archive) as t:
            t.extractall(temp, filter='data')
        temp.rename(src)
    if subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=src, text=True).strip() != COMMIT:
        raise RuntimeError('Wrong source commit')
    env = os.environ.copy()
    env['PATH'] = '/usr/bin:/bin:' + env.get('PATH', '')
    build = WORK / 'build'
    configure = [str(cmake), '-S', str(src), '-B', str(build), '-G', 'Unix Makefiles',
                 '-DCMAKE_BUILD_TYPE=Release', '-DCMAKE_C_COMPILER=/usr/bin/gcc',
                 '-DCMAKE_CXX_COMPILER=/usr/bin/g++', '-DYOSYS_WITHOUT_SLANG=ON',
                 '-DYOSYS_USE_BUNDLED_LIBS=ON', '-DBUILD_SHARED_LIBS=OFF',
                 '-DYOSYS_WITH_PYTHON=OFF', '-DPython3_EXECUTABLE=' + sys.executable]
    config_file = WORK / 'build-config.json'
    if config_file.exists() and json.loads(config_file.read_text()) != configure:
        raise RuntimeError('Build settings changed; use an independent build directory')
    config_file.write_text(json.dumps(configure, indent=2))
    compile_cmd = [str(cmake), '--build', str(build), '--parallel', str(args.jobs)]

    def run(commands, logfile):
        with (WORK / logfile).open('a') as log:
            for command in commands:
                log.write('\nCOMMAND ' + repr(command) + '\n')
                log.flush()
                subprocess.run(command, cwd=src, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)

    marker = WORK / 'baseline.json'
    original = build / 'yosys-original'
    abc = build / 'yosys-abc'
    target = src / 'passes/opt/pmux_area_opt.cc'
    if not marker.exists():
        if target.exists():
            raise RuntimeError('Cannot produce an upstream baseline from patched sources')
        status('building_original', log=str(WORK / 'original-build.log'))
        run([configure, compile_cmd], 'original-build.log')
        shutil.copy2(build / 'yosys', original)
        marker.write_text(json.dumps({'baseline_sha256': sha(original), 'abc_sha256': sha(abc)}))
    frozen = json.loads(marker.read_text())
    if sha(original) != frozen['baseline_sha256'] or sha(abc) != frozen['abc_sha256']:
        raise RuntimeError('Baseline or ABC was changed')
    plugin = (ROOT / args.plugin).resolve(strict=True)
    plugin_sha = sha(plugin)
    status('building_optimized', plugin=plugin.name, log=str(WORK / 'optimized-build.log'))
    if not target.exists() or sha(target) != plugin_sha:
        shutil.copy2(plugin, target)
        # copy2 preserves the original timestamp, which can be older than an
        # object compiled for another algorithm. Force dependency invalidation.
    target.touch()
    cmfile = src / 'passes/opt/CMakeLists.txt'
    original_cm = subprocess.check_output(['git', 'show', 'HEAD:passes/opt/CMakeLists.txt'], cwd=src).decode()
    patched_cm = original_cm + '\nyosys_pass(pmux_area_opt pmux_area_opt.cc)\n'
    if cmfile.read_text() != patched_cm:
        cmfile.write_text(patched_cm)
    run([configure, compile_cmd], 'optimized-build.log')
    if sha(abc) != frozen['abc_sha256']:
        raise RuntimeError('ABC changed during plugin build')
    candidate = build / ('yosys-pmux-' + plugin_sha[:16])
    shutil.copy2(build / 'yosys', candidate)
    version = subprocess.check_output([str(original), '-V'], text=True).strip()
    candidate_version = subprocess.check_output([str(candidate), '-V'], text=True).strip()
    if not all(re.match(r'^Yosys 0\.69 \(', v) for v in [version, candidate_version]):
        raise RuntimeError('Expected exact Yosys 0.69 versions: ' + repr([version, candidate_version]))
    builtin = subprocess.check_output([str(candidate), '-Q', '-T', '-p', 'help pmux_area_opt'], text=True)
    execution = subprocess.check_output([str(candidate), '-Q', '-T', '-p', 'pmux_area_opt -inspect'], text=True)
    expected_banner = re.search(r'Executing PMUX_AREA_OPT (?:prototype )?v\d+\.', plugin.read_text())
    if expected_banner and expected_banner.group() not in execution:
        raise RuntimeError('Executable contains a stale pass implementation')
    rejected = subprocess.run([str(original), '-Q', '-T', '-p', 'pmux_area_opt'], text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if 'pmux_area_opt [-inspect]' not in builtin or rejected.returncode == 0 or 'No such command' not in rejected.stdout:
        raise RuntimeError('Built-in pass isolation check failed')
    (WORK / 'builtin-check.log').write_text(builtin + execution + '\nBASELINE REJECTION\n' + rejected.stdout)
    patch = ''.join(difflib.unified_diff(original_cm.splitlines(True), patched_cm.splitlines(True),
                    fromfile='a/passes/opt/CMakeLists.txt', tofile='b/passes/opt/CMakeLists.txt'))
    patch += ''.join(difflib.unified_diff([], plugin.read_text().splitlines(True),
                    fromfile='/dev/null', tofile='b/passes/opt/pmux_area_opt.cc'))
    patch_path = WORK / ('pmux-' + plugin_sha[:16] + '.patch')
    patch_path.write_text(patch)
    manifest = dict(yosys_release='0.69', yosys_commit=COMMIT, source_sha256=SOURCE_SHA,
                    plugin_source=str(plugin), plugin_source_sha256=plugin_sha,
                    baseline=str(original), baseline_sha256=sha(original), baseline_version=version,
                    candidate=str(candidate), candidate_sha256=sha(candidate), candidate_version=candidate_version,
                    abc=str(abc), abc_sha256=sha(abc), build_config=configure, patch=str(patch_path),
                    note='Exact v0.69 tag, same ABC/backend. Plugin built into candidate; Slang disabled on both.')
    serial = json.dumps(manifest, indent=2)
    (WORK / ('manifest-' + plugin_sha[:16] + '.json')).write_text(serial)
    (WORK / 'manifest.json').write_text(serial)
    # Force EQY to use the pinned upstream 0.69 too, without replacing the suite.
    proof_bin = WORK / 'proof-bin'
    proof_bin.mkdir(exist_ok=True)
    proof = proof_bin / 'yosys'
    if not proof.exists():
        proof.symlink_to(original)
    if proof.resolve() != original.resolve():
        raise RuntimeError('Unexpected proof executable link')
    status('complete', manifest=str(WORK / 'manifest.json'))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        status('failed', error=str(exc))
        raise
