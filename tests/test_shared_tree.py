"""Independent combinational fixtures for complete and incomplete decoder trees."""
import json,random,tempfile
from pathlib import Path
from build_069 import ROOT
from run_competition_v11 import environment,measure,prove,counts

env,m=environment();out=Path(tempfile.mkdtemp(prefix='shared-tree-tests-',dir=ROOT));rows=[]
for bits,incomplete in [(3,False),(4,False),(5,False),(3,True),(4,True),(5,True)]:
    name=f'decoder_{bits}_{int(incomplete)}';p=out/name;p.mkdir();arms=1<<bits;width=8
    order=list(range(arms-int(incomplete)));random.Random(710+bits).shuffle(order)
    code=f'module {name}(input [{bits-1}:0] sel,input [{arms*width-1}:0] data,output reg [7:0] y,z);\nalways @* begin\ny=8\'h59;z=8\'ha6;\ncase(sel)\n'
    for i in order:
        code+=f"{bits}'d{i}: begin y=data[{i*width} +: 8]; z=data[{(i^1)*width} +: 8]; end\n"
    code+='endcase\nend\nendmodule\n';src=p/'input.v';src.write_text(code)
    flow=p/'flow.ys';flow.write_text(f'read_verilog {src}\nsynth_intel -family cycloneiv -top {name}\nwrite_json {p}/netlist.json\nwrite_verilog -noattr -norename {p}/netlist.v\n')
    measure([m['candidate'],'-Q','-T','-s',str(flow)],p/'synthesis.log',env)
    ok=prove(src,name,p/'netlist.v',p/'proof',env)
    log=(p/'synthesis.log').read_text();trigger='PMUX_SHARED_TREE cells=' in log
    # Complete XOR-permuted tables must exercise sharing. Incomplete tables must skip it.
    assert trigger != incomplete,(name,trigger)
    assert ok,name
    rows.append(dict(name=name,proof='PASS',tree_triggered=trigger,counts=counts(p/'netlist.json',name)))
    print(name,'PASS',trigger,flush=True)
(ROOT/'shared-tree-tests-latest.json').write_text(json.dumps(dict(status='PASS',directory=str(out),cases=rows),indent=2))
