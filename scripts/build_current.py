#!/usr/bin/env python3
"""Rebuild the repository's current PMUX integration using verified local dependencies."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tarfile
import time

YOSYS_COMMIT = '9f75ca1f9834a39a863915b5dae0c7b1e33533bc'
YOSYS_ARCHIVE_SHA = '086045e23253917b93c71fc2d9db495df3c153cdc5d212bac505df7c4ad62e2f'
EQY_COMMIT = '4a72eb94fc253062464afee4d0018359017bb846'
EQY_ARCHIVE_SHA = 'dd1a4c5edcf83353c66e9765661cc332f4c7f6f122585c97da68290eab230291'


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def write_json(path, data):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(data, indent=2) + '\n')
    temporary.replace(path)


def output(command, cwd=None, env=None):
    return subprocess.check_output(command, cwd=cwd, env=env, text=True).strip()


def unpack(archive, destination):
    if destination.exists():
        raise RuntimeError('Refusing to overwrite source directory: ' + str(destination))
    destination.mkdir()
    with tarfile.open(archive) as bundle:
        bundle.extractall(destination, filter='data')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dependencies', type=Path)
    parser.add_argument('--oss-suite', type=Path, default=Path.home() / 'oss-cad-suite')
    parser.add_argument('--jobs', type=int, default=1, choices=(1, 2))
    parser.add_argument('--repeats', type=int, default=21)
    args = parser.parse_args()
    if sys.platform != 'linux' or args.repeats < 3:
        parser.error('Ubuntu and at least 3 repeats are required')
    repository = Path(__file__).resolve().parent.parent
    root = repository / 'clean-v11'
    dependencies = (args.dependencies or repository.parent).resolve()
    old_root = dependencies / 'clean-v11'
    work = root / 'toolchains/yosys-0.69'
    build = work / 'build-repro'
    source = work / 'src'
    logs = work / 'rebuild-logs'
    logs.mkdir(parents=True, exist_ok=True)
    status_file = root / 'local-build-v14-status.json'

    def stage(name, **extra):
        write_json(status_file, dict(stage=name, time=time.time(), **extra))
        print(name, flush=True)

    def run(command, logfile, cwd=None):
        with (logs / logfile).open('a') as stream:
            stream.write('\nCOMMAND ' + repr(command) + '\n')
            stream.flush()
            subprocess.run(command, cwd=cwd, env=env, stdout=stream,
                           stderr=subprocess.STDOUT, check=True)

    env = dict(os.environ, PATH='/usr/bin:/bin:' + os.environ.get('PATH', ''), CCACHE_DISABLE='1')
    env.pop('PYTHONHOME', None)
    env.pop('PYTHONPATH', None)
    stage('checking_dependencies')
    for name in ('git', 'make', 'gcc', 'g++', 'bison', 'flex', 'pkg-config'):
        if not shutil.which(name, path=env['PATH']):
            raise RuntimeError('Missing build dependency: ' + name)
    subprocess.run(['pkg-config', '--exists', 'tcl', 'readline', 'libffi', 'zlib'], env=env, check=True)
    cmake = dependencies / 'toolchains/cmake-3.31.6/bin/cmake'
    suite = args.oss_suite.resolve()
    sby = suite / 'bin/sby'
    build_python = suite / 'bin/tabbypy3'
    for path in (cmake, sby, build_python):
        if not path.is_file():
            raise RuntimeError('Missing retained dependency: ' + str(path))
    print(output([str(cmake), '--version']).splitlines()[0], flush=True)
    if shutil.disk_usage(repository).free < 4 * 2**30:
        raise RuntimeError('At least 4 GiB free space is required')

    old_manifest = old_root / 'toolchains/yosys-0.69/competition-v11/manifest.json'
    old_data = json.loads(old_manifest.read_text())
    old_hashes = {old_data[key]: old_data[key + '_sha256'] for key in ('baseline', 'candidate', 'abc')}
    for path, checksum in old_hashes.items():
        if digest(path) != checksum:
            raise RuntimeError('Retained original environment changed: ' + path)

    patch = work / 'competition-v11/synth-intel-competition.patch'
    plugin = root / 'pmux_competition_v11.cc'
    if plugin.read_text() != (repository / 'src/pmux_competition_v11.cc').read_text():
        raise RuntimeError('The two tracked PMUX source copies differ')
    if 'Executing PMUX_COMPETITION_OPT v14.' not in plugin.read_text():
        raise RuntimeError('Expected the current v14 implementation')
    head = output(['git', 'rev-parse', 'HEAD'], repository)
    tracked_inputs = [plugin, patch, root / 'run_competition_v11.py', root / 'test_shared_tree.py']
    for path in tracked_inputs:
        committed = output(['git', 'show', 'HEAD:' + path.relative_to(repository).as_posix()], repository)
        if committed.replace('\r\n', '\n') != path.read_text().rstrip('\n'):
            raise RuntimeError('Tracked input differs from the current commit: ' + str(path))
    inputs = {str(path): digest(path) for path in tracked_inputs}
    plan = dict(repository_commit=head, inputs=inputs, cmake=str(cmake),
                build_python=str(build_python), external_objects_copied=0,
                yosys_source_sha256=YOSYS_ARCHIVE_SHA, eqy_source_sha256=EQY_ARCHIVE_SHA)
    plan_path = work / 'rebuild-plan.json'
    if plan_path.exists():
        if json.loads(plan_path.read_text()) != plan:
            raise RuntimeError('Build inputs changed; preserve this build and use a new independent build')
    else:
        if source.exists() or build.exists():
            raise RuntimeError('Existing unrecorded source/build directory; refusing to reuse it')
        write_json(plan_path, plan)
    for target, origin, checksum in (
        (work / 'source.tar.gz', old_root / 'toolchains/yosys-0.69/source.tar.gz', YOSYS_ARCHIVE_SHA),
        (root / 'toolchains/eqy-0.69/source.tar', old_root / 'toolchains/eqy-0.69/source.tar', EQY_ARCHIVE_SHA),
    ):
        if digest(origin) != checksum:
            raise RuntimeError('Source archive checksum mismatch: ' + str(origin))
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copy2(origin, target)
        if digest(target) != checksum:
            raise RuntimeError('Copied archive checksum mismatch: ' + str(target))

    if not source.exists():
        stage('extracting_pristine_yosys')
        unpack(work / 'source.tar.gz', source)
    if output(['git', 'rev-parse', 'HEAD'], source) != YOSYS_COMMIT:
        raise RuntimeError('Wrong Yosys source commit')
    cfg = [str(cmake), '-S', str(source), '-B', str(build), '-G', 'Unix Makefiles',
           '-DCMAKE_BUILD_TYPE=Release', '-DCMAKE_C_COMPILER=/usr/bin/gcc',
           '-DCMAKE_CXX_COMPILER=/usr/bin/g++', '-DYOSYS_WITHOUT_SLANG=ON',
           '-DYOSYS_USE_BUNDLED_LIBS=ON', '-DBUILD_SHARED_LIBS=OFF',
           '-DYOSYS_WITH_PYTHON=OFF', '-DPython3_EXECUTABLE=' + str(build_python),
           '-DCMAKE_C_COMPILER_LAUNCHER=', '-DCMAKE_CXX_COMPILER_LAUNCHER=']
    compile_command = [str(cmake), '--build', str(build), '--parallel', str(args.jobs)]
    baseline = build / 'yosys-original'
    abc = build / 'yosys-abc'
    baseline_marker = work / 'rebuild-baseline.json'
    integrated = source / 'passes/opt/pmux_competition_opt.cc'
    if not baseline_marker.exists():
        if integrated.exists():
            raise RuntimeError('Cannot build an upstream baseline from a patched tree')
        stage('building_fresh_baseline', log=str(logs / 'baseline.log'))
        run(cfg, 'baseline.log', source)
        run(compile_command, 'baseline.log', source)
        shutil.copy2(build / 'yosys', baseline)
        write_json(baseline_marker, dict(baseline=digest(baseline), abc=digest(abc)))
    frozen = json.loads(baseline_marker.read_text())
    if digest(baseline) != frozen['baseline'] or digest(abc) != frozen['abc']:
        raise RuntimeError('Fresh baseline or ABC was modified')
    rejected = subprocess.run([str(baseline), '-Q', '-T', '-p', 'pmux_competition_opt'], env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if rejected.returncode == 0 or 'No such command' not in rejected.stdout:
        raise RuntimeError('Baseline unexpectedly contains the candidate pass')
    stage('applying_repository_v14_patch')
    if not integrated.exists():
        for name in ('passes/opt/CMakeLists.txt', 'techlibs/intel/CMakeLists.txt', 'techlibs/intel/synth_intel.cc'):
            path = source / name
            upstream = subprocess.check_output(['git', 'show', 'HEAD:' + name], cwd=source)
            if path.read_bytes().replace(b'\r\n', b'\n') != upstream.replace(b'\r\n', b'\n'):
                raise RuntimeError('Unexpected source modification before patch: ' + name)
            path.write_bytes(path.read_bytes().replace(b'\r\n', b'\n'))
        run(['git', 'apply', '--check', str(patch)], 'patch.log', source)
        run(['git', 'apply', str(patch)], 'patch.log', source)
    if integrated.read_text() != plugin.read_text():
        raise RuntimeError('Patch implementation does not match repository PMUX source')
    run(['git', 'apply', '--check', '--reverse', str(patch)], 'patch.log', source)
    stage('building_repository_v14', log=str(logs / 'candidate.log'))
    run(cfg, 'candidate.log', source)
    run(compile_command, 'candidate.log', source)
    candidate = build / 'yosys-competition-reconstructed'
    shutil.copy2(build / 'yosys', candidate)
    if digest(baseline) != frozen['baseline'] or digest(abc) != frozen['abc']:
        raise RuntimeError('Candidate build changed the baseline/ABC')
    versions = {role: output([str(path), '-V'], env=env)
                for role, path in (('baseline', baseline), ('candidate', candidate))}
    if any(not version.startswith('Yosys 0.69 (') for version in versions.values()):
        raise RuntimeError('Expected exact Yosys 0.69: ' + repr(versions))
    help_text = output([str(candidate), '-Q', '-T', '-p', 'help pmux_competition_opt'], env=env)
    banner = output([str(candidate), '-Q', '-T', '-p', 'pmux_competition_opt'], env=env)
    if 'safely completes default codes' not in help_text or 'PMUX_COMPETITION_OPT v14.' not in banner:
        raise RuntimeError('Compiled candidate contains a stale pass')
    (logs / 'candidate-version-check.log').write_text(help_text + '\n' + banner + '\n')
    proof = work / 'proof-bin'
    proof.mkdir(exist_ok=True)
    link = proof / 'yosys'
    if link.is_symlink():
        if link.resolve() != baseline.resolve():
            raise RuntimeError('Unexpected proof Yosys link')
    elif link.exists():
        raise RuntimeError('Unexpected proof executable')
    else:
        link.symlink_to(baseline)
    wrapper = proof / 'sby'
    wrapper.write_text('#!/bin/sh\nexec ' + shlex.quote(str(sby)) + ' --yosys ' +
                       shlex.quote(str(baseline)) + ' --abc ' + shlex.quote(str(abc)) + ' "$@"\n')
    wrapper.chmod(0o755)

    stage('building_matching_eqy_069')
    eqy_work = root / 'toolchains/eqy-0.69'
    eqy_source = eqy_work / 'src-repro'
    prefix = eqy_work / 'install-repro'
    if not eqy_source.exists():
        unpack(eqy_work / 'source.tar', eqy_source)
    # This verified release archive uses export-substituted .gittag and has
    # no embedded Git repository. Do not accidentally read the parent repo HEAD.
    if (eqy_source / '.gittag').read_text().strip() != 'v0.69':
        raise RuntimeError('Wrong EQY source release tag')
    run(['make', '-j' + str(args.jobs), 'install', 'YOSYS_CONFIG=' + str(build / 'yosys-config'),
         'PREFIX=' + str(prefix)], 'eqy.log', eqy_source)
    eqy_executable = prefix / 'bin/eqy'
    eqy_version = output(['/usr/bin/python3', '-E', str(eqy_executable), '--version'], env=env)
    if eqy_version != 'EQY v0.69':
        raise RuntimeError('Wrong EQY version: ' + eqy_version)
    # Validate the system Python dependencies before starting formal proofs.
    subprocess.run(['/usr/bin/python3', '-E', '-c', 'import click'], env=env, check=True)
    eqy_manifest = dict(commit=EQY_COMMIT, version=eqy_version, source_sha256=EQY_ARCHIVE_SHA,
                        executable=str(eqy_executable),
                        files={str(path): digest(path) for path in sorted(prefix.rglob('*')) if path.is_file()})
    eqy_manifest['files'][str(wrapper)] = digest(wrapper)
    write_json(eqy_work / 'manifest.json', eqy_manifest)
    mapping = build / 'share/intel/competition_abc_v11.abc'
    if mapping.read_text().strip() != (root / 'competition_abc_dch.abc').read_text().strip():
        raise RuntimeError('Compiled ABC9 mapping script differs from the repository')
    manifest = dict(yosys_release='0.69', yosys_commit=YOSYS_COMMIT,
                    source_sha256=YOSYS_ARCHIVE_SHA, repository_commit=head,
                    baseline=str(baseline), candidate=str(candidate), abc=str(abc),
                    patch=str(patch), plugin_source=str(plugin), abc_script=str(mapping),
                    integrated_source=str(integrated), integrated_source_sha256=digest(integrated),
                    build_config=cfg, external_objects_copied=0,
                    baseline_version=versions['baseline'], candidate_version=versions['candidate'])
    for role in ('baseline', 'candidate', 'abc', 'patch', 'plugin_source', 'abc_script'):
        manifest[role + '_sha256'] = digest(manifest[role])
    write_json(work / 'competition-v11/manifest.json', manifest)
    stage('running_four_cases_21_pairs', log=str(logs / 'validation.log'))
    run(['/usr/bin/python3', '-E', '-u', str(repository / 'scripts/run_current.py'),
         '--repeats', str(args.repeats)], 'validation.log', repository)
    report = json.loads((root / 'competition-v11-latest.json').read_text())
    if report['status'] != 'PASS' or not report['all_other_cell_types_nonincrease']:
        raise RuntimeError('Formal/resource checks failed')
    stage('running_v14_boundary_fixtures', log=str(logs / 'fixtures.log'))
    run(['/usr/bin/python3', '-E', '-u', str(root / 'test_shared_tree.py')], 'fixtures.log', root)
    fixtures = json.loads((root / 'shared-tree-tests-latest.json').read_text())
    if fixtures['status'] != 'PASS' or len(fixtures['cases']) != 11:
        raise RuntimeError('Expected all 11 v14 fixtures to pass')
    stage('sampling_process_tree_pss', log=str(logs / 'pss.log'))
    run(['/usr/bin/python3', '-E', '-u', str(root / 'measure_competition_v11_pss.py')], 'pss.log', root)
    pss = json.loads((root / 'competition-v11-tree-pss.json').read_text())
    for path, checksum in old_hashes.items():
        if digest(path) != checksum:
            raise RuntimeError('Original environment was modified: ' + path)
    for path, checksum in inputs.items():
        if digest(path) != checksum:
            raise RuntimeError('Repository input changed during build: ' + path)
    perf_ok = report['all_measured_5pct_pass'] and all(row['max_overhead_percent'] <= 5 for row in pss['cases'])
    receipt = dict(status='PASS' if perf_ok else 'FUNCTIONAL_PASS_PERFORMANCE_REVIEW',
                   repository_commit=head, repository=str(repository), manifest=str(work / 'competition-v11/manifest.json'),
                   source_input_sha256=inputs, external_objects_copied=0, original_environment_unchanged=True,
                   report_dir=report['report_dir'], fixtures_dir=fixtures['directory'],
                   proofs=8, negative_control=report['negative_control'], fixtures=len(fixtures['cases']),
                   average_lut_gain_percent=report.get('average_lut_gain_percent',report['average_gain_percent']),
                   average_logic_gain_percent=report['average_gain_percent'], repeats=args.repeats,
                   all_measured_5pct_pass=report['all_measured_5pct_pass'],
                   all_sampled_pss_5pct_pass=all(row['max_overhead_percent'] <= 5 for row in pss['cases']),
                   note='Fresh source/build on the current Ubuntu with retained compiler, CMake and OSS CAD Suite. Linux measurements are cross-checks, not official Windows scoring.')
    write_json(root / 'local-build-v14-receipt.json', receipt)
    stage(receipt['status'], receipt=str(root / 'local-build-v14-receipt.json'))
    print(json.dumps(receipt, indent=2), flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        root = Path(__file__).resolve().parent.parent / 'clean-v11'
        if root.is_dir():
            write_json(root / 'local-build-v14-status.json', dict(stage='FAIL', error=str(error), time=time.time()))
        raise
