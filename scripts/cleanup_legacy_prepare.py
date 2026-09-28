"""Inventory and archive superseded project files only after clean reproduction PASS."""
import os,json,hashlib,stat,zipfile,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parent
assert ROOT==Path('/home/ubuntu/FPGA')
assert json.loads((ROOT/'clean-v11/clean-reproduction.json').read_text())['status']=='PASS'
keep={'clean-v11','competition_case','engineering_fixtures','engineering_fixtures_069','rtl','.vscode','toolchains',
      'competition-v11-review-20260927.zip','competition-v11-package-receipt.json','competition-transfer.zip'}
keep_prefix=('cleanup','clean-','clean_','start_clean','CLEAN_')
targets=[p for p in ROOT.iterdir() if p.name not in keep and not p.name.startswith(keep_prefix)]
targets += [ROOT/'toolchains'/n for n in ('yosys-0.63','yosys-0.68','yosys-0.69','eqy-0.69') if (ROOT/'toolchains'/n).exists()]
targets=sorted(targets)
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()
entries=[];total=0
for top in targets:
    assert top.parent.resolve().is_relative_to(ROOT) and not top.is_symlink()
    assert top.name.lower() not in ('oss-cad-suite','cmake-3.31.6')
    paths=[top] if top.is_file() else sorted(top.rglob('*'))
    for p in paths:
        if p.is_symlink():
            entries.append(dict(path=p.relative_to(ROOT).as_posix(),link=os.readlink(p)))
        elif p.is_file():
            st=p.stat();total+=st.st_size
            entries.append(dict(path=p.relative_to(ROOT).as_posix(),bytes=st.st_size,sha256=sha(p)))
plan=dict(root=str(ROOT),targets=[str(p) for p in targets],entries=entries,bytes=total,
          disk_before=shutil.disk_usage(ROOT)._asdict(),preserved=list(sorted(keep)),
          note='Only project-owned superseded files; existing source fixtures/configuration and external dependencies retained.')
(ROOT/'cleanup-plan.json').write_text(json.dumps(plan,indent=2))
archive=ROOT/'cleanup-legacy-backup.zip';assert not archive.exists()
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=1,allowZip64=True) as z:
    for e in entries:
        if 'link' in e:
            info=zipfile.ZipInfo(e['path']);info.create_system=3;info.external_attr=(stat.S_IFLNK|0o777)<<16
            z.writestr(info,e['link'])
        else:z.write(ROOT/e['path'],e['path'])
    z.writestr('CLEANUP_MANIFEST.json',json.dumps(plan,indent=2))
with zipfile.ZipFile(archive) as z:assert z.testzip() is None
receipt=dict(archive=archive.name,bytes=archive.stat().st_size,sha256=sha(archive),files=len(entries),original_bytes=total)
(ROOT/'cleanup-backup-receipt.json').write_text(json.dumps(receipt,indent=2));print(json.dumps(receipt),flush=True)
