# 赛题二：Yosys 0.69 PMUX 优化 v24

当前源码为 `v24-bounded-search`。在原版 Yosys 0.69 内加入通用 PMUX 优化，在 `synth_intel -family cycloneiv` 中调用；九例统一使用同一份 ABC9 脚本。源码 SHA-256：`f278dfa15309f735644eb09dbcb1e385f99cb6e571912b68d9d679917d4d5b12`。

2026-10-27 已完成 WSL 最终交付材料的全新目录离线构建演练、新产物一次固定性能测量和18项新网表 EQY。九例 LUT＋NOT 缩减率的算术平均为 **20.661033%**，逐例逻辑资源均不增加。原有82项边界检查及3个负对照属于同源码的早先工具验证，本轮没有冒充重新执行。

本轮 test1 墙钟减少 **0.895694%**。test2 首轮根内存增加 **5.390248%**；按短例追加五次复核后，墙钟增加 **2.917401%**、根内存增加 **0.190369%**。包含首轮的五次/六次口径也均在5%以内。其余八例首轮墙钟与根内存在5%以内。严格首轮九例并非全部通过，现场成绩和正式复核认定仍以主办方评测为准。CPU口径单列在结果表，不与墙钟混用；原生Windows首次迟滞问题未被这次WSL验证修复。

## 队友从这里开始

1. 阅读 [WSL交付说明](docs/README_V24_WSL.md) 和 [现场操作步骤](docs/ONSITE_RUNBOOK.md)。
2. 从队内交付附件获取 `FPGA-topic2-v24-WSL-onsite-kit-20261027.zip`。源码仓库不包含大型二进制附件；该一体包带原运行/构建材料、EQY工具包、现场辅助入口及完整新证据。文件指纹见交付清单和包外 `.sha256`，不要仅下载本仓库后假设工具已安装。
3. 使用 WSL Ubuntu 24.04 x86_64、GCC/G++13、Python3.12及已列出的基础系统工具，照步骤核验、编译、测量、证明。新的输出目录不得复用历史结果。

现场新增脚本也保存在 `scripts/wsl/`：`stage_rebuilt_measurement.py` 接收 `--package --build-root --output`，加 `--run` 才运行固定测量；`onsite_proof.py` 接收 `--package --proof-kit --roles-root --build-receipt --output`。它们验证外部工具包和新构建收据，不能省略依赖。

## 已有 Ubuntu 仓库入口

本机已经部署工具的仓库仍可执行：

```bash
/usr/bin/python3 -E -B -u scripts/run_current.py
```

此入口进行九例功能/资源验证，单独的效率测量按上面的WSL步骤执行。新机器的工具重建见 [原有Linux构建说明](docs/LOCAL_BUILD.md)。旧Windows及原生Ubuntu记录保留在 [原v24说明](docs/README_NATIVE_V24_20261027.md)，不能将它们与WSL成绩合并。

## 源码、结果与材料

- 实现：`src/pmux_competition_v11.cc`，兼容镜像：`clean-v11/pmux_competition_v11.cc`。
- 集成补丁：`clean-v11/toolchains/yosys-0.69/competition-v11/synth-intel-competition.patch`。
- 固定脚本：`abc/competition_abc_dch.abc`；九例注册表：`cases_current.json`。
- [完整结果与两轮WSL对比](docs/RESULTS_V24_WSL.md)、[技术设计报告](docs/DESIGN_REPORT_V24_WSL.md)、[答辩说明](docs/DEFENSE_NOTES_V24_WSL.md)、[交付清单](docs/DELIVERY_CHECKLIST.md)。
- 本轮摘要：`validation/wsl-v24-onsite-20261027/`。原始样本、失败记录及完整证明在配套证据归档中保留。

技术材料已据实更新；三位队员真实分工按用户要求暂跳过。本文不宣称已经完成主办方验收或现场答辩。
