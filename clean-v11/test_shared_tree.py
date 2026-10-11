"""Independent fixtures for selector-order search and safe default completion."""
import json,random,re,tempfile
from pathlib import Path
from build_069 import ROOT
from run_competition_v11 import environment,measure,prove,counts

env,m=environment();out=Path(tempfile.mkdtemp(prefix='shared-tree-tests-',dir=ROOT));rows=[]

# The function sel[2] ? sel[0] : sel[1] has a smaller reduced decision DAG
# when selector bit 2 is outermost. This verifies that the integrated v12
# selector-order search is active instead of silently retaining v11 order.
name='selector_order_3';p=out/name;p.mkdir();order=list(range(8));random.Random(913).shuffle(order)
code=f'module {name}(input [2:0] sel,input [7:0] a,b,output reg [7:0] y);\nalways @* begin\ny=8\'h00;\ncase(sel)\n'
for i in order:
    choose_b=((i>>2)&1 and (i>>0)&1) or (not ((i>>2)&1) and (i>>1)&1)
    code+=f"3'd{i}: y={'b' if choose_b else 'a'};\n"
code+='endcase\nend\nendmodule\n';src=p/'input.v';src.write_text(code)
flow=p/'flow.ys';flow.write_text(f'read_verilog {src}\nsynth_intel -family cycloneiv -top {name}\nwrite_json {p}/netlist.json\nwrite_verilog -noattr -norename {p}/netlist.v\n')
measure([m['candidate'],'-Q','-T','-s',str(flow)],p/'synthesis.log',env)
ok=prove(src,name,p/'netlist.v',p/'proof',env);log=(p/'synthesis.log').read_text()
match=re.search(r'PMUX_SHARED_TREE.*order=(\d+)',log)
assert match and match.group(1).startswith('2'),(name,match.group(1) if match else None)
assert ok,name
rows.append(dict(name=name,proof='PASS',tree_triggered=True,selector_order=match.group(1),counts=counts(p/'netlist.json',name)))
print(name,'PASS',match.group(1),flush=True)

# Four explicit codes share b and the other twelve codes use PMUX default a.
# Completing every missing code exposes the compact sel[3:2] == 0 structure.
name='sparse_default_4';p=out/name;p.mkdir()
code=f'module {name}(input [3:0] sel,input [7:0] a,b,output reg [7:0] y);\nalways @* begin\ny=a;\ncase(sel)\n'
for i in [2,0,3,1]: code+=f"4'd{i}: y=b;\n"
code+='endcase\nend\nendmodule\n';src=p/'input.v';src.write_text(code)
flow=p/'flow.ys';flow.write_text(f'read_verilog {src}\nsynth_intel -family cycloneiv -top {name}\nwrite_json {p}/netlist.json\nwrite_verilog -noattr -norename {p}/netlist.v\n')
measure([m['candidate'],'-Q','-T','-s',str(flow)],p/'synthesis.log',env)
ok=prove(src,name,p/'netlist.v',p/'proof',env);log=(p/'synthesis.log').read_text()
trigger='PMUX_SHARED_TREE cells=' in log
assert trigger and ok,name
rows.append(dict(name=name,proof='PASS',tree_triggered=True,missing_codes=12,counts=counts(p/'netlist.json',name)))
print(name,'PASS',trigger,flush=True)

# The default arm directly references a selector bit. Under each missing code
# that bit has a known value and should be cofactored before DAG construction.
name='default_ctrl_specialization';p=out/name;p.mkdir()
code=f'module {name}(input [3:0] sel,input [7:0] b,output reg [7:0] y);\nalways @* begin\ny={{8{{sel[3]}}}};\ncase(sel)\n'
for i in [2,0,3,1]: code+=f"4'd{i}: y=b;\n"
code+='endcase\nend\nendmodule\n';src=p/'input.v';src.write_text(code)
flow=p/'flow.ys';flow.write_text(f'read_verilog {src}\nsynth_intel -family cycloneiv -top {name}\nwrite_json {p}/netlist.json\nwrite_verilog -noattr -norename {p}/netlist.v\n')
measure([m['candidate'],'-Q','-T','-s',str(flow)],p/'synthesis.log',env)
ok=prove(src,name,p/'netlist.v',p/'proof',env);log=(p/'synthesis.log').read_text()
match=re.search(r'specialized_default_bits=(\d+)',log);trigger='PMUX_SHARED_TREE cells=' in log
assert trigger and match and int(match.group(1))>0 and ok,name
rows.append(dict(name=name,proof='PASS',tree_triggered=True,specialized_default_bits=int(match.group(1)),counts=counts(p/'netlist.json',name)))
print(name,'PASS',match.group(1),flush=True)

# Two four-bit PMUX outputs share the same decoder and permuted data leaves.
# v14 skipped widths below eight; v15 must optimize them when the cost gate wins.
name='narrow_shared_4';p=out/name;p.mkdir();bits=3;width=4;arms=1<<bits
code=f'module {name}(input [2:0] sel,input [31:0] data,output reg [3:0] y,z);\nalways @* begin\ny=0;z=0;\ncase(sel)\n'
for i in range(arms):
    base=i*width
    other=(i^1)*width
    code+=f"3'd{i}: begin y=data[{base} +: 4]; z=data[{other} +: 4]; end\n"
