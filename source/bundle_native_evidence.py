"""Copy one completed, unmodified Windows measurement into a new proof bundle."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def inside(root, name):
    p = Path(name)
    if p.is_absolute() or p.drive or '..' in p.parts:
        raise RuntimeError('Expected package-relative path: '+str(name))
    value = (root/p).resolve()
    value.relative_to(root)
    return value

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--package', required=True, type=Path)
    ap.add_argument('--report', required=True, type=Path)
    ap.add_argument('--output', required=True, type=Path)
    args = ap.parse_args()
    root, report_path, out = (p.resolve() for p in (args.package, args.report, args.output))
    report_path.relative_to(root)
    if out.exists():
        raise RuntimeError('Refusing to overwrite evidence')
    report = json.loads(report_path.read_text(encoding='utf-8'))
    if report.get('status') not in {'MEASUREMENTS_PASS_FORMAL_PENDING', 'MEASUREMENTS_REVIEW_FORMAL_PENDING'}:
        raise RuntimeError('Windows measurements not complete')
    if report['case_count'] != 9 or len(report['cases']) != 9 or report['formal_status'] != 'PENDING':
        raise RuntimeError('Incomplete nine-case evidence')
    manifest = json.loads((root/'manifest.json').read_text(encoding='utf-8'))
    required = {'manifest.json', 'cases_current.json', 'run_current_cases.py', 'windows_metrics.py', 'README_PROTOCOL.md'}
    bindings = {'manifest_sha256': 'manifest.json', 'case_manifest_sha256': 'cases_current.json',
                'harness_sha256': 'run_current_cases.py', 'meter_sha256': 'windows_metrics.py'}
    for key, name in bindings.items():
        if sha(root/name) != report[key]:
            raise RuntimeError('Input changed after measurement: '+key)
    for key, name in (
        ('source_sha256', 'source/pmux_competition_v11.cc'),
        ('source_patch_sha256', 'source/synth-intel-competition.patch'),
        ('script_sha256', 'source/competition_abc_dch.abc')):
        if sha(inside(root, name)) != manifest[key]:
            raise RuntimeError('Current source identity changed: '+name)
        required.add(name)
    for role in ('baseline', 'candidate'):
        for name, digest in manifest['roles'][role]['files'].items():
            actual = manifest['roles'][role].get('file_origins', {}).get(name, role+'/'+name)
            if sha(inside(root, actual)) != digest:
                raise RuntimeError('Binary/resource changed: '+actual)
            required.add(actual)
    for name, digest in manifest.get('shared_files', {}).items():
        if sha(inside(root, name)) != digest:
            raise RuntimeError('Shared runtime changed: '+name)
        required.add(name)
    for row in report['cases']:
        required.add(row['source_path'])
        if sha(inside(root, row['source_path'])) != row['source_sha256']:
            raise RuntimeError('RTL changed')
        for role in ('baseline', 'candidate'):
            data = row['roles'][role]
            if sha(inside(root, data['path']+'/postabc.il')) != data['ilang_sha256']:
                raise RuntimeError('Formal object changed')
    result_dir = inside(root, report['directory'])
    for p in result_dir.rglob('*'):
        if p.is_file():
            required.add(p.relative_to(root).as_posix())
    out.mkdir(parents=True)
    for name in sorted(required):
        p = inside(root, name)
        target = out/name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, target)
        if sha(p) != sha(target):
            raise RuntimeError('Copy failed')
    if manifest['package_layout'] != 'colocated_yosys_shared_runtime':
        raise RuntimeError('This evidence entry requires the shared runtime layout')
    # The frozen Linux helper uses these logical names. They are explicit,
    # byte-identical proof copies, never separately executed Windows programs.
    aliases = {}
    for role in ('baseline', 'candidate'):
        logical = role+'/yosys.exe'
        physical = manifest['roles'][role]['file_origins']['yosys.exe']
        aliases[logical] = {'physical': physical, 'sha256': manifest['roles'][role]['files']['yosys.exe']}
    script_names = [name for name in manifest['roles']['candidate']['files'] if name.endswith(('.abc','.script'))]
    if len(script_names) != 1:
        raise RuntimeError('Require one candidate recipe')
    name = script_names[0]
    aliases['candidate/'+name] = {'physical': manifest['roles']['candidate']['file_origins'][name],
                                 'sha256': manifest['script_sha256']}
    for logical, item in aliases.items():
        src, target = inside(out,item['physical']), inside(out,logical)
        if target.exists() or sha(src) != item['sha256']:
            raise RuntimeError('Invalid or colliding proof alias')
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(src,target)
        if sha(target) != item['sha256']:
            raise RuntimeError('Alias bytes differ')
    (out/'proof-aliases.json').write_text(json.dumps({'schema':'windows-logical-proof-aliases-v1',
        'purpose':'Byte-identical logical names required by the frozen Linux proof helper; no Windows execution',
        'aliases':aliases},indent=2)+'\n',encoding='utf-8')
    shutil.copy2(report_path, out/'report.json')
    inv = {'scope': 'All original Windows measurement samples and actual post-ABC objects; no filtering',
           'source_package': str(root), 'source_report': str(report_path),
           'windows_report_sha256': sha(report_path), 'payload_files': {}}
    for p in sorted(out.rglob('*')):
        if p.is_file():
            inv['payload_files'][p.relative_to(out).as_posix()] = {'sha256': sha(p), 'bytes': p.stat().st_size}
    (out/'evidence-inventory.json').write_text(json.dumps(inv, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'bundle': str(out), 'windows_report_sha256': sha(out/'report.json'),
                      'inventory_sha256': sha(out/'evidence-inventory.json'), 'files': len(inv['payload_files'])}, indent=2))

if __name__ == '__main__':
    main()
