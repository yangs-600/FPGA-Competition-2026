"""Verify the surviving default project after removing all archived old paths."""
import json,sys,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parent;fresh=ROOT/'clean-v11';sys.path.insert(0,str(fresh))
from run_competition_v11 import environment
env,m=environment()
report=json.loads((fresh/'competition-v11-latest.json').read_text())
assert report['status']=='PASS' and report['all_dff_nonincrease'] and report['all_measured_5pct_pass']
assert report['negative_control']=='EXPECTED_COUNTEREXAMPLE'
previous=json.loads((fresh/'previous-v11-report.json').read_text())
for a,b in zip(previous['cases'],report['cases']):
    for role in ('baseline','candidate'):assert a['roles'][role]['by_type']==b['roles'][role]['by_type']
assert Path('/home/ubuntu/oss-cad-suite/bin/sby').exists()
assert (ROOT/'toolchains/cmake-3.31.6/bin/cmake').exists()
for name in ('yosys-0.63','yosys-0.68','yosys-0.69','eqy-0.69'):assert not (ROOT/'toolchains'/name).exists()
plan=json.loads((ROOT/'cleanup-plan.json').read_text());cleaned=json.loads((ROOT/'cleanup-result.json').read_text())
assert cleaned['status']=='PASS' and len(cleaned['deleted'])==len(plan['targets'])
now=shutil.disk_usage(ROOT)
receipt=dict(status='PASS',clean_root=str(fresh),post_cleanup_report=report['report_dir'],
             average_gain_percent=report['average_gain_percent'],old_target_count=len(plan['targets']),
             bytes_freed=now.free-plan['disk_before']['free'],disk_free=now.free,
             oss_cad_preserved=True,cmake_preserved=True,toolchain=m)
(ROOT/'cleanup-postcheck.json').write_text(json.dumps(receipt,indent=2))
(ROOT/'README.md').write_text('# 当前工程：清洁构建 v11\n\n运行 `python3 run_current.py`；激活 `source ./activate_competition.sh`。\n\n工作源码、工具链和最新证据在 `clean-v11/`，详细复现和清理记录见 `CLEAN_REPRODUCTION.md`、`cleanup-postcheck.json`。\n\n平均 LUT 缩减 22.11%，清理后复测通过。OSSCAD、CMake、原始用例和新工具链均保留。\n',encoding='utf-8')
print(json.dumps({k:v for k,v in receipt.items() if k!='toolchain'}),flush=True)
