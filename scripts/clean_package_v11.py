"""Archive fresh-build inputs, runnable tools, proofs and measurements."""
from pathlib import Path
import json,zipfile,hashlib,os,stat
ROOT=Path(__file__).resolve().parent;fresh=ROOT/'clean-v11'
assert json.loads((fresh/'clean-reproduction.json').read_text())['status']=='PASS'
def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()
files=[]
for p in fresh.rglob('*'):
    if not p.is_file() or '__pycache__' in p.parts:continue
    n=p.relative_to(fresh).as_posix()
    if n.startswith(('toolchains/yosys-0.69/src/','toolchains/eqy-0.69/src/')):continue
    if n.startswith('toolchains/yosys-0.69/build/'):
        sub=n.removeprefix('toolchains/yosys-0.69/build/')
        if not (sub.startswith('share/') or sub in ('yosys','yosys-original','yosys-abc','yosys-config') or sub.startswith('yosys-competition-')):continue
    files.append(p)
files += [ROOT/'start_clean_v11.py',ROOT/'clean_build_v11.py',ROOT/'clean-v11-bootstrap.log',ROOT/'clean-v11-resume.log',ROOT/'CLEAN_REPRODUCTION.md']
archive=ROOT/'clean-v11-reproduction.zip';assert not archive.exists()
hashes={p.relative_to(ROOT).as_posix():(hashlib.sha256(os.readlink(p).encode()).hexdigest() if p.is_symlink() else digest(p)) for p in files}
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=3) as z:
    for p in files:
        if p.is_symlink():
            info=zipfile.ZipInfo(p.relative_to(ROOT).as_posix());info.create_system=3;info.external_attr=(stat.S_IFLNK|0o777)<<16
            z.writestr(info,os.readlink(p))
        else:z.write(p,p.relative_to(ROOT).as_posix())
    z.writestr('SHA256SUMS.json',json.dumps(hashes,indent=2))
with zipfile.ZipFile(archive) as z:assert z.testzip() is None
receipt=dict(archive=archive.name,sha256=digest(archive),bytes=archive.stat().st_size,files=len(files))
(ROOT/'clean-package-receipt.json').write_text(json.dumps(receipt,indent=2));print(json.dumps(receipt),flush=True)
