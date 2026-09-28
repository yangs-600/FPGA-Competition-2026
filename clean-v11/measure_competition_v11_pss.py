"""Supplemental summed process-tree RSS sampling; not an exact kernel peak."""
import json,os,subprocess,time,statistics
from pathlib import Path
from run_competition_v11 import environment
from build_069 import ROOT

def sample(pid):
    todo=[pid];seen=set();total=0;details=[]
    while todo:
        current=todo.pop()
        if current in seen: continue
        seen.add(current)
        try:
            todo += [int(n) for n in Path(f'/proc/{current}/task/{current}/children').read_text().split()]
            rollup=Path(f'/proc/{current}/smaps_rollup').read_text()
            rss=int(next(line.split()[1] for line in rollup.splitlines() if line.startswith('Pss:')))*1024
            total += rss
            details.append(dict(pid=current,pss_kib=rss//1024,command=Path(f'/proc/{current}/comm').read_text().strip()))
        except (FileNotFoundError,ProcessLookupError,PermissionError): pass
    return total,details

def main():
    env,m=environment();r=json.loads((ROOT/'competition-v11-latest.json').read_text())
    if r['status']!='PASS': raise RuntimeError('Complete formal validation first')
    result=dict(status='PASS',report_dir=r['report_dir'],cases=[],interval_seconds=.001,
                note='Sampled process-tree PSS apportions shared resident pages; non-atomic /proc reads and brief missed peaks remain limitations. Not official memory metric.')
    for row in r['cases']:
        samples={role:[] for role in ('baseline','candidate')}
        compositions={role:[] for role in samples}
        for i in range(21):
            for role in (('baseline','candidate') if i%2==0 else ('candidate','baseline')):
                path=Path(row['roles'][role]['path'])/'flow.ys'
                with open(os.devnull,'w') as log:
                    p=subprocess.Popen([m[role],'-Q','-T','-q','-s',str(path)],stdout=log,stderr=log,env=env)
                    peak=0;composition=[];start=time.monotonic()
                    while p.poll() is None:
                        current,detail=sample(p.pid)
                        if current>peak: peak=current;composition=detail
                        if time.monotonic()-start>120: p.kill();p.wait();raise RuntimeError('Timeout')
                        time.sleep(.001)
                if p.returncode: raise RuntimeError('Synthesis failed')
                samples[role].append(peak/1048576)
                compositions[role].append(composition)
        item=dict(name=row['name'],sampled_peak_pss_mib=samples,peak_compositions=compositions,
                  max_overhead_percent=100*(max(samples['candidate'])/max(samples['baseline'])-1))
        result['cases'].append(item);print(row['name'],item['max_overhead_percent'],flush=True)
    (ROOT/'competition-v11-tree-pss.json').write_text(json.dumps(result,indent=2))

if __name__=='__main__':main()
