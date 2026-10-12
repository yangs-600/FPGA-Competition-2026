"""Four immutable RTL cases: Cyclone IV cells, RTL proofs and paired CPU/RSS measurements."""
import argparse,json,os,re,signal,statistics,subprocess,tempfile,time
from collections import Counter
from pathlib import Path
from build_069 import ROOT,WORK,COMMIT,sha

def environment():
    m=json.loads((WORK/'competition-v11/manifest.json').read_text())
    assert m['yosys_commit']==COMMIT and m['yosys_release']=='0.69'
    for role in ('baseline','candidate','abc','abc_script','plugin_source','patch'):
        if sha(m[role])!=m[role+'_sha256']: raise RuntimeError('Changed '+role)
    env=dict(os.environ,PATH=str(WORK/'proof-bin')+os.pathsep+os.environ['PATH'])
    eqy=json.loads((ROOT/'toolchains/eqy-0.69/manifest.json').read_text())
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
                metric='official per-case mean: LUT plus standalone NOT; DFF and all other cell types must not increase',
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
            row['lut_gain_percent']=100*(base['logic_cells']-cand['logic_cells'])/base['logic_cells']
            row['scored_logic_gain_percent']=100*(base['scored_logic_cells']-cand['scored_logic_cells'])/base['scored_logic_cells']
            row['gain_percent']=row['scored_logic_gain_percent']
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
        report['average_lut_gain_percent']=statistics.mean(r['lut_gain_percent'] for r in report['cases'])
        report['all_dff_nonincrease']=all(r['dff_nonincrease'] for r in report['cases'])
        report['all_other_cell_types_nonincrease']=all(r['other_cell_types_nonincrease'] for r in report['cases'])
        report['all_measured_5pct_pass']=all(r['measured_5pct_pass'] for r in report['cases'])
        report['status']='PASS'
        save();print('VALIDATION PASS',report['average_gain_percent'],out,flush=True)
    except Exception as exc:
        report.update(status='FAIL',error=str(exc));save();raise

if __name__=='__main__': main()
