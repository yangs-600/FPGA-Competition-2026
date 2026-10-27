#!/usr/bin/env python3
"""Stage a fresh v24 WSL build for the frozen protocol; --run explicitly runs it once.

Default: validate and copy only. No historical measurement/formal results are
copied or inherited. An existing output is always refused, even after failure.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys

ROLES = ('baseline', 'candidate')
SOURCE = 'f278dfa15309f735644eb09dbcb1e385f99cb6e571912b68d9d679917d4d5b12'
ARCHIVE = '086045e23253917b93c71fc2d9db495df3c153cdc5d212bac505df7c4ad62e2f'
PATCH = '44e8e077d8ed7fb60e4173602fa89ac11598dbe0dbadb2bb88e52b8878f3d143'
ABC_SCRIPT = 'bb92697ba7adcd8f97827885daaf8ef501d49d79428b54e51122fbffc45c5fa7'
COMMIT = '9f75ca1f9834a39a863915b5dae0c7b1e33533bc'
DELIVERY_INDEX = '6390bac7b5703f3fd59f0c4e1dcdca22da84562ed8a9dec5d052e2e92b4b8710'
PINNED = {
    'run_current_cases.py': 'a738da57816cc5276fa382893162d2f7e6844673788dd6d49378cd4632e8c57b',
    'review_efficiency_v2.py': '5a745339f858db0077bb0053c635ba1b231d506d17c42831a1f8eab039d5aeb8',
    'cases_current.json': '6360cd97fb17315cc39ed6d6d8a21ce1d99dcc99b1541fe1a92d64dfeefc26da',
    'linux_metrics.py': '45d1fda7d113991425208c42a6941dbb7a5609033bc8e7ba03411c8126966466',
    'linux_root_meter.c': '77a6a1e73bd3e934476deee4cdca3299970c46cd15953ae683c9193277f1cfce',
    'linux_root_meter': 'ff5f3aa19449f92b8cd296e02d066925cd1ecb0c7d4477c858c30d2294520694',
    'linux_meter_control.c': '7450756ea588ec56702f6b12531fb6591c7255b05ed4b4903b7dd18521c7fdcc',
    'linux_meter_control': 'd38faa8421f2a11e5cadd1aef4d4322cfa8e71f2d1a20618faca739eec854b1f',
}
METER_NAMES = {'linux_metrics.py', 'linux_root_meter.c', 'linux_root_meter',
               'linux_meter_control.c', 'linux_meter_control'}
HASH = re.compile(r'^[0-9a-f]{64}$')


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def no_duplicates(pairs):
    obj = {}
    for key, value in pairs:
        require(key not in obj, 'Duplicate JSON key: ' + key)
        obj[key] = value
    return obj


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'), object_pairs_hook=no_duplicates)


def write_json(path, value, exclusive=True):
    with Path(path).open('x' if exclusive else 'w', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write('\n')


def relative(root, name):
    require(isinstance(name, str) and name and ':' not in name and '\\' not in name,
            'Noncanonical relative file: ' + str(name))
    rel = PurePosixPath(name)
    require(not rel.is_absolute() and '..' not in rel.parts and str(rel) == name,
            'Unsafe relative file: ' + name)
    current = root
    for part in rel.parts:
        current = current / part
        require(not current.is_symlink(), 'Symlink not accepted: ' + str(current))
    current.resolve().relative_to(root.resolve())
    require(current.is_file(), 'Missing regular file: ' + str(current))
    return current


def inventory(root):
    require(root.is_dir() and not root.is_symlink(), 'Invalid role/delivery root: ' + str(root))
    result = {}
    for path in sorted(root.rglob('*')):
        require(not path.is_symlink(), 'Symlink not accepted: ' + str(path))
        if path.is_dir():
            continue
        require(path.is_file(), 'Special file not accepted: ' + str(path))
        result[path.relative_to(root).as_posix()] = sha(path)
    return result


def hash_map(value, label):
    require(isinstance(value, dict) and value, 'Missing file map: ' + label)
    for name, digest in value.items():
        require(isinstance(digest, str) and HASH.fullmatch(digest), 'Invalid SHA: ' + label + '/' + name)
    return value


def checked_package(package):
    index_path = relative(package, 'delivery-manifest.json')
    require(sha(index_path) == DELIVERY_INDEX, 'Not the frozen v24 WSL delivery index')
    index = read_json(index_path)
    files = hash_map(index.get('files'), 'delivery')
    actual = inventory(package)
    require(set(actual) == set(files) | {'delivery-manifest.json'}, 'Delivery has missing or unindexed files')
    for name, digest in files.items():
        relative(package, name)
        require(actual[name] == digest, 'Delivery fingerprint mismatch: ' + name)
    for name, digest in PINNED.items():
        require(actual.get(name) == digest, 'Frozen protocol component mismatch: ' + name)
    for name in ('linux_root_meter', 'linux_meter_control'):
        require(os.access(relative(package, name), os.X_OK), 'Meter executable permission missing: ' + name)
    manifest = read_json(relative(package, 'manifest.json'))
    require(str(manifest.get('yosys_release')) == '0.69' and manifest.get('yosys_commit') == COMMIT,
            'Expected fixed upstream Yosys 0.69 identity')
    require(manifest.get('candidate_version') == 'v24-wsl' and manifest.get('source_sha256') == SOURCE
            and manifest.get('source_archive_sha256') == ARCHIVE and manifest.get('patch_sha256') == PATCH,
            'Expected frozen v24 source/archive/patch')
    require(manifest.get('measurement_files') == {name: PINNED[name] for name in METER_NAMES},
            'Unexpected frozen meter component map')
    for role in ROLES:
        require(inventory(package / role) == hash_map(manifest['roles'][role]['files'], role),
                'Frozen role/manifest mismatch: ' + role)
    require(manifest['roles']['baseline']['files']['yosys-abc'] == manifest['roles']['candidate']['files']['yosys-abc'],
            'Frozen roles have different ABC identities')
    return manifest, actual


def normalized_flags(flags):
    require(isinstance(flags, list) and all(isinstance(x, str) for x in flags), 'Missing compiler configuration')
    require(sum(x.startswith('-DCMAKE_PREFIX_PATH=') for x in flags) == 1, 'Ambiguous build dependency prefix')
    return ['-DCMAKE_PREFIX_PATH=<BUILD_ROOT>/tools/usr' if x.startswith('-DCMAKE_PREFIX_PATH=') else x for x in flags]


def checked_build(build, package, old_manifest):
    receipt_path = relative(build, 'build-receipt.json')
    receipt = read_json(receipt_path)
    require(receipt.get('schema') == 1 and receipt.get('name') == 'v24-wsl'
            and receipt.get('status') == 'BUILD_COMPLETE_NOT_EXECUTED', 'Unsupported/incomplete new build receipt')
    for key, digest in [('candidate_source_sha256', SOURCE), ('source_archive_sha256', ARCHIVE), ('patch_sha256', PATCH)]:
        require(receipt.get(key) == digest, 'New build identity mismatch: ' + key)
    old_receipt = read_json(relative(package, 'source/build-receipt.json'))
    require(normalized_flags(receipt.get('flags')) == normalized_flags(old_receipt.get('flags')),
            'New and frozen compiler configurations differ')
    require(receipt.get('abc_identical') is True and receipt.get('performance_tested') is False,
            'Receipt does not describe a completed, not-performance-tested build')
    require(isinstance(receipt.get('steps'), list) and receipt['steps']
            and all(type(s.get('returncode')) is int and s['returncode'] == 0 for s in receipt['steps']),
            'New build has an incomplete or failed recorded step; use a reviewed successful receipt')
    checked = {str(receipt_path): sha(receipt_path)}
    for name, digest in [('input/yosys-0.69-pristine.tar.gz', ARCHIVE),
                         ('input/synth-intel-competition.patch', PATCH),
                         ('source/passes/opt/pmux_competition_opt.cc', SOURCE),
                         ('source/techlibs/intel/competition_abc_v11.abc', ABC_SCRIPT)]:
        path = relative(build, name)
        require(sha(path) == digest, 'New build actual source bytes differ: ' + name)
        checked[str(path)] = digest
    roles, comparison = {}, {}
    require(set(receipt.get('roles', {})) == set(ROLES), 'Expected exactly two built roles')
    for role in ROLES:
        files = inventory(build / 'roles' / role)
        require(files == hash_map(receipt['roles'][role]['files'], 'new ' + role), 'New role receipt mismatch: ' + role)
        require(set(files) == set(old_manifest['roles'][role]['files']), 'New role resource set differs: ' + role)
        require({'yosys', 'yosys-abc'} <= set(files), 'Missing new executable pair')
        for name in ('yosys', 'yosys-abc'):
            path = relative(build / 'roles' / role, name)
            with path.open('rb') as stream:
                require(stream.read(4) == b'\x7fELF', 'Not Linux ELF: ' + str(path))
            require(os.access(path, os.X_OK), 'Not executable: ' + str(path))
        old = old_manifest['roles'][role]['files']
        comparison[role] = dict(all_files_same=files == old,
            changed_files=[name for name in files if files[name] != old[name]],
            old_yosys_sha256=old['yosys'], new_yosys_sha256=files['yosys'],
            old_abc_sha256=old['yosys-abc'], new_abc_sha256=files['yosys-abc'])
        roles[role] = dict(files=files)
    require(roles['baseline']['files']['yosys-abc'] == roles['candidate']['files']['yosys-abc'],
            'New roles must share the same ABC binary')
    require(roles['candidate']['files'].get('share/intel/competition_abc_v11.abc') == ABC_SCRIPT,
            'New role has a different fixed ABC script')
    return receipt, roles, comparison, checked


def copy_checked(source, target, digest):
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    require(sha(source) == digest and sha(target) == digest, 'Source/copy changed: ' + str(source))


def stage(package, build, output):
    require(not output.exists(), 'Output already exists; do not reuse any attempt: ' + str(output))
    for source in (package, build):
        require(output != source and source not in output.parents and output not in source.parents,
                'Output must be separate from package/build trees')
    old_manifest, package_before = checked_package(package)
    receipt, roles, comparison, build_before = checked_build(build, package, old_manifest)
    registry = read_json(relative(package, 'cases_current.json'))
    require(isinstance(registry, dict) and len(registry.get('cases', [])) == 9, 'Expected frozen nine-case registry')
    names = set(PINNED)
    for case in registry['cases']:
        require(sha(relative(package, case['path'])) == case['sha256'], 'Frozen case mismatch')
        names.add(case['path'])
    output.mkdir(parents=False, exist_ok=False)
    for name in sorted(names):
        copy_checked(relative(package, name), output / name, package_before[name])
    for role in ROLES:
        for name, digest in roles[role]['files'].items():
            copy_checked(relative(build / 'roles' / role, name), output / role / name, digest)
        require(inventory(output / role) == roles[role]['files'], 'Copied role inventory changed')
    provenance = output / 'provenance'
    copy_checked(relative(build, 'build-receipt.json'), provenance / 'build-receipt.json', build_before[str(build / 'build-receipt.json')])
    copy_checked(relative(package, 'delivery-manifest.json'), provenance / 'original-delivery-manifest.json', package_before['delivery-manifest.json'])
    shutil.copy2(Path(__file__), provenance / 'stage_rebuilt_measurement.py')
    manifest = dict(old_manifest)
    manifest.update(roles=roles, status='STAGED_NOT_EXECUTED', build_receipt_sha256=sha(provenance / 'build-receipt.json'),
        baseline_build=receipt['baseline_build'], candidate_build=receipt['candidate_build'], staged_utc=now(),
        scope='Freshly rebuilt WSL ELF roles; independent new measurements, no historical PASS inherited',
        rebuilt_delivery_origin_sha256=package_before['delivery-manifest.json'])
    write_json(output / 'manifest.json', manifest)
    require(inventory(package) == package_before, 'Frozen delivery changed during staging')
    for path, digest in build_before.items():
        require(sha(path) == digest, 'Build input/receipt changed during staging: ' + path)
    for role in ROLES:
        require(inventory(build / 'roles' / role) == roles[role]['files'], 'Build role changed during staging')
    result = dict(status='NEW_BUILD_STAGED_NOT_EXECUTED', completed_utc=now(),
        package=str(package), build_root=str(build), output=str(output),
        staging_script_sha256=sha(__file__), frozen_delivery_manifest_sha256=package_before['delivery-manifest.json'],
        build_receipt_sha256=sha(provenance / 'build-receipt.json'), manifest_sha256=sha(output / 'manifest.json'),
        runner_sha256=PINNED['run_current_cases.py'], review_v2_sha256=PINNED['review_efficiency_v2.py'],
        case_manifest_sha256=PINNED['cases_current.json'], comparison_to_frozen_roles=comparison,
        all_role_files_identical_to_frozen=all(c['all_files_same'] for c in comparison.values()),
        historical_results_copied=False, yosys_executed_by_staging=False, overall_submission_acceptance=False,
        scope='Input/provenance checks only; receipt is not a performance or equivalence PASS')
    write_json(output / 'stage-receipt.json', result)
    return result


def run_once(output, staged):
    require(not (output / 'validation-once').exists() and not (output / 'latest-current.json').exists(),
            'No previously started measurement is accepted')
    command = ['/usr/bin/python3', '-E', '-B', '-u', str(output / 'run_current_cases.py'), '--package', str(output)]
    attempt = dict(status='STARTING_ONE_FIXED_PROTOCOL', started_utc=now(), command=command,
        stage_receipt_sha256=sha(output / 'stage-receipt.json'), manifest_sha256=staged['manifest_sha256'],
        protocol='Frozen a738 runner: 10 baseline warmups per case, baseline then candidate; only prescribed five-pair reviews',
        historical_pass_inherited=False, overall_submission_acceptance=False)
    path = output / 'run-once.json'
    write_json(path, attempt)  # Exclusive once-only marker before any process.
    env = dict(os.environ, PATH='/usr/bin:/bin', LC_ALL='C', LANG='C')
    for key in ('PYTHONHOME', 'PYTHONPATH', 'YOSYS_DATDIR', 'ABC', 'YOSYS_ABC', 'LD_PRELOAD', 'LD_LIBRARY_PATH'):
        env.pop(key, None)
    try:
        with (output / 'measurement-process.log').open('xb') as log:
            code = subprocess.run(command, cwd=output, env=env, stdout=log, stderr=subprocess.STDOUT).returncode
        attempt.update(status='FIXED_PROTOCOL_PROCESS_FINISHED', runner_exit_code=code,
            process_log_sha256=sha(output / 'measurement-process.log'))
        raw = output / 'latest-current.json'
        review_code = None
        if raw.is_file():
            raw_sha = sha(raw)
            report = read_json(raw)
            attempt.update(raw_report_sha256=raw_sha, raw_status=report.get('status'))
            if report.get('status') == 'RAW_MEASUREMENTS_COMPLETE_REVIEW_AND_FORMAL_REQUIRED':
                require(report.get('manifest_sha256') == staged['manifest_sha256'], 'Raw report bound to another manifest')
                review_command = ['/usr/bin/python3', '-E', '-B', str(output / 'review_efficiency_v2.py'),
                    '--report', str(raw), '--output', str(output / 'efficiency-interpretation-view-v2.json')]
                with (output / 'offline-review-process.log').open('xb') as log:
                    review_code = subprocess.run(review_command, cwd=output, env=env, stdout=log, stderr=subprocess.STDOUT).returncode
                require(sha(raw) == raw_sha, 'Raw measurements changed during offline review')
                attempt.update(review_exit_code=review_code, review_command=review_command)
                view = output / 'efficiency-interpretation-view-v2.json'
                if view.is_file():
                    attempt['offline_view_sha256'] = sha(view)
        # Hash only after all timed runs and offline interpretation finish;
        # this check is outside every measurement interval.
        require(sha(output / 'manifest.json') == staged['manifest_sha256'], 'Staged manifest changed during execution')
        manifest = read_json(output / 'manifest.json')
        for name, digest in PINNED.items():
            require(sha(relative(output, name)) == digest, 'Staged protocol component changed: ' + name)
        for role in ROLES:
            require(inventory(output / role) == manifest['roles'][role]['files'], 'Staged role changed during execution: ' + role)
        for case in read_json(output / 'cases_current.json')['cases']:
            require(sha(relative(output, case['path'])) == case['sha256'], 'Staged input changed during execution')
        require(sha(output / 'provenance/build-receipt.json') == staged['build_receipt_sha256'], 'Copied build receipt changed')
        require(sha(output / 'provenance/original-delivery-manifest.json') == staged['frozen_delivery_manifest_sha256'],
                'Copied original delivery index changed')
        require(sha(output / 'provenance/stage_rebuilt_measurement.py') == staged['staging_script_sha256'], 'Staging script copy changed')
        attempt['input_tools_unchanged'] = True
        attempt.update(completed_utc=now(), overall_submission_acceptance=False)
        write_json(path, attempt, exclusive=False)
        # View success never overrides a failed runner or incomplete evidence.
        return code if code else (review_code if review_code is not None else 2)
    except BaseException as error:
        attempt.update(status='INTERRUPTED_OR_ERROR_RETAIN_ATTEMPT', error=repr(error), completed_utc=now())
        write_json(path, attempt, exclusive=False)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', required=True, type=Path, help='Extracted frozen WSL delivery with delivery-manifest.json')
    parser.add_argument('--build-root', required=True, type=Path, help='Completed fresh offline build with roles/ and build-receipt.json')
    parser.add_argument('--output', required=True, type=Path, help='Absent absolute ASCII directory outside both inputs; parent must exist')
    parser.add_argument('--run', action='store_true', help='Explicitly run the frozen protocol once after successful staging, then offline v2')
    args = parser.parse_args(argv)
    if sys.platform != 'linux':
        parser.error('Run inside WSL/Linux; --help is available on any platform')
    if not args.output.is_absolute() or not str(args.output).isascii() or any(c.isspace() for c in str(args.output)):
        parser.error('--output must be absolute ASCII without whitespace')
    package, build, output = args.package.resolve(), args.build_root.resolve(), args.output.resolve()
    require(output.parent.is_dir(), 'Output parent must already exist')
    staged = stage(package, build, output)
    print(json.dumps(staged, indent=2), flush=True)
    if not args.run:
        return 0
    return run_once(output, staged)


if __name__ == '__main__':
    raise SystemExit(main())