code+='endcase\nend\nendmodule\n';src=p/'input.v';src.write_text(code)
candidate_flow=p/'candidate.ys';candidate_flow.write_text(f'read_verilog {src}\nsynth_intel -family cycloneiv -top {name}\nwrite_json {p}/candidate.json\nwrite_verilog -noattr -norename {p}/candidate.v\n')
baseline_flow=p/'baseline.ys';baseline_flow.write_text(f'read_verilog {src}\nsynth_intel -family cycloneiv -top {name}\nwrite_json {p}/baseline.json\n')
measure([m['candidate'],'-Q','-T','-s',str(candidate_flow)],p/'candidate.log',env)
measure([m['baseline'],'-Q','-T','-s',str(baseline_flow)],p/'baseline.log',env)
ok=prove(src,name,p/'candidate.v',p/'proof',env);log=(p/'candidate.log').read_text()
candidate_counts=counts(p/'candidate.json',name);baseline_counts=counts(p/'baseline.json',name)
trigger='PMUX_SHARED_TREE cells=' in log
assert trigger and ok and candidate_counts['logic_cells']<baseline_counts['logic_cells'],name
rows.append(dict(name=name,proof='PASS',tree_triggered=True,baseline_counts=baseline_counts,candidate_counts=candidate_counts))
print(name,'PASS',baseline_counts['logic_cells'],candidate_counts['logic_cells'],flush=True)

# Two narrow PMUX outputs use the same logical selector, but the second equality
# decoder presents its bits as {sel[1],sel[2],sel[0]}. v16 canonicalizes the
# control vector and remaps each comparison constant before grouping the tables.
name='permuted_decoder_sharing';p=out/name;p.mkdir();src=p/'input.v'
code=f'module {name}(input [2:0] sel,input [31:0] data,output reg [3:0] y,z);\nalways @* begin\ny=0;\ncase(sel)\n'
for i in range(8): code+=f"3'd{i}: y=data[{i*4} +: 4];\n"
code+='endcase\nend\nalways @* begin\nz=0;\ncase({sel[1],sel[2],sel[0]})\n'
for i in range(8):
    permuted=((i>>1)&1)*4+((i>>2)&1)*2+(i&1)
    code+=f"3'd{permuted}: z=data[{(i^1)*4} +: 4];\n"
code+='endcase\nend\nendmodule\n';src.write_text(code)
candidate_flow=p/'candidate.ys';candidate_flow.write_text(f'read_verilog {src}\nsynth_intel -family cycloneiv -top {name}\nwrite_json {p}/candidate.json\nwrite_verilog -noattr -norename {p}/candidate.v\n')
baseline_flow=p/'baseline.ys';baseline_flow.write_text(f'read_verilog {src}\nsynth_intel -family cycloneiv -top {name}\nwrite_json {p}/baseline.json\n')
measure([m['candidate'],'-Q','-T','-s',str(candidate_flow)],p/'candidate.log',env)
measure([m['baseline'],'-Q','-T','-s',str(baseline_flow)],p/'baseline.log',env)
ok=prove(src,name,p/'candidate.v',p/'proof',env);log=(p/'candidate.log').read_text()
candidate_counts=counts(p/'candidate.json',name);baseline_counts=counts(p/'baseline.json',name)
trigger='PMUX_SHARED_TREE cells=2' in log
assert trigger and ok and candidate_counts['logic_cells']<baseline_counts['logic_cells'],name
rows.append(dict(name=name,proof='PASS',tree_triggered=True,baseline_counts=baseline_counts,candidate_counts=candidate_counts))
print(name,'PASS',baseline_counts['logic_cells'],candidate_counts['logic_cells'],flush=True)

for bits,missing in [(3,0),(4,0),(5,0),(3,1),(4,1),(5,1),(3,2),(4,2),(5,2)]:
    name=f'decoder_{bits}_missing_{missing}';p=out/name;p.mkdir();arms=1<<bits;width=8
    order=list(range(arms-missing));random.Random(710+bits+missing).shuffle(order)
    code=f'module {name}(input [{bits-1}:0] sel,input [{arms*width-1}:0] data,output reg [7:0] y,z);\nalways @* begin\ny=8\'h59;z=8\'ha6;\ncase(sel)\n'
    for i in order:
        code+=f"{bits}'d{i}: begin y=data[{i*width} +: 8]; z=data[{(i^1)*width} +: 8]; end\n"
    code+='endcase\nend\nendmodule\n';src=p/'input.v';src.write_text(code)
    flow=p/'flow.ys';flow.write_text(f'read_verilog {src}\nsynth_intel -family cycloneiv -top {name}\nwrite_json {p}/netlist.json\nwrite_verilog -noattr -norename {p}/netlist.v\n')
    measure([m['candidate'],'-Q','-T','-s',str(flow)],p/'synthesis.log',env)
    ok=prove(src,name,p/'netlist.v',p/'proof',env)
    log=(p/'synthesis.log').read_text();trigger='PMUX_SHARED_TREE cells=' in log
    # Complete tables must trigger. Sparse random tables may be rejected when
    # completing their defaults would exceed the real explicit-arm cost.
    if missing == 0: assert trigger,(name,trigger)
    assert ok,name
    rows.append(dict(name=name,proof='PASS',tree_triggered=trigger,counts=counts(p/'netlist.json',name)))
    print(name,'PASS',trigger,flush=True)
(ROOT/'shared-tree-tests-latest.json').write_text(json.dumps(dict(status='PASS',directory=str(out),cases=rows),indent=2))
