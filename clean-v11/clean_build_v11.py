"""Build all baseline objects from source, then apply the final patch in this fresh tree."""
import json,os,subprocess,sys,tarfile,shutil,time
from pathlib import Path
from build_069 import ROOT,WORK,sha,COMMIT,SOURCE_SHA

def main():
    bootstrap=json.loads((ROOT/'bootstrap.json').read_text())
    src=WORK/'src';build=WORK/'build';result=WORK/'competition-v11'
    resume='--resume-after-baseline' in sys.argv
    if not resume:assert not src.exists() and not build.exists(),'Fresh directories required'
    else:
        assert (build/'yosys-original').exists() and sha(build/'yosys-original')==sha(build/'yosys')
        assert not (src/'passes/opt/pmux_competition_opt.cc').exists()
        assert bootstrap['old_objects_copied']==0
    assert sha(WORK/'source.tar.gz')==SOURCE_SHA
    def stage(name):
        (ROOT/'clean-status.json').write_text(json.dumps(dict(stage=name,time=time.time())))
        print(name,flush=True)
    def run(command,log,env=None):
        with (ROOT/log).open('a') as f:
            f.write(repr(command)+'\n');f.flush()
            subprocess.run(command,cwd=src if src.exists() else ROOT,stdout=f,stderr=subprocess.STDOUT,env=env,check=True)
    if not resume:
        stage('extracting_pristine_source');src.mkdir()
        with tarfile.open(WORK/'source.tar.gz') as t:t.extractall(src,filter='data')
        assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=src,text=True).strip()==COMMIT
        assert not list(src.rglob('CMakeCache.txt')) and not list(src.rglob('*.o'))
    env=dict(os.environ,PATH='/usr/bin:/bin:'+os.environ['PATH'],CCACHE_DISABLE='1')
    cfg=[bootstrap['cmake'],'-S',str(src),'-B',str(build),'-G','Unix Makefiles',
        '-DCMAKE_BUILD_TYPE=Release','-DCMAKE_C_COMPILER=/usr/bin/gcc','-DCMAKE_CXX_COMPILER=/usr/bin/g++',
        '-DYOSYS_WITHOUT_SLANG=ON','-DYOSYS_USE_BUNDLED_LIBS=ON','-DBUILD_SHARED_LIBS=OFF',
        '-DYOSYS_WITH_PYTHON=OFF','-DPython3_EXECUTABLE='+sys.executable,
        '-DCMAKE_C_COMPILER_LAUNCHER=','-DCMAKE_CXX_COMPILER_LAUNCHER=']
    if not resume:
        stage('building_fresh_baseline');run(cfg,'clean-baseline-build.log',env)
        run([cfg[0],'--build',str(build),'--parallel','2'],'clean-baseline-build.log',env)
    baseline=build/'yosys-original';shutil.copy2(build/'yosys',baseline);abc=build/'yosys-abc'
    frozen=(sha(baseline),sha(abc))
    reject=subprocess.run([str(baseline),'-Q','-T','-p','pmux_competition_opt'],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    assert reject.returncode and 'No such command' in reject.stdout
    patch=result/'synth-intel-competition.patch'
    normalized=[]
    for name in ['passes/opt/CMakeLists.txt','techlibs/intel/synth_intel.cc','techlibs/intel/CMakeLists.txt']:
        data=(src/name).read_bytes();lf=data.replace(b'\r\n',b'\n')
        upstream=subprocess.check_output(['git','show','HEAD:'+name],cwd=src)
        assert lf==upstream.replace(b'\r\n',b'\n')
        (src/name).write_bytes(lf);normalized.append(dict(path=name,crlf_lines=data.count(b'\r\n')))
    (ROOT/'clean-line-ending-normalization.json').write_text(json.dumps(normalized,indent=2))
    stage('applying_final_patch');run(['git','apply','--check',str(patch)],'clean-patch.log',env)
    run(['git','apply',str(patch)],'clean-patch.log',env)
    stage('building_fresh_candidate');run(cfg,'clean-candidate-build.log',env)
    run([cfg[0],'--build',str(build),'--parallel','2'],'clean-candidate-build.log',env)
    candidate=build/('yosys-competition-'+sha(patch)[:16]);shutil.copy2(build/'yosys',candidate)
    assert frozen==(sha(baseline),sha(abc))
    m=dict(yosys_release='0.69',yosys_commit=COMMIT,source_sha256=SOURCE_SHA,build_config=cfg,
           baseline=str(baseline),candidate=str(candidate),abc=str(abc),patch=str(patch),
           plugin_source=str(ROOT/'pmux_competition_v11.cc'),abc_script=str(build/'share/intel/competition_abc_v11.abc'))
    for name in ('baseline','candidate','abc','patch','plugin_source','abc_script'):m[name+'_sha256']=sha(m[name])
    for role in ('baseline','candidate'):
        m[role+'_version']=subprocess.check_output([m[role],'-V'],text=True).strip()
        assert m[role+'_version'].startswith('Yosys 0.69 (')
    (result/'manifest.json').write_text(json.dumps(m,indent=2))
    proof=WORK/'proof-bin';proof.mkdir();(proof/'yosys').symlink_to(baseline)
    stage('building_fresh_eqy');run([sys.executable,str(ROOT/'build_eqy_069.py')],'clean-eqy-build.log')
    for script,log in [('run_current.py','clean-validation.log'),('test_shared_tree.py','clean-fixtures.log'),('measure_competition_v11_pss.py','clean-pss.log')]:
        stage(script);run([sys.executable,str(ROOT/script)],log)
    previous=json.loads((ROOT/'previous-v11-report.json').read_text());current=json.loads((ROOT/'competition-v11-latest.json').read_text())
    assert current['status']=='PASS' and current['all_dff_nonincrease'] and current['all_measured_5pct_pass']
    for a,b in zip(previous['cases'],current['cases']):
        assert a['name']==b['name']
        for role in ('baseline','candidate'):assert a['roles'][role]['by_type']==b['roles'][role]['by_type']
    pss=json.loads((ROOT/'competition-v11-tree-pss.json').read_text())
    assert all(c['max_overhead_percent']<=5 for c in pss['cases'])
    receipt=dict(status='PASS',root=str(ROOT),old_objects_copied=0,all_counts_identical=True,
        average_gain_percent=current['average_gain_percent'],proofs=8,fixtures=6,
        note='Fresh source and build directory on the same Ubuntu; existing system compiler/CMake/OSS dependency tools retained. Candidate uses only objects just built for this fresh baseline.')
    (ROOT/'clean-reproduction.json').write_text(json.dumps(receipt,indent=2));stage('PASS')

if __name__=='__main__':
    try:main()
    except Exception as e:
        (ROOT/'clean-failure.json').write_text(json.dumps(dict(error=str(e))));raise
