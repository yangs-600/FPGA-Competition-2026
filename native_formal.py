"""Prove this run's Windows post-ABC objects with a configured Windows OSS CAD Suite.

The synthesis binaries and measurement protocol are not changed.  A proof result
is bound to the immutable measurement report and to the exact RTL/RTLIL bytes.
"""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid

INDEX_SHA = 'daefcb876db83cc4766583ba188c234e126561aa817cacf80f1a01a213792ba4'
CEX_PHRASES = ('model found: FAIL', 'model found for base case: FAIL', 'proof did fail')

def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for data in iter(lambda:f.read(1024*1024),b''):h.update(data)
    return h.hexdigest()
def now():return datetime.now(timezone.utc).isoformat()
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def save(p,data):Path(p).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def need(ok,message):
    if not ok:raise RuntimeError(message)
def module(path,name):
    spec=importlib.util.spec_from_file_location(name,path)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result
def inside(root,name):
    p=Path(name)
    need(not p.is_absolute() and not p.drive and '..' not in p.parts,'Expected relative evidence path')
    p=(root/p).resolve();need(p.is_relative_to(root),'Evidence escaped package');return p
def capture(command,env,cwd,timeout=30):
    p=subprocess.run([str(c) for c in command],env=env,cwd=cwd,capture_output=True,timeout=timeout)
    need(p.returncode==0,'Tool failed: '+str(command[0])+'\n'+p.stdout.decode('utf-8','replace')+p.stderr.decode('utf-8','replace'))
    return p.stdout.decode('utf-8','replace').strip()

def executable_in_path(name,path):
    """Search only explicit PATH entries, never the caller's current directory.

    shutil.which on Windows may prepend cwd even when path= is supplied. The
    package root contains the measurement ABC, which is not the proof ABC.
    All command dependencies used here are PE .exe files, not CMD wrappers.
    """
    for entry in path.split(os.pathsep):
        folder=Path(entry.strip('"'))
        if not folder.is_absolute():continue
        candidate=folder/(name if name.lower().endswith('.exe') else name+'.exe')
        if candidate.is_file():return candidate.resolve()
    return None

def suite_environment(suite,attempt):
    need(os.name=='nt','Windows native EQY needs Windows')
    suite=Path(suite).resolve()
    need(suite.is_dir(),'OSS CAD Suite installation directory is missing: '+str(suite))
    # CMD and EQY's generated makefiles both interpret these paths.
    need(re.fullmatch(r'[A-Za-z]:[/\\A-Za-z0-9_.-]+',str(suite)),
         'Use an ASCII suite path without spaces or shell metacharacters')
    script=suite/'environment.bat';need(script.is_file(),'Missing OSS CAD Suite environment.bat')
    bootstrap=attempt/'read-suite-environment.cmd'
    bootstrap.write_text('@echo off\ncall "'+str(script)+'" >nul\nif errorlevel 1 exit /b 1\nset\n',encoding='ascii')
    cmd=Path(os.environ.get('SystemRoot','C:/Windows'))/'System32/cmd.exe'
    tool_vars=('ABC','YOSYS','SMTBMC','WITNESS','SUPROVE','AIGBMC','AVY','BTORMC','PONO','RIC3','IMCTK_EQY_ENGINE')
    base_env={k:v for k,v in os.environ.items() if k.upper() not in tool_vars+('YOSYSHQ_ROOT','PYTHONHOME','PYTHONPATH','PYTHONUSERBASE','PYTHONSTARTUP','PYTHONINSPECT','PYTHON_EXECUTABLE','YOSYS_DATDIR','BASH_ENV','ENV','MSYSTEM')}
    for k in list(base_env):
        if k.lower()=='path':base_env.pop(k)
    base_env['PATH']=str(cmd.parent)
    process=subprocess.run([str(cmd),'/d','/u','/c',str(bootstrap)],capture_output=True,timeout=30,env=base_env)
    need(process.returncode==0,'OSS CAD Suite environment setup failed')
    # The environment may contain secrets; never write it into logs or reports.
    env={}
    for line in process.stdout.decode('utf-16-le').splitlines():
        if '=' in line and not line.startswith('='):
            key,value=line.split('=',1);env[key]=value
    need(any(k.lower()=='path' for k in env),'Suite environment did not provide PATH')
    for key in list(env):
        if key.upper() in tool_vars+('YOSYS_DATDIR','PYTHONPATH','PYTHONHOME','PYTHONUSERBASE','PYTHONSTARTUP','PYTHONINSPECT','BASH_ENV','ENV'):
            env.pop(key,None)
    env['PYTHONDONTWRITEBYTECODE']='1'
    env['PYTHONNOUSERSITE']='1'
    env['NoDefaultCurrentDirectoryInExePath']='1'
    support=Path(__file__).resolve().parent/'native_support/usr/bin'
    need((support/'make.exe').is_file(),'Bundled native_support/make.exe is missing')
    (support.parents[1]/'tmp').mkdir(exist_ok=True)
    path_key=next(k for k in env if k.lower()=='path')
    env[path_key]=str(support)+';'+env[path_key]
    path=env[path_key]
    return suite,env,path

