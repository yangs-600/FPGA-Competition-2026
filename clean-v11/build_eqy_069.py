"""Build official EQY v0.69 plugins against the pinned Yosys 0.69 headers."""
import json,os,subprocess,tarfile,shutil
from pathlib import Path
from build_069 import ROOT,WORK,sha

def main():
    w=ROOT/'toolchains/eqy-0.69';src=w/'src';prefix=w/'install'
    assert sha(w/'source.tar')=='dd1a4c5edcf83353c66e9765661cc332f4c7f6f122585c97da68290eab230291'
    if not src.exists():
        src.mkdir()
        with tarfile.open(w/'source.tar') as t:t.extractall(src,filter='data')
    env=dict(os.environ,PATH='/usr/bin:/bin:'+os.environ['PATH'])
    with (w/'build.log').open('w') as log:
        subprocess.run(['make','-j2','install','YOSYS_CONFIG='+str(WORK/'build/yosys-config'),
                        'PREFIX='+str(prefix)],cwd=src,env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
    # Use system Python so the OSS Python launcher cannot rewrite PATH.
    if subprocess.run(['/usr/bin/python3','-E','-c','import click'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode:
        import click
        shutil.copytree(Path(click.__file__).parent,prefix/'share/yosys/python3/click',dirs_exist_ok=True)
    # EQY's SBY strategy invokes sby by name; its launcher may also rewrite PATH.
    wrapper=WORK/'proof-bin/sby'
    wrapper.write_text('#!/bin/sh\nexec /home/ubuntu/oss-cad-suite/bin/sby --yosys '+str(WORK/'build/yosys-original')+' --abc '+str(WORK/'build/yosys-abc')+' "$@"\n')
    wrapper.chmod(0o755)
    paths=[prefix/'bin/eqy',prefix/'share/yosys/python3/eqy_job.py',wrapper,*sorted((prefix/'share/yosys/plugins').glob('*.so'))]
    m=dict(commit='4a72eb94fc253062464afee4d0018359017bb846',version=subprocess.check_output(['/usr/bin/python3','-E',str(prefix/'bin/eqy'),'--version'],text=True).strip(),
           source_sha256=sha(w/'source.tar'),files={str(p):sha(p) for p in paths},executable=str(prefix/'bin/eqy'))
    (w/'manifest.json').write_text(json.dumps(m,indent=2));print(json.dumps(m,indent=2))

if __name__=='__main__':main()
