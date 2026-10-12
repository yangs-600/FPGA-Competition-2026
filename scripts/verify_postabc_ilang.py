"""Prove the four official RTL cases against the actual ABC9-after RTLIL."""
import json, re, subprocess, sys, tempfile
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'clean-v11'))
from run_competition_v11 import environment, counts
from build_069 import ROOT, sha

def prove(src, top, ilang, target, env, manifest, ff_model):
    cfg = target.with_suffix('.eqy')
    cfg.write_text(
        '[gold]\n' + f'read_verilog "{src}"\nprep -top {top} -flatten\nmemory_map\nopt_clean\nrename -hide\n\n' +
        '[gate]\n' + f'read_rtlil "{ilang}"\nread_verilog -overwrite "{ff_model}"\nlut2mux -word\nprep -top {top} -flatten\nmemory_map\nopt_clean\nrename -hide\n\n' +
        '[strategy simple]\nuse sat\ndepth 5\n\n[strategy pdr]\nuse sby\nengine abc pdr\ntimeout 120\n')
    with target.with_suffix('.log').open('w') as log:
        p = subprocess.run(['/usr/bin/python3', '-E', manifest['eqy']['executable'],
                            '--yosys', manifest['baseline'], '--abc', manifest['abc'],
                            '-d', str(target), str(cfg)], env=env, stdout=log,
                           stderr=subprocess.STDOUT, timeout=900)
    versions = []
    for log in target.rglob('*.log'):
        versions += re.findall(r'^Yosys .+$', log.read_text(errors='replace'), re.M)
    if not versions or any(not v.startswith('Yosys 0.69 (') for v in versions):
        raise RuntimeError('Proof engine version mismatch')
    return dict(exit_code=p.returncode, status='PASS' if p.returncode == 0 and
                (target/'PASS').exists() and not (target/'FAIL').exists() else 'FAIL',
                yosys_versions=sorted(set(versions)), config_sha256=sha(cfg),
                path=str(target))