def tools_for_suite(suite,env,path,attempt):
    def pick(name,choices):
        items=[suite/p for p in choices]
        found=next((p for p in items if p.is_file()),None)
        need(found is not None,'Missing '+name+' inside OSS CAD Suite')
        return found
    selected={
        'yosys':pick('Yosys',['bin/yosys.exe']),
        'abc':pick('ABC',['bin/yosys-abc.exe','bin/abc.exe']),
        'python':pick('Python',['lib/python3.exe','bin/python3.exe','bin/python.exe','lib/python.exe']),
        'eqy':pick('EQY',['bin/eqy-script.py','bin/eqy','bin/eqy.py']),
    }
    for name in ('make','bash','grep','awk','sby'):
        located=executable_in_path(name,path)
        need(located,'OSS CAD Suite environment cannot locate '+name)
        selected[name]=Path(located).resolve()
    for name in ('make','bash','grep','awk'):
        need(selected[name].is_relative_to(Path(__file__).resolve().parent/'native_support'),
             'External command shadows the bundled proof dependency: '+name)
    need(selected['sby'].is_relative_to(suite),'SBY resolves outside configured OSS CAD Suite')
    for command,tool in (('yosys','yosys'),('yosys-abc','abc')):
        resolved=executable_in_path(command,path)
        need(resolved and Path(resolved).resolve()==selected[tool].resolve(),
             'Indirect proof command does not use the configured suite: '+command)
    # SBY consumes these variables for its internal Yosys/ABC invocations.
    # Use full paths as well as a restricted PATH, so cwd cannot select the
    # package's measurement executable. Forward slashes also work in Bash.
    env['YOSYS']=selected['yosys'].as_posix()
    env['ABC']=selected['abc'].as_posix()
    shell_paths=capture([selected['bash'],'--noprofile','--norc','-c',
                         'command -v yosys; command -v yosys-abc'],env,attempt).splitlines()
    need(len(shell_paths)==2,'Could not inspect proof Bash command resolution')
    for found,tool in zip(shell_paths,('yosys','abc')):
        found=re.sub(r'^/cygdrive/([A-Za-z])/',lambda m:m[1]+':/',found)
        found=re.sub(r'^/([A-Za-z])/',lambda m:m[1]+':/',found)
        if not found.lower().endswith('.exe'):found+='.exe'
        need(Path(found).resolve()==selected[tool].resolve(),
             'Proof Bash command resolves outside configured suite: '+tool)
    versions={
        'yosys':capture([selected['yosys'],'-V'],env,attempt),
        'eqy':capture([selected['python'],'-s','-B',selected['eqy'],'--version'],env,attempt),
        'python':capture([selected['python'],'--version'],env,attempt),
        'make':capture([selected['make'],'--version'],env,attempt).splitlines()[0],
        'sby':capture([selected['sby'],'--version'],env,attempt),
    }
    need(versions['yosys'].startswith('Yosys '),'Unexpected proof Yosys version')
    return selected,versions

