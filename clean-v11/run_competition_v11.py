"""Four immutable RTL cases: Cyclone IV cells, RTL proofs and paired CPU/RSS measurements."""
import argparse,json,os,re,signal,statistics,subprocess,tempfile,time
from collections import Counter
from pathlib import Path
from build_069 import ROOT,WORK,COMMIT,sha

def environment():
    manifest_path=WORK/'competition-v11/manifest.json'
    if manifest_path.exists():
        m=json.loads(manifest_path.read_text())
        assert m['yosys_commit']==COMMIT and m['yosys_release']=='0.69'
        for role in ('baseline','candidate','abc','abc_script','plugin_source','patch'):
            if sha(m[role])!=m[role+'_sha256']: raise RuntimeError('Changed '+role)
    else:
        # A reconstructed build is valid only when the complete toolchain is
        # present and independently identifies itself as the pinned release.
        # This fallback does not fabricate the missing manifest.
        build=WORK/'build-repro'; source=WORK/'src'
        paths=dict(
            baseline=build/'yosys-original',
            candidate=build/'yosys-competition-reconstructed',
            abc=build/'yosys-abc',
            abc_script=ROOT/'competition_abc_dch.abc',
            plugin_source=ROOT/'pmux_competition_v11.cc',
            patch=WORK/'competition-v11/synth-intel-competition.patch')
        missing=[str(path) for path in paths.values() if not path.is_file()]
        if missing:
            raise RuntimeError('No manifest and reconstructed toolchain is incomplete: '+', '.join(missing))
        if not source.is_dir():
            raise RuntimeError('No manifest and reconstructed Yosys source tree is missing')
        commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=source,text=True).strip()
        if commit!=COMMIT: raise RuntimeError('Wrong reconstructed Yosys commit: '+commit)
        integrated_source=source/'passes/opt/pmux_competition_opt.cc'
        if not integrated_source.is_file() or sha(integrated_source)!=sha(paths['plugin_source']):
            raise RuntimeError('Reconstructed PMUX source does not match the project source')
        patch_check=subprocess.run(['git','apply','--check','--reverse',str(paths['patch'])],cwd=source,
                                   stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
        if patch_check.returncode:
            raise RuntimeError('Reconstructed source does not match the integration patch: '+patch_check.stdout)
        versions={role:subprocess.check_output([str(paths[role]),'-V'],text=True).strip()
                  for role in ('baseline','candidate')}
        if any(not value.startswith('Yosys 0.69 (') for value in versions.values()):
            raise RuntimeError('Expected exact reconstructed Yosys 0.69: '+repr(versions))
        help_text=subprocess.check_output([str(paths['candidate']),'-Q','-T','-p','help pmux_competition_opt'],text=True)
        if 'at any data width' not in help_text:
            raise RuntimeError('Reconstructed candidate does not contain the v15 PMUX pass')
        rejected=subprocess.run([str(paths['baseline']),'-Q','-T','-p','pmux_competition_opt'],
                                stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
        if rejected.returncode==0: raise RuntimeError('Reconstructed baseline contains the candidate pass')
        m=dict(yosys_release='0.69',yosys_commit=COMMIT,reconstructed_environment=True,
               baseline_version=versions['baseline'],candidate_version=versions['candidate'])
        for role,path in paths.items():
            m[role]=str(path);m[role+'_sha256']=sha(path)
    proof_paths=[ROOT/'proof-bin',WORK/'proof-bin']
    env=dict(os.environ,PATH=os.pathsep.join(str(path) for path in proof_paths)+os.pathsep+os.environ['PATH'])
    eqy_manifest=ROOT/'toolchains/eqy-0.69/manifest.json'
    if eqy_manifest.exists():
        eqy=json.loads(eqy_manifest.read_text())
    else:
        executable=ROOT/'toolchains/eqy-0.69/install-repro/bin/eqy'
        if not executable.is_file(): raise RuntimeError('EQY manifest and reconstructed executable are missing')
        version=subprocess.check_output(['/usr/bin/python3','-E',str(executable),'--version'],text=True).strip()
        if version!='EQY v0.69': raise RuntimeError('Expected exact reconstructed EQY v0.69: '+version)
        eqy=dict(executable=str(executable),version=version,files={str(executable):sha(executable)},
                 reconstructed_environment=True)
    for path,digest in eqy['files'].items():
        if sha(path)!=digest: raise RuntimeError('EQY tool changed '+path)
    m['eqy']=eqy
    for case in json.loads((ROOT/'competition_inputs.json').read_text())['cases']:
        if sha(ROOT/'competition_case'/case['path'])!=case['sha256']: raise RuntimeError('Original RTL hash changed')
    return env,m

def measure(command,log,env):
    start=time.monotonic()
    with open(log,'w') as f:
        p=subprocess.Popen(command,stdout=f,stderr=subprocess.STDOUT,env=env,start_new_session=True)
        while True:
            pid,status,usage=os.wait4(p.pid,os.WNOHANG)
            if pid: break
            if time.monotonic()-start>120:
                os.killpg(p.pid,signal.SIGKILL);os.waitpid(p.pid,0)
                raise RuntimeError('Synthesis timeout')
            time.sleep(.002)
        p.returncode=os.waitstatus_to_exitcode(status)
    if p.returncode: raise RuntimeError('Synthesis failed: '+str(log))
    return dict(cpu_seconds=usage.ru_utime+usage.ru_stime,wall_seconds=time.monotonic()-start,
                peak_rss_kib=usage.ru_maxrss)

def counts(path,top):
    net=json.loads(path.read_text()); cells=net['modules'][top]['cells']
    by=Counter(c['type'] for c in cells.values())
    if set(by)-{'cycloneiv_lcell_comb','dffeas','$not','$scopeinfo'}:
        raise RuntimeError('Unmapped or unsupported cells '+str(by))
    for c in cells.values():
        if c['type']=='dffeas':
            for pin,value in dict(prn='1',aload='0',asdata='0',sclr='0',sload='0').items():
                if c['connections'].get(pin)!=[value]: raise RuntimeError('Unsupported FF control '+pin)
        if c['type']=='cycloneiv_lcell_comb':
            if c['parameters'].get('sum_lutc_input','datac')!='datac': raise RuntimeError('Carry LUT unsupported')
            if c['connections'].get('cout'): raise RuntimeError('Carry output unsupported')
    return dict(logic_cells=by['cycloneiv_lcell_comb'],dff_cells=by['dffeas'],
                standalone_not_cells=by['$not'],scored_logic_cells=by['cycloneiv_lcell_comb']+by['$not'],
                by_type=dict(by))

def prove(src,top,netlist,folder,env):
    cfg=folder.with_suffix('.eqy')
    cfg.write_text('[gold]\n'+f'read_verilog "{src}"\nprep -top {top} -flatten\nmemory_map\nopt_clean\nrename -hide\n\n'+
       '[gate]\n'+f'read_verilog "{ROOT}/formal_cycloneiv.v"\nread_verilog "{netlist}"\nprep -top {top} -flatten\nmemory_map\nopt_clean\nrename -hide\n\n'+
       '[strategy simple]\nuse sat\ndepth 5\n\n[strategy pdr]\nuse sby\nengine abc pdr\ntimeout 60\n')
    _,manifest=environment()
    with folder.with_suffix('.log').open('w') as f:
        p=subprocess.run(['/usr/bin/python3','-E',manifest['eqy']['executable'],'--yosys',manifest['baseline'],'--abc',manifest['abc'],'-d',str(folder),str(cfg)],stdout=f,stderr=subprocess.STDOUT,env=env,timeout=600)
    versions=[]
    for logfile in folder.rglob('*.log'):
        versions += re.findall(r'^Yosys .+$',logfile.read_text(errors='replace'),re.M)
    if not versions or any(not v.startswith('Yosys 0.69 (') for v in versions):
        raise RuntimeError('Proof engine version mismatch: '+str(set(versions)))
    (folder/'verified_yosys_versions.json').write_text(json.dumps(sorted(set(versions)),indent=2))
    return p.returncode==0 and (folder/'PASS').exists() and not (folder/'FAIL').exists()

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--repeats',type=int,default=21)
    args=ap.parse_args()
    if args.repeats<3: ap.error('At least 3 paired repeats required')
    env,m=environment();out=Path(tempfile.mkdtemp(prefix='competition-v11-',dir=ROOT))
    report=dict(status='RUNNING',harness_sha256=sha(Path(__file__)),formal_model_sha256=sha(ROOT/'formal_cycloneiv.v'),manifest=m,cases=[],report_dir=str(out),repeats=args.repeats,
                metric='primary LUT count plus explicit $not audit; every non-LUT cell type is constrained not to increase',
                timing='Linux wait4 user+system CPU, including waited ABC descendants; full read/synth/write process',
                memory='Linux wait4 ru_maxrss: maximum resident high-water mark, not simultaneous sum of process-tree RSS',
                proof_model='Restricted inverse models of emitted Cyclone IV LUT and DFFE mapping, not vendor timing models')
    def save():
        (out/'report.json').write_text(json.dumps(report,indent=2))
        (ROOT/'competition-v11-latest.json').write_text(json.dumps(report,indent=2))
    save()
    try:
        for n in range(1,5):
            top=f'test{n}';src=ROOT/'competition_case'/top/(top+'.v'); case=out/top;case.mkdir()
            row=dict(name=top,source_sha256=sha(src),source=str(src),roles={});report['cases'].append(row);save()
            commands={}
            for role in ('baseline','candidate'):
                target=case/role;target.mkdir()
                flow=target/'flow.ys'
                flow.write_text(f'read_verilog "{src}"\nsynth_intel -family cycloneiv -top {top}\nwrite_verilog -norename -noattr "{target}/netlist.v"\nwrite_json "{target}/netlist.json"\n')
                commands[role]=[m[role],'-Q','-T','-q','-s',str(flow)]
                initial=measure([m[role],'-Q','-T','-s',str(flow)],target/'synthesis.log',env)
                resource=counts(target/'netlist.json',top)
                proof=prove(src,top,target/'netlist.v',target/'proof',env)
                row['roles'][role]=dict(**resource,initial=initial,proof='PASS' if proof else 'FAIL',path=str(target),samples=[])
                save()
                if not proof: raise RuntimeError('RTL equivalence failed '+top+' '+role)
            base=row['roles']['baseline'];cand=row['roles']['candidate']
            row['gain_percent']=100*(base['logic_cells']-cand['logic_cells'])/base['logic_cells']
            row['scored_logic_gain_percent']=100*(base['scored_logic_cells']-cand['scored_logic_cells'])/base['scored_logic_cells']
            row['dff_nonincrease']=cand['dff_cells']<=base['dff_cells']
            checked_types=(set(base['by_type'])|set(cand['by_type']))-{'cycloneiv_lcell_comb','$scopeinfo'}
            row['other_cell_types_nonincrease']=all(cand['by_type'].get(t,0)<=base['by_type'].get(t,0) for t in checked_types)
            if not row['other_cell_types_nonincrease']:
                raise RuntimeError('Non-LUT cell increase '+top+': '+str({t:(base['by_type'].get(t,0),cand['by_type'].get(t,0)) for t in checked_types}))
            for role in commands: measure(commands[role],os.devnull,env)
            for i in range(args.repeats):
                for role in (('baseline','candidate') if i%2==0 else ('candidate','baseline')):
                    row['roles'][role]['samples'].append(measure(commands[role],os.devnull,env))
            for role in commands:
                r=row['roles'][role]
                r['median_cpu_seconds']=statistics.median(s['cpu_seconds'] for s in r['samples'])
                r['median_peak_rss_kib']=statistics.median(s['peak_rss_kib'] for s in r['samples'])
                r['max_peak_rss_kib']=max(s['peak_rss_kib'] for s in r['samples'])
                r['cpu_range_seconds']=[min(s['cpu_seconds'] for s in r['samples']),max(s['cpu_seconds'] for s in r['samples'])]
                if counts(Path(r['path'])/'netlist.json',top)['by_type']!=r['by_type']: raise RuntimeError('Nondeterministic counts')
            row['cpu_overhead_percent']=100*(cand['median_cpu_seconds']/base['median_cpu_seconds']-1)
            row['rss_overhead_percent']=100*(cand['max_peak_rss_kib']/base['max_peak_rss_kib']-1)
            row['measured_5pct_pass']=row['cpu_overhead_percent']<=5 and row['rss_overhead_percent']<=5
            print(top,'logic',base['logic_cells'],cand['logic_cells'],'DFF',base['dff_cells'],cand['dff_cells'],
                  'gain',round(row['gain_percent'],3),'CPU%',round(row['cpu_overhead_percent'],2),'RSS%',round(row['rss_overhead_percent'],2),flush=True)
            save()
        # A real output mutation must fail the same formal checker.
        negative=out/'negative';negative.mkdir()
        bad=negative/'bad.v'
        bad.write_text('module test2(input clk,a,b,c,d,input [4:0] dataa,datab,datac,datad,output [4:0] out); assign out=0; endmodule\n')
        ok=prove(ROOT/'competition_case/test2/test2.v','test2',bad,negative/'proof',env)
        report['negative_control']='UNEXPECTED_PASS' if ok else 'FAIL'
        logs=list((negative/'proof/strategies').rglob('logfile.txt'))+list((negative/'proof/strategies').rglob('run.log'))
        evidence='\n'.join(p.read_text(errors='replace') for p in logs)
        if ok or not (negative/'proof/FAIL').exists() or not any(x in evidence for x in ('model found: FAIL','model found for base case: FAIL','proof did fail')):
            raise RuntimeError('Negative control needs a definite counterexample; inspect log')
        report['negative_control']='EXPECTED_COUNTEREXAMPLE'
        report['average_gain_percent']=statistics.mean(r['gain_percent'] for r in report['cases'])
        report['all_dff_nonincrease']=all(r['dff_nonincrease'] for r in report['cases'])
        report['all_other_cell_types_nonincrease']=all(r['other_cell_types_nonincrease'] for r in report['cases'])
        report['all_measured_5pct_pass']=all(r['measured_5pct_pass'] for r in report['cases'])
        report['status']='PASS'
        save();print('VALIDATION PASS',report['average_gain_percent'],out,flush=True)
    except Exception as exc:
        report.update(status='FAIL',error=str(exc));save();raise

if __name__=='__main__': main()
