"""Create a fresh project using only the verified v11 review package."""
import json,zipfile,hashlib,shutil,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
archive=ROOT/'competition-v11-review-20260927.zip'
assert hashlib.sha256(archive.read_bytes()).hexdigest()=='6a9a1fd060a4a48c7e65bd202b5267b3ac304963faabdbcddfa3c1eb92944743'
fresh=ROOT/'clean-v11'
assert not fresh.exists(),'Never reuse an earlier build directory'
fresh.mkdir()
names=['build_069.py','build_eqy_069.py','run_competition_v11.py','run_current.py',
       'test_shared_tree.py','measure_competition_v11_pss.py','formal_cycloneiv.v',
       'pmux_competition_v11.cc','competition_abc_dch.abc','competition_inputs.json',
       'activate_competition.sh','COMPETITION_V11.md','toolchains/yosys-0.69/source.tar.gz',
       'toolchains/eqy-0.69/source.tar','toolchains/yosys-0.69/competition-v11/synth-intel-competition.patch']
with zipfile.ZipFile(archive) as z:
    hashes=json.loads(z.read('SHA256SUMS.json'))
    names += [n for n in hashes if n.startswith('competition_case/')]
    for n in names:
        data=z.read(n);assert hashlib.sha256(data).hexdigest()==hashes[n]
        dest=fresh/n;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(data)
shutil.copy2(ROOT/'clean_build_v11.py',fresh/'clean_build_v11.py')
shutil.copy2(ROOT/'competition-v11-latest.json',fresh/'previous-v11-report.json')
(fresh/'bootstrap.json').write_text(json.dumps(dict(archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
    copied_inputs=names,old_objects_copied=0,cmake=str(ROOT/'toolchains/cmake-3.31.6/bin/cmake')),indent=2))
subprocess.run([sys.executable,str(fresh/'clean_build_v11.py')],cwd=fresh,check=True)
