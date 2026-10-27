#!/usr/bin/env python3
"""Fresh nine-case synthesis and EQY proof using explicitly selected package/kit.

No embedded host paths, historical PASS replay or performance-sample claim.
The verified external kit supplies the proof runtime; supplied roles synthesize
eighteen new post-ABC objects in this invocation's new output directory.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PureWindowsPath
import platform
import re
import shutil
import statistics
import subprocess
import sys

KIT_INDEX_SHA = 'ac50f798b70f4a105f8ad42e12ed16b03bb9ed87ce2ff2ad0194cdf66c4c6cd9'
CORE_SHA = '9ae28d47bd5c911777336cfdb195676c345a3cd871755056fca6d0309fc8f843'
SOURCE_SHA = 'f278dfa15309f735644eb09dbcb1e385f99cb6e571912b68d9d679917d4d5b12'
PATCH_SHA = '44e8e077d8ed7fb60e4173602fa89ac11598dbe0dbadb2bb88e52b8878f3d143'
ABC_SCRIPT_SHA = 'bb92697ba7adcd8f97827885daaf8ef501d49d79428b54e51122fbffc45c5fa7'
CASES_SHA = '6360cd97fb17315cc39ed6d6d8a21ce1d99dcc99b1541fe1a92d64dfeefc26da'
COMMIT = '9f75ca1f9834a39a863915b5dae0c7b1e33533bc'
NAME = re.compile(r'^[A-Za-z_][A-Za-z0-9_$]*$')
ROLES = ('baseline', 'candidate')


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def inside(root, name):
    value, windows = Path(name), PureWindowsPath(name)
    if value.is_absolute() or windows.is_absolute() or windows.drive or '..' in value.parts or '\\' in str(name):
        raise ValueError('Expected a relative path: ' + str(name))
    path = (root / value).resolve()
    path.relative_to(root)
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def inventory(root):
    return {p.relative_to(root).as_posix(): sha(p) for p in sorted(root.rglob('*')) if p.is_file()}


def check_index(root, files):
    for name, digest in files.items():
        if sha(inside(root, name)) != digest:
            raise RuntimeError('Changed indexed file: ' + str(root / name))


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n', encoding='utf8')


def load_module(path):
    spec = importlib.util.spec_from_file_location('onsite_pinned_formal_core', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def identity(case):
    name = str(case.get('name', case.get('id', '')))
    return name, str(case.get('top', name)), str(case['path']), str(case['sha256'])


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--package', type=Path, required=True, help='Extracted v24 WSL delivery; never modified')
    ap.add_argument('--proof-kit', type=Path, required=True, help='Extracted pinned external EQY kit; never modified')
    ap.add_argument('--output', type=Path, required=True, help='A NEW isolated output directory')
    ap.add_argument('--roles-root', type=Path, help='Optional new-build roles/ containing baseline and candidate')
    ap.add_argument('--build-receipt', type=Path, help='Required with --roles-root; new build-receipt.json')
    ap.add_argument('--strategy-timeout', type=int, default=300)
    ap.add_argument('--synthesis-timeout', type=int, default=120)
    args = ap.parse_args()
    if os.name != 'posix' or platform.machine().lower() not in ('x86_64', 'amd64'):
        ap.error('Linux x86_64/WSL is required')
    if args.strategy_timeout < 1 or args.synthesis_timeout < 1:
        ap.error('Timeouts must be positive')
    if bool(args.roles_root) != bool(args.build_receipt):
        ap.error('--roles-root and --build-receipt must be provided together')
    package, kit, out = (p.expanduser().resolve() for p in (args.package, args.proof_kit, args.output))
    role_root = args.roles_root.expanduser().resolve() if args.roles_root else package
    for path in (package, kit, out, role_root):
        if not str(path).isascii() or any(c.isspace() for c in str(path)) or '"' in str(path):
            ap.error('Use ASCII paths without whitespace or double quotes')
    for source in (package, kit, role_root):
        if source == out or source in out.parents or out in source.parents:
            ap.error('Output must be isolated from input directories')
    if out.exists():
        raise FileExistsError('Refuse to reuse any proof output: ' + str(out))
    index_path = kit / 'portable-index.json'
    if sha(index_path) != KIT_INDEX_SHA:
        raise RuntimeError('Unsupported external proof-kit index')
    index = json.loads(index_path.read_text())
    check_index(kit, index['files'])
    # Verify the runtime before executing it. Every command uses the supplied
    # kit location, not a historical proof-tool manifest or report directory.
    python = inside(kit, 'runtime/bin/python3')
    if (Path(sys.prefix).resolve() != kit / 'runtime/python' or not sys.flags.isolated or not sys.flags.no_site
            or Path(os.environ.get('FPGA_PORTABLE_DISPATCH', '')).resolve() != kit / 'runtime/python_dispatch.py'):
        clean = dict(PATH='/usr/bin:/bin', LC_ALL='C', LANG='C', TERM='dumb')
        os.execve(str(python), [str(python), '-I', '-S', '-B', str(Path(__file__).resolve()), *sys.argv[1:]], clean)
    sys.executable = str(python)
    delivery_path = package / 'delivery-manifest.json'
    delivery = json.loads(delivery_path.read_text())
    check_index(package, delivery['files'])
    manifest_path = package / 'manifest.json'
    package_manifest = json.loads(manifest_path.read_text())
    if (str(package_manifest.get('yosys_release')) != '0.69' or package_manifest.get('yosys_commit') != COMMIT
            or package_manifest.get('source_sha256') != SOURCE_SHA or package_manifest.get('patch_sha256') != PATCH_SHA):
        raise RuntimeError('Expected the frozen v24/Yosys 0.69 source identity')
    registry_path = package / 'cases_current.json'
    if sha(registry_path) != CASES_SHA or sha(kit / 'cases_current.json') != CASES_SHA:
        raise RuntimeError('Expected the same nine immutable input cases')
    registry = json.loads(registry_path.read_text())
    cases = registry['cases'] if isinstance(registry, dict) else registry
    if len(cases) != 9 or len({identity(c)[0] for c in cases}) != 9:
        raise RuntimeError('Exactly nine unique cases required')
    for case in cases:
        name, top, path, digest = identity(case)
        if not NAME.fullmatch(name) or not NAME.fullmatch(top) or sha(inside(package, path)) != digest:
            raise RuntimeError('Invalid or changed case: ' + name)
    receipt_path = args.build_receipt.expanduser().resolve() if args.build_receipt else None
    receipt = json.loads(receipt_path.read_text()) if receipt_path else None
    if receipt:
        if (receipt.get('status') != 'BUILD_COMPLETE_NOT_EXECUTED' or receipt.get('candidate_source_sha256') != SOURCE_SHA
                or receipt.get('patch_sha256') != PATCH_SHA or not receipt.get('abc_identical')
                or receipt.get('source_archive_sha256') != package_manifest.get('source_archive_sha256')):
            raise RuntimeError('New-build receipt is incomplete or belongs to another source/patch')
        role_files = {role: receipt['roles'][role]['files'] for role in ROLES}
    else:
        role_files = {role: package_manifest['roles'][role]['files'] for role in ROLES}
    for role in ROLES:
        if inventory(role_root / role) != role_files[role]:
            raise RuntimeError('Role payload differs from its pinned receipt: ' + role)
        for executable in ('yosys', 'yosys-abc'):
            if not os.access(role_root / role / executable, os.X_OK):
                raise RuntimeError('Role executable mode is missing: ' + role + '/' + executable)
    if role_files['baseline']['yosys-abc'] != role_files['candidate']['yosys-abc']:
        raise RuntimeError('Original and candidate must share an identical ABC')
    if role_files['candidate'].get('share/intel/competition_abc_v11.abc') != ABC_SCRIPT_SHA:
        raise RuntimeError('Fixed candidate ABC script differs')
    core_path = inside(kit, 'scripts/verify_current_cases.py')
    if sha(core_path) != CORE_SHA:
        raise RuntimeError('Proof core differs from reviewed version')
    core = load_module(core_path)
    out.mkdir(parents=True)
    for name in ('home', 'tmp', 'inputs'):
        (out / name).mkdir()
    # All proof work and temporary files live under the new output. The kit's
    # payload and historical results are read-only inputs to this invocation.
    os.environ.clear()
    os.environ.update(PATH=str(kit / 'runtime/bin'), LC_ALL='C', LANG='C', TERM='dumb',
        HOME=str(out / 'home'), TMPDIR=str(out / 'tmp'), TMP=str(out / 'tmp'), TEMP=str(out / 'tmp'),
        TCL_LIBRARY=str(kit / 'runtime/tcl8.6'), FPGA_PORTABLE_DISPATCH=str(kit / 'runtime/python_dispatch.py'))
    tools = index['tools']
    parser, abc, eqy = (inside(kit, tools[key]) for key in ('baseline', 'abc', 'eqy'))
    proof_bin = kit / 'runtime/bin'
    # A parser alias is explicitly separated from the synthesis candidate.
    proof_manifest = dict(schema=1, yosys_release='0.69', yosys_commit=COMMIT,
        baseline=str(parser), baseline_sha256=sha(parser),
        candidate=str(parser), candidate_sha256=sha(parser),
        candidate_role='original_parser_alias_only; actual synthesis roles recorded separately',
        abc=str(abc), abc_sha256=sha(abc), proof_bin=str(proof_bin),
        proof_wrapper_hashes={name: sha(proof_bin / name) for name in ('yosys', 'sby')},
        eqy=dict(executable=str(eqy), files={str(kit / name): digest for name, digest in index['files'].items()
            if name.startswith(('runtime/eqy/', 'runtime/sby/', 'runtime/vendor/'))
            or name in ('runtime/python_dispatch.py', 'runtime/bin/python3')}),
        portable_index_sha256=KIT_INDEX_SHA,
        scope='New onsite post-ABC exports; no historical performance-sample claim')
    generated_manifest = out / 'proof-tool-manifest.json'
    write_json(generated_manifest, proof_manifest)
    report = dict(schema=1, status='RUNNING', formal_status='RUNNING', cases=[],
        started_utc=datetime.now(timezone.utc).isoformat(), expected_positive_proofs=18,
        performance_tested=False, performance_samples_proved=False, overall_submission_acceptance=False,
        scope='New onsite synthesis/export and formal evidence only; historical PASS results are not used',
        export_flow='Single unmeasured role process: synth_intel begin:map_cells; post-ABC RTLIL; map_cells:; final JSON/Verilog',
        package_manifest_sha256=sha(manifest_path), delivery_manifest_sha256=sha(delivery_path),
        case_manifest_sha256=sha(registry_path), proof_kit_index_sha256=KIT_INDEX_SHA,
        source_sha256=SOURCE_SHA, harness_sha256=sha(__file__), proof_core_sha256=CORE_SHA,
        supplied_paths=dict(package=str(package), proof_kit=str(kit), roles_root=str(role_root)),
        new_build_receipt_sha256=sha(receipt_path) if receipt_path else None,
        roles={role: dict(executable_sha256=role_files[role]['yosys'], abc_sha256=role_files[role]['yosys-abc'],
                        inventory_sha256=hashlib.sha256(json.dumps(role_files[role], sort_keys=True).encode()).hexdigest()) for role in ROLES},
        proof_tool_manifest_sha256=sha(generated_manifest))
    def save():
        write_json(out / 'report.json', report)
    save()
    try:
        proof_env, checked, fingerprints, versions = core.load_environment(kit, generated_manifest)
        report['proof_versions'] = versions
        for command in index['required_commands']:
            chosen = shutil.which(command, path=proof_env['PATH'])
            if not chosen or Path(chosen).parent != proof_bin:
                raise RuntimeError('Proof tool missing/shadowed: ' + command)
        sby_version = subprocess.check_output([str(proof_bin / 'sby'), '--version'], env=proof_env, cwd=out,
                                             text=True, timeout=30).strip()
        if sby_version != index['sby_version']:
            raise RuntimeError('SBY version differs from pinned kit')
        report['proof_versions']['sby'] = sby_version
        model = out / 'formal_dffeas.v'
        canonical = inside(kit, 'clean-v11/formal_cycloneiv.v')
        core.extract_ff_model(canonical, model)
        report.update(formal_model_sha256=sha(model), canonical_model_sha256=sha(canonical))
        synth_env = dict(HOME=str(out / 'home'), PATH='/usr/bin:/bin', LC_ALL='C', LANG='C',
                         TMPDIR=str(out / 'tmp'), TMP=str(out / 'tmp'), TEMP=str(out / 'tmp'))
        for case in cases:
            name, top, path, digest = identity(case)
            src = out / 'inputs' / Path(path)
            src.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(inside(package, path), src)
            if sha(src) != digest:
                raise RuntimeError('Copied onsite source differs: ' + name)
            row = dict(name=name, top=top, source_path=src.relative_to(out).as_posix(), source_sha256=digest, roles={})
            report['cases'].append(row)
            for role in ROLES:
                directory = out / name / role
                directory.mkdir(parents=True)
                item = dict(status='RUNNING', executable_sha256=role_files[role]['yosys'])
                row['roles'][role] = item
                save()
                try:
                    flow, ilang = directory / 'synthesis.ys', directory / 'postabc.il'
                    option = ' -sv' if src.suffix.lower() == '.sv' else ''
                    flow.write_text(f'read_verilog{option} "{src}"\nsynth_intel -family cycloneiv -top {top} -run begin:map_cells\n'
                        f'select {top}\nwrite_rtlil -selected "{ilang}"\nselect *\n'
                        f'synth_intel -family cycloneiv -top {top} -run map_cells:\n'
                        f'write_json "{directory}/final.json"\nwrite_verilog -norename -noattr "{directory}/final.v"\n')
                    env = dict(synth_env, YOSYS_DATDIR=str(role_root / role / 'share'))
                    execution = core.run([role_root / role / 'yosys', '-Q', '-T', '-s', flow],
                                         directory / 'synthesis.log', env, args.synthesis_timeout, out)
                    item['synthesis'] = execution
                    if execution['timed_out'] or execution['exit_code']:
                        raise RuntimeError('Fresh synthesis failed')
                    if 'Executing ABC9 pass' not in (directory / 'synthesis.log').read_text(errors='replace'):
                        raise RuntimeError('Full ABC9 stage was not observed')
                    item.update(ilang_sha256=sha(ilang), final_json_sha256=sha(directory / 'final.json'),
                        final_verilog_sha256=sha(directory / 'final.v'), flow_sha256=sha(flow),
                        synthesis_log_sha256=sha(directory / 'synthesis.log'), final_counts=core.final_counts(directory / 'final.json', top))
                    audit = directory / 'audit.ys'
                    audit.write_text(f'read_verilog -lib "{model}"\nread_rtlil "{ilang}"\nwrite_json "{directory}/audit.json"\n')
                    audited = core.run([checked['baseline'], '-Q', '-T', '-s', audit],
                                       directory / 'audit.log', proof_env, args.synthesis_timeout, out)
                    if audited['timed_out'] or audited['exit_code']:
                        raise RuntimeError('New post-ABC object audit failed')
                    item['postabc_audit'] = core.audit_postabc(directory / 'audit.json', top)
                    item['audit_json_sha256'] = sha(directory / 'audit.json')
                    item['proof'] = core.prove(src, top, ilang, directory / 'proof', proof_env, checked, model, out, args.strategy_timeout)
                    item['status'] = item['proof']['status']
                except Exception as error:
                    item.update(status='ERROR', error=repr(error))
                print(name, role, 'NEW_EXPORT_EQY_' + item['status'], flush=True)
                save()
        negative = out / 'negative'
        negative.mkdir()
        test2 = [case for case in cases if identity(case)[1] == 'test2']
        if len(test2) != 1:
            raise RuntimeError('Immutable test2 required for negative control')
        src = out / 'inputs' / identity(test2[0])[2]
        wrong, ilang, flow = negative / 'wrong.v', negative / 'wrong.il', negative / 'synthesis.ys'
        wrong.write_text('module test2(input clk,a,b,c,d,input [4:0] dataa,datab,datac,datad,output [4:0] out); assign out=0; endmodule\n')
        flow.write_text(f'read_verilog "{wrong}"\nsynth_intel -family cycloneiv -top test2 -run begin:map_cells\nselect test2\nwrite_rtlil -selected "{ilang}"\n')
        execution = core.run([checked['baseline'], '-Q', '-T', '-s', flow], negative / 'synthesis.log', proof_env, args.synthesis_timeout, out)
        if execution['timed_out'] or execution['exit_code']:
            raise RuntimeError('Negative-control construction failed')
        bad = core.prove(src, 'test2', ilang, negative / 'proof', proof_env, checked, model, out, args.strategy_timeout)
        negative_ok = bad['status'] == 'FAIL' and bad['definite_counterexample']
        report['negative_control'] = dict(status='EXPECTED_COUNTEREXAMPLE' if negative_ok else 'INVALID_NEGATIVE_CONTROL',
            wrong_source_sha256=sha(wrong), wrong_ilang_sha256=sha(ilang), proof=bad)
        check_index(kit, index['files'])
        check_index(package, delivery['files'])
        if sha(index_path) != KIT_INDEX_SHA or sha(delivery_path) != report['delivery_manifest_sha256']:
            raise RuntimeError('Input index changed during this invocation')
        for role in ROLES:
            if inventory(role_root / role) != role_files[role]:
                raise RuntimeError('Synthesis role changed during proof')
        if receipt_path and sha(receipt_path) != report['new_build_receipt_sha256']:
            raise RuntimeError('New build receipt changed')
        for row in report['cases']:
            if sha(out / row['source_path']) != row['source_sha256']:
                raise RuntimeError('Copied RTL changed during proof: ' + row['name'])
            for role in ROLES:
                item = row['roles'][role]
                for filename, key in (('postabc.il', 'ilang_sha256'), ('final.json', 'final_json_sha256'),
                                      ('final.v', 'final_verilog_sha256')):
                    if key in item and sha(out / row['name'] / role / filename) != item[key]:
                        raise RuntimeError('Export changed after proof: ' + row['name'] + '/' + role + '/' + filename)
        states = [row['roles'][role]['status'] for row in report['cases'] for role in ROLES]
        report['positive_proof_counts'] = dict(Counter(states))
        area = []
        for row in report['cases']:
            b, c = (row['roles'][role].get('final_counts') for role in ROLES)
            if b and c and b['scored_logic_cells'] > 0:
                row['logic_gain_percent'] = 100.0 * (b['scored_logic_cells'] - c['scored_logic_cells']) / b['scored_logic_cells']
                row['logic_cells_nonincrease'] = c['scored_logic_cells'] <= b['scored_logic_cells']
                area.append(row['logic_gain_percent'])
        report['area_observations'] = dict(complete_case_count=len(area),
            average_logic_gain_percent=statistics.mean(area) if area else None,
            all_case_logic_nonincrease=len(area) == 9 and all(row.get('logic_cells_nonincrease', False) for row in report['cases']),
            metric='LUT plus standalone NOT; new unmeasured synthesis only')
        passed = len(states) == 18 and all(value == 'PASS' for value in states) and negative_ok
        report.update(status='PASS' if passed else 'FAIL', formal_status='PASS' if passed else 'FAIL',
            input_payloads_unchanged=True, completed_utc=datetime.now(timezone.utc).isoformat())
        save()
        write_json(out / 'evidence-index.json', dict(schema=1, files=inventory(out)))
        print('ONSITE_FRESH_FORMAL_' + report['status'], out, flush=True)
        return 0 if passed else 2
    except BaseException as error:
        report.update(status='ERROR', formal_status='ERROR', error=repr(error), completed_utc=datetime.now(timezone.utc).isoformat())
        save()
        raise


if __name__ == '__main__':
    raise SystemExit(main())