def prove(src,top,ilang,target,env,tools,model,runner,expected_version,timeout=300):
    config=target.with_suffix('.eqy')
    option=' -sv' if src.suffix.lower()=='.sv' else ''
    config.write_text('[gold]\n'+f'read_verilog{option} "{src.as_posix()}"\nprep -top {top} -flatten\nmemory_map\nopt_clean\nrename -hide\n\n'
       +'[gate]\n'+f'read_rtlil "{ilang.as_posix()}"\nread_verilog -overwrite "{model.as_posix()}"\nlut2mux -word\nprep -top {top} -flatten\nmemory_map\nopt_clean\nrename -hide\n\n'
       +'[strategy simple]\nuse sat\ndepth 5\n\n[strategy pdr]\nuse sby\nengine abc pdr\n'+f'timeout {timeout}\n',encoding='utf-8')
    log=target.with_suffix('.log')
    execution=runner.run([tools['python'],'-s','-B',tools['eqy'],'--yosys',tools['yosys'],
                         '--abc',tools['abc'],'-d',target,config],log,env,max(900,timeout*3),target.parent)
    logs=list(target.rglob('*.log'))+[log]
    versions=sorted(set(v for p in logs if p.is_file() for v in re.findall(r'^Yosys .+$',p.read_text(encoding='utf-8',errors='replace'),re.M)))
    version_prefix=expected_version.split(' (')[0]
    version_ok=bool(versions) and all(v.startswith(version_prefix+' ') or v.strip()==version_prefix for v in versions)
    evidence=[]
    for p in list(target.rglob('logfile.txt'))+list(target.rglob('run.log')):
        text=p.read_text(encoding='utf-8',errors='replace')
        phrases=[x for x in CEX_PHRASES if x in text]
        if phrases:evidence.append({'path':str(p),'sha256':sha(p),'phrases':phrases})
    success=execution['exit_code']==0 and (target/'PASS').is_file() and not (target/'FAIL').exists() and not (target/'UNKNOWN').exists()
    counterexample=(target/'FAIL').is_file() and bool(evidence)
    if execution['timed_out'] or not execution['descendant_cleanup_verified'] or not version_ok:status='ERROR'
    elif success:status='PASS'
    elif counterexample:status='FAIL'
    else:status='UNKNOWN'
    return dict(execution, status=status,config_sha256=sha(config),log_sha256=sha(log),
                definite_counterexample=counterexample,counterexample_evidence=evidence,
                proof_engine_versions_valid=version_ok,yosys_versions=versions,
                status_markers={n:(target/n).is_file() for n in ('PASS','FAIL','UNKNOWN')})