def main():
    env, m = environment()
    out = Path(tempfile.mkdtemp(prefix='postabc-', dir=ROOT))
    model = out/'formal_dffeas.v'
    # synth_intel maps FFs before ABC9. Keep only its previously audited FF model;
    # LUTs are the native $lut cells in the exported ILANG, without a LUT model.
    model.write_text('module dffeas(' + (ROOT/'formal_cycloneiv.v').read_text().split('module dffeas(', 1)[1])
    report = dict(status='RUNNING', report_dir=str(out), cases=[], manifest=m,
                  harness_sha256=sha(Path(__file__)), ff_model_sha256=sha(model),
                  canonical_model_sha256=sha(ROOT/'formal_cycloneiv.v'),
                  proof_stage='synth_intel begin:map_cells (end label excluded); native $lut ILANG after ABC9',
                  proof_preparation='Read native LUT ILANG; standard lut2mux -word lowering for SAT/AIG engine support',
                  ff_model='Restricted dffeas model; prn=1, aload=asdata=sclr=sload=0 are checked',
                  performance_acceptance=False)
    def save():
        (out/'report.json').write_text(json.dumps(report, indent=2))
    save()
    prior = json.loads((ROOT/'competition-v11-latest.json').read_text())
    assert prior['status'] == 'PASS'
    try:
        for n in range(1, 5):
            top = f'test{n}'; src = ROOT/'competition_case'/top/(top+'.v')
            row = dict(name=top, source_sha256=sha(src), roles={})
            report['cases'].append(row)
            previous = next(r for r in prior['cases'] if r['name'] == top)
            assert row['source_sha256'] == previous['source_sha256']
            for role in ('baseline', 'candidate'):
                d = out/top/role; d.mkdir(parents=True)
                flow = d/'flow.ys'
                flow.write_text(f'read_verilog "{src}"\nsynth_intel -family cycloneiv -top {top} -run begin:map_cells\n' +
                                f'select {top}\nwrite_rtlil -selected "{d}/postabc.il"\nselect *\nwrite_json "{d}/postabc.json"\n' +
                                f'synth_intel -family cycloneiv -top {top} -run map_cells:\nwrite_json "{d}/final.json"\n')
                with (d/'synthesis.log').open('w') as log:
                    subprocess.run([m[role], '-Q', '-T', '-s', str(flow)], env=env,
                                   stdout=log, stderr=subprocess.STDOUT, check=True, timeout=120)
                cells = json.loads((d/'postabc.json').read_text())['modules'][top]['cells']
                by = Counter(c['type'] for c in cells.values())
                if not by['$lut'] or set(by)-{'$lut', 'dffeas', '$not', '$_NOT_', '$scopeinfo'}:
                    raise RuntimeError('Unexpected post-ABC cell types: '+repr(by))
                for c in cells.values():
                    if c['type'] == 'dffeas':
                        for pin, value in dict(prn='1', aload='0', asdata='0', sclr='0', sload='0').items():
                            if c['connections'].get(pin) != [value]:
                                raise RuntimeError('Unsupported FF control '+pin)
                logtext = (d/'synthesis.log').read_text()
                if 'Executing ABC9 pass' not in logtext:
                    raise RuntimeError('ABC9 not observed')
                final = counts(d/'final.json', top)
                if final['by_type'] != previous['roles'][role]['by_type']:
                    raise RuntimeError('Split flow changed final counts')
                proof = prove(src, top, d/'postabc.il', d/'proof', env, m, model)
                row['roles'][role] = dict(postabc_by_type=dict(by), final=final, proof=proof,
                                         ilang_sha256=sha(d/'postabc.il'), flow_sha256=sha(flow))
                save()
                if proof['status'] != 'PASS': raise RuntimeError(top+' '+role+' proof failed')
                print(top, role, 'POSTABC_EQY_PASS', dict(by), flush=True)
            b = row['roles']['baseline']['final']; c = row['roles']['candidate']['final']
            row['logic_gain_percent'] = 100*(b['scored_logic_cells']-c['scored_logic_cells'])/b['scored_logic_cells']
        neg = out/'negative'; neg.mkdir()
        bad = neg/'bad.v'
        bad.write_text('module test2(input clk,a,b,c,d,input [4:0] dataa,datab,datac,datad,output [4:0] out); assign out=0; endmodule\n')
        script = neg/'flow.ys'
        script.write_text(f'read_verilog "{bad}"\nsynth_intel -family cycloneiv -top test2 -run begin:map_cells\nselect test2\nwrite_rtlil -selected "{neg}/bad.il"\n')
        with (neg/'synthesis.log').open('w') as log:
            subprocess.run([m['candidate'], '-Q', '-T', '-s', str(script)], env=env,
                           stdout=log, stderr=subprocess.STDOUT, check=True)
        proof = prove(ROOT/'competition_case/test2/test2.v', 'test2', neg/'bad.il', neg/'proof', env, m, model)
        evidence = '\n'.join(p.read_text(errors='replace') for pattern in ('logfile.txt', 'run.log')
                             for p in (neg/'proof/strategies').rglob(pattern))
        if proof['status'] == 'PASS' or not (neg/'proof/FAIL').exists() or not any(
                s in evidence for s in ('model found: FAIL', 'model found for base case: FAIL', 'proof did fail')):
            raise RuntimeError('Negative control lacks a definite counterexample')
        report['negative_control'] = dict(status='EXPECTED_COUNTEREXAMPLE', proof=proof, ilang_sha256=sha(neg/'bad.il'))
        report['average_scored_logic_gain_percent'] = sum(r['logic_gain_percent'] for r in report['cases'])/4
        for role in ('baseline', 'candidate', 'abc'):
            if sha(m[role]) != m[role+'_sha256']: raise RuntimeError('Tool changed during proofs')
        report['status'] = 'PASS'; save()
        print('POSTABC_VALIDATION_PASS', report['average_scored_logic_gain_percent'], out, flush=True)
    except Exception as exc:
        report.update(status='FAIL', error=str(exc)); save(); raise

if __name__ == '__main__': main()
