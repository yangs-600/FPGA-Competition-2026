"""EQY proofs of actual Windows-produced native LUT ILANG on pinned Ubuntu tools."""
import json,sys,tempfile,zipfile,subprocess
from collections import Counter
from pathlib import Path
REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'scripts'))
import verify_postabc_ilang as v

def main():
    env,m=v.environment()
    out=Path(tempfile.mkdtemp(prefix='postabc-windows-',dir=v.ROOT))
    bundle=Path(sys.argv[1])
    with zipfile.ZipFile(bundle) as z:
        if z.testzip():raise RuntimeError('Corrupt Windows input archive')
        for name in z.namelist():
            if Path(name).is_absolute() or '..' in Path(name).parts:raise RuntimeError('Unsafe input path')
        z.extractall(out/'windows-inputs')
    inputs=out/'windows-inputs';win=json.loads((inputs/'report.json').read_text())
    assert win['status']=='MEASUREMENTS_PASS_FORMAL_PENDING'
    model=out/'formal_dffeas.v'
    model.write_text('module dffeas('+(v.ROOT/'formal_cycloneiv.v').read_text().split('module dffeas(',1)[1])
    result=dict(status='RUNNING',directory=str(out),windows_report_sha256=v.sha(inputs/'report.json'),
                windows_manifest_sha256=v.sha(inputs/'manifest.json'),windows_bundle_sha256=v.sha(bundle),
                harness_sha256=v.sha(Path(__file__)),proof_harness_sha256=v.sha(Path(v.__file__)),
                formal_model_sha256=v.sha(model),cases=[],proof_engine_manifest=m,
                proof_stage='Actual Windows ABC9-after native LUT ILANG; source RTL unchanged',
                line_endings='Original Windows CRLF bytes preserved; proof input has reversible CRLF-to-LF normalization only',
                proof_preparation='Native LUTs lowered by standard lut2mux -word; audited restricted dffeas model')
    def save():(out/'report.json').write_text(json.dumps(result,indent=2))
    save()
    try:
        for row in win['cases']:
            top=row['name'];src=v.ROOT/'competition_case'/top/(top+'.v')
            assert v.sha(src)==row['source_sha256']
            case=dict(name=top,source_sha256=v.sha(src),roles={});result['cases'].append(case)
            for role in ('baseline','candidate'):
                ilang=inputs/top/role/'postabc.il';assert v.sha(ilang)==row['roles'][role]['ilang_sha256']
                d=out/top/role;d.mkdir(parents=True);audit=d/'audit.json'
                original=ilang.read_bytes();normalized=original.replace(b'\r\n',b'\n')
                if b'\r' in normalized or normalized.replace(b'\n',b'\r\n')!=original:
                    raise RuntimeError('Windows ILANG line-ending conversion is not reversible')
                proof_input=d/'postabc-lf.il';proof_input.write_bytes(normalized)
                with (d/'audit.log').open('w') as log:
                    subprocess.run([m['baseline'],'-Q','-T','-p',f'read_verilog -lib "{model}"; read_rtlil "{proof_input}"; write_json "{audit}"'],env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
                cells=json.loads(audit.read_text())['modules'][top]['cells'];by=Counter(c['type'] for c in cells.values())
                if not by['$lut'] or set(by)-{'$lut','dffeas','$scopeinfo'}:raise RuntimeError('Wrong actual Windows proof stage '+repr(by))
                for c in cells.values():
                    if c['type']=='dffeas':
                        for pin,value in dict(prn='1',aload='0',asdata='0',sclr='0',sload='0').items():
                            if c['connections'].get(pin)!=[value]:raise RuntimeError('Unsupported FF control')
                proof=v.prove(src,top,proof_input,d/'proof',env,m,model)
                case['roles'][role]=dict(ilang_sha256=v.sha(ilang),windows_executable_sha256=row['roles'][role]['executable_sha256'],
                                         normalized_ilang_sha256=v.sha(proof_input),postabc_by_type=dict(by),proof=proof)
                save()
                if proof['status']!='PASS':raise RuntimeError('Windows netlist equivalence failed '+top+' '+role)
                print(top,role,'WINDOWS_ILANG_EQY_PASS',flush=True)
        neg=out/'negative';neg.mkdir();bad=neg/'bad.il'
        bad.write_text('module \\test2\n  wire input 1 \\clk\n  wire input 2 \\a\n  wire input 3 \\b\n  wire input 4 \\c\n  wire input 5 \\d\n  wire width 5 input 6 \\dataa\n  wire width 5 input 7 \\datab\n  wire width 5 input 8 \\datac\n  wire width 5 input 9 \\datad\n  wire width 5 output 10 \\out\n  connect \\out 5\'00000\nend\n')
        proof=v.prove(v.ROOT/'competition_case/test2/test2.v','test2',bad,neg/'proof',env,m,model)
        evidence='\n'.join(p.read_text(errors='replace') for pat in ('logfile.txt','run.log') for p in (neg/'proof/strategies').rglob(pat))
        if proof['status']=='PASS' or not (neg/'proof/FAIL').exists() or not any(s in evidence for s in ('model found: FAIL','model found for base case: FAIL','proof did fail')):
            raise RuntimeError('Negative control lacks a counterexample')
        result['negative_control']=dict(status='EXPECTED_COUNTEREXAMPLE',proof=proof)
        result['status']='PASS';save();print('WINDOWS_ILANG_VALIDATION_PASS',out,flush=True)
    except Exception as e:
        result.update(status='FAIL',error=str(e));save();raise

if __name__=='__main__':main()