def run_formal(root,report_path,suite_path,*,diagnostic_cases=None):
    root=Path(root).resolve();report_path=Path(report_path).resolve()
    need(re.fullmatch(r'[A-Za-z]:[/\\A-Za-z0-9_.-]+',str(root)),
         'Native EQY requires an ASCII package path without spaces or shell metacharacters')
    need(report_path.parent.parent==root and report_path.name=='report.json','Use a per-run report inside the package')
    run=read(report_path);run_hash=sha(report_path)
    need(report_path.parent.name==run['directory'],'Report directory mismatch')
    # Keep strategy working paths short: native Yosys uses the Windows CRT,
    # whose relative file opens can still hit MAX_PATH despite Python support.
    attempt=root/'tmp/nf'/uuid.uuid4().hex[:8];attempt.mkdir(parents=True)
    receipt=attempt/'formal-receipt.json';proof_report_path=attempt/'proof-report.json'
    result={'schema':'windows-native-demo-formal-v1','status':'ERROR','started_at':now(),
            'backend':'windows-native','windows_report_sha256':run_hash,'positive_proof_counts':{},
            'negative_control':{'status':'NOT_RUN'},'case_rows':[], 'performance_retested':False,
            'paths':{'receipt':receipt.relative_to(root).as_posix(),'formal_report':proof_report_path.relative_to(root).as_posix()}}
    evidence={'status':'RUNNING','cases':[],'windows_report_sha256':run_hash,'started_at':now()}
    save(receipt,result);save(proof_report_path,evidence)
    try:
        need(sha(root/'payload-index.json')==INDEX_SHA,'Frozen package index changed')
        index=read(root/'payload-index.json')['files']
        core_path=root/'source/verify_current_cases.py';canonical=root/'source/formal_cycloneiv.v'
        bundler=root/'source/bundle_native_evidence.py'
        for p in (core_path,canonical,bundler):need(sha(p)==index[p.relative_to(root).as_posix()]['sha256'],'Frozen proof helper/model changed')
        core=module(core_path,'native_proof_frozen_core')
        runner=module(Path(__file__).with_name('native_job.py'),'native_proof_job')
        result['adapter_sha256']=sha(Path(__file__));result['job_runner_sha256']=sha(Path(__file__).with_name('native_job.py'))
        suite,env,path=suite_environment(suite_path,attempt)
        tools,versions=tools_for_suite(suite,env,path,attempt)
        tool_hashes={str(p):sha(p) for p in set(tools.values()) if p.is_file()}
        support_root=Path(__file__).resolve().parent/'native_support'
        for item in read(support_root/'provenance.json')['files'].values():
            p=inside(support_root,item['file'])
            need(sha(p)==item['sha256'],'Bundled proof command dependency changed: '+item['file'])
            tool_hashes[str(p)]=item['sha256']
        for p in (suite/'share/yosys/plugins').glob('eqy*'):tool_hashes[str(p)]=sha(p)
        for p in (suite/'share/yosys/python3').glob('*.py'):
            if p.is_file():tool_hashes[str(p)]=sha(p)
        for pattern in ('bin/*-script.py','lib/python*.dll','bin/*.dll','lib/*.dll'):
            for p in suite.glob(pattern):
                if p.is_file():tool_hashes[str(p)]=sha(p)
        result['tool_metadata']={'suite':str(suite),'proof_engine_versions':versions,'tool_sha256':tool_hashes}
        # The original bundler verifies all source, measurement and binary bindings.
        bundle=attempt/'bundle'
        execution=runner.run([root/'runtime/python.exe','-I','-S','-B','-X','utf8',bundler,
                              '--package',root,'--report',report_path,'--output',bundle],attempt/'bundle.log',os.environ.copy(),180,root)
        need(execution['exit_code']==0 and not execution['timed_out'],'Measurement evidence validation failed; see bundle.log')
        need(sha(bundle/'report.json')==run_hash,'Copied report differs')
        inv=read(bundle/'evidence-inventory.json')
        model=attempt/'formal_dffeas.v';core.extract_ff_model(canonical,model)
        evidence.update(tool_versions=versions,tool_sha256=tool_hashes,formal_model_sha256=sha(model),
                        canonical_model_sha256=sha(canonical),evidence_inventory_sha256=sha(bundle/'evidence-inventory.json'),
                        proof_preparation='Unchanged canonical dynamic-clrn dffeas model, lut2mux -word, SAT depth 5 + SBY ABC PDR',
                        diagnostics_only=bool(diagnostic_cases))
        registry=read(bundle/'cases_current.json')['cases'];rows={r['name']:r for r in run['cases']}
        need(len(registry)==len(rows)==len({c['name'] for c in registry})==9,'Expected nine unique cases')
        manifest=read(bundle/'manifest.json')
        for row in run['cases']:
            for role in ('baseline','candidate'):
                data=row['roles'][role]
                need(data['executable_sha256']==manifest['roles'][role]['files']['yosys.exe'], 'Measured executable binding differs')
                need(data.get('formal_object_status')=='EXPORTED_NOT_PROVED' and data.get('samples'), 'Missing complete measurement/proof object')
        if diagnostic_cases:need(set(diagnostic_cases).issubset(rows),'Unknown diagnostic case')
        for case_number,case in enumerate(registry):
            name=case['name'];top=case['top']
            if diagnostic_cases and name not in diagnostic_cases:continue
            need(re.fullmatch(r'[A-Za-z_][A-Za-z0-9_$]*',top),'Invalid top name')
            row=rows[name];src=inside(bundle,case['path'])
            need(row['source_sha256']==case['sha256']==sha(src) and row['source_path']==case['path'] and row['top']==top,'Case identity mismatch')
            record={'name':name,'roles':{}};evidence['cases'].append(record)
            for role in ('baseline','candidate'):
                folder=attempt/('c'+str(case_number))/role[0];folder.mkdir(parents=True)
                data=row['roles'][role];original=inside(bundle,data['path']+'/postabc.il')
                need(sha(original)==data['ilang_sha256'],'Windows netlist changed')
                raw=original.read_bytes();normalized=raw.replace(b'\r\n',b'\n')
                need(b'\r' not in normalized and (normalized.replace(b'\n',b'\r\n') if b'\r\n' in raw else normalized)==raw,'Non-reversible line ending conversion')
                ilang=folder/'postabc-lf.il';ilang.write_bytes(normalized)
                audit_json=folder/'audit.json';audit_flow=folder/'audit.ys'
                audit_flow.write_text(f'read_verilog -lib "{model.as_posix()}"\nread_rtlil "{ilang.as_posix()}"\nwrite_json "{audit_json.as_posix()}"\n',encoding='utf-8')
                check_run=runner.run([tools['yosys'],'-Q','-T','-s',audit_flow],folder/'audit.log',env,120,folder)
                need(check_run['exit_code']==0 and not check_run['timed_out'],'RTLIL cell/control audit failed')
                audit=core.audit_postabc(audit_json,top)
                proof=prove(src,top,ilang,folder/'proof',env,tools,model,runner,versions['yosys'])
                record['roles'][role]={'status':proof['status'],'proof':proof,'audit':audit,
                                       'original_ilang_sha256':sha(original),'normalized_ilang_sha256':sha(ilang)}
                print(name,role,'WINDOWS_NATIVE_EQY_'+proof['status'],flush=True)
                save(proof_report_path,evidence)
        negative=attempt/'negative';negative.mkdir()
        src=inside(bundle,next(c['path'] for c in registry if c['name']=='test2'))
        wrong=negative/'bad.v';wrong.write_text('module test2(input clk,a,b,c,d,input [4:0] dataa,datab,datac,datad,output [4:0] out); assign out=0; endmodule\n',encoding='utf-8')
        il=negative/'bad.il';flow=negative/'flow.ys'
        # Constant-zero gate has no mapped logic; generic preparation avoids an
        # unrelated proof-suite ABC9 temporary-file issue and leaves the same
        # deliberately incorrect function for the identical EQY proof chain.
        flow.write_text(f'read_verilog "{wrong.as_posix()}"\nprep -top test2\nselect test2\nwrite_rtlil -selected "{il.as_posix()}"\n',encoding='utf-8')
        generation=runner.run([tools['yosys'],'-Q','-T','-s',flow],negative/'synthesis.log',env,120,negative)
        need(generation['exit_code']==0 and not generation['timed_out'],'Negative control generation failed')
        neg=prove(src,'test2',il,negative/'proof',env,tools,model,runner,versions['yosys'])
        negative_ok=neg['status']=='FAIL' and neg['definite_counterexample']
        evidence['negative_control']={'status':'EXPECTED_COUNTEREXAMPLE' if negative_ok else 'INVALID_NEGATIVE_CONTROL',
                                      'method':'Constant-zero test2 prepared by proof Yosys; unchanged EQY SAT/PDR strategies',
                                      'proof':neg,'wrong_rtl_sha256':sha(wrong),'wrong_ilang_sha256':sha(il)}
        for p,digest in tool_hashes.items():need(sha(Path(p))==digest,'Proof tool changed during execution')
        for name,data in inv['payload_files'].items():need(sha(inside(bundle,name))==data['sha256'],'Evidence changed during proof')
        need(sha(report_path)==run_hash,'Original Windows report changed')
        counts=dict(Counter(v['status'] for row in evidence['cases'] for v in row['roles'].values()))
        expected=2*(len(diagnostic_cases) if diagnostic_cases else 9)
        passed=counts=={'PASS':expected} and negative_ok
        status=('SUBSET_PASS' if diagnostic_cases else 'PASS') if passed else 'FAIL'
        result.update(status=status,positive_proof_counts=counts,negative_control=evidence['negative_control'],
                      case_rows=[{'name':r['name'], **{role:r['roles'][role]['status'] for role in ('baseline','candidate')}} for r in evidence['cases']],
                      descendant_cleanup_verified=True,source_and_evidence_unchanged=True)
        evidence.update(status=status,positive_proof_counts=counts)
    except (Exception, KeyboardInterrupt) as error:
        result.update(status='ERROR',error=f'{type(error).__name__}: {error}')
        evidence.update(status='ERROR',error=result['error'])
    finally:
        result['completed_at']=now();evidence['completed_at']=result['completed_at']
        save(proof_report_path,evidence);result['formal_report_sha256']=sha(proof_report_path);save(receipt,result)
    return result

if __name__=='__main__':
    import argparse
    ap=argparse.ArgumentParser();ap.add_argument('--package',type=Path,required=True);ap.add_argument('--report',type=Path,required=True);ap.add_argument('--suite',type=Path,required=True);ap.add_argument('--case',action='append')
    args=ap.parse_args();result=run_formal(args.package,args.report,args.suite,diagnostic_cases=args.case)
    print(json.dumps(result,ensure_ascii=False,indent=2));raise SystemExit(0 if result['status'] in ('PASS','SUBSET_PASS') else 3)
