"""Delete exactly archived and rechecked paths after Windows backup verification."""
import json,hashlib,shutil,os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
assert ROOT==Path('/home/ubuntu/FPGA')
assert json.loads((ROOT/'clean-v11/clean-reproduction.json').read_text())['status']=='PASS'
plan=json.loads((ROOT/'cleanup-plan.json').read_text())
remote=json.loads((ROOT/'cleanup-backup-receipt.json').read_text())
verified=json.loads((ROOT/'cleanup-windows-verified.json').read_text())
assert verified['sha256']==remote['sha256'] and verified['all_entries_verified']
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()
assert sha(ROOT/remote['archive'])==remote['sha256']
for e in plan['entries']:
    p=ROOT/e['path'];assert p.parent.resolve().is_relative_to(ROOT)
    if 'link' in e:assert p.is_symlink() and os.readlink(p)==e['link']
    else:assert not p.is_symlink() and p.stat().st_size==e['bytes'] and sha(p)==e['sha256'],str(p)
targets=[Path(p) for p in plan['targets']]
for p in targets:
    assert p.resolve().is_relative_to(ROOT) and p.resolve()!=ROOT and not p.is_symlink()
    assert not p.resolve().is_relative_to(ROOT/'clean-v11')
    assert not any(x in p.parts for x in ('oss-cad-suite','cmake-3.31.6','competition_case','.vscode'))
# Confirm no other process currently executes inside a deletion target.
for process in Path('/proc').glob('[0-9]*'):
    if int(process.name)==os.getpid():continue
    for kind in ('cwd','exe'):
        try:q=(process/kind).resolve(strict=True)
        except (FileNotFoundError,PermissionError,ProcessLookupError):continue
        assert not any(q==p or q.is_relative_to(p) for p in targets),f'Active process {process.name}: {q}'
deleted=[]
for p in targets:
    if p.is_dir():shutil.rmtree(p)
    else:p.unlink()
    deleted.append(str(p))
# Publish simple entrypoints to the surviving, independently built project.
(ROOT/'run_current.py').write_text('import runpy,sys\nfrom pathlib import Path\np=Path(__file__).resolve().parent/"clean-v11"\nsys.path.insert(0,str(p))\nrunpy.run_path(str(p/"run_current.py"),run_name="__main__")\n')
(ROOT/'activate_competition.sh').write_text('source /home/ubuntu/FPGA/clean-v11/activate_competition.sh\n')
(ROOT/remote['archive']).unlink() # Identical, fully verified copy is now on Windows.
(ROOT/'competition-transfer.zip').unlink(missing_ok=True)
receipt=dict(status='PASS',deleted=deleted,archived_bytes=plan['bytes'],disk_after=shutil.disk_usage(ROOT)._asdict(),windows_backup=verified)
(ROOT/'cleanup-result.json').write_text(json.dumps(receipt,indent=2));print(json.dumps({k:v for k,v in receipt.items() if k!='deleted'}),flush=True)
