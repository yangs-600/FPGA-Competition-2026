# 交付与复审指南（2026-10-27）

当前默认版本为 **v21**。Windows 运行包和新增 Linux 形式验证包配套使用；v22 实验及全部原始记录保留，暂不升级默认版。现有结果仍有性能统计口径和答辩材料待确认，不能称赛项全部达标。

## 已交付文件

文件位于 Windows 的 `D:/杨森宇/FPGA/`：

| 文件 | 用途 |
|---|---|
| `FPGA-topic2-v21-Windows-0.69-20261027.zip` | 原冻结 Windows 包：含 Yosys 0.69 原版/候选、统一 ABC 脚本、运行时、九例及测量入口。在 ASCII、无空格目录解压后运行 `run_cases.cmd`。 |
| `FPGA-topic2-v21-EQY-Linux-0.69-20261027.tar.gz` | 新增配套证明包：在 Linux x86_64 / 兼容 WSL2 中，独立复证 Windows 原始 18 份网表及错误输出负对照。携带所需用户态工具和依赖，不需要原 Ubuntu 仓库或 OSS CAD Suite 路径。 |
| `FPGA-topic2-v21-EQY-relocation-evidence-20261027.tar.gz` | Linux 证明包迁移解压后的实际证明记录。 |

| 归档 | 字节数 | SHA-256 |
|---|---:|---|
| Windows ZIP | 91,017,216 | `931c68d5aeac5e8e3acb331c733becc07733958e4c7decb8c728414c496a34c6` |
| Linux EQY tar.gz | 43,472,694 | `1e310f0210e364649be7905e18b7e9ba26b1b81af59ce5002ffd0d0b8b371501` |
| Linux 迁移证明证据 | 4,143,990 | `d4ef4ff10ff0649d4f37b64b696bb5d12e10b46e6526a7eb60710f3e912894ca` |

设计报告为 `docs/FPGA_TOPIC2_DESIGN_V21_DRAFT.pdf`，供审阅算法、成绩和证据链；它仍是草稿，最终字节及摘要以最后交付索引为准。本指南没有修改 PDF 或上述归档。

## 在 Ubuntu / WSL2 复证

使用 Linux x86_64，要求 `/bin/sh`、`/proc`、`/dev/null` 可用，解包位置可写。将 Linux tar.gz 复制到 Linux 用户主目录，在**新的 ASCII、无空格目录**解包；保留原包目录结构和执行权限。以下示例目录若已存在，应另选新目录：

```sh
mkdir "$HOME/fpga-v21-review-20261027"
tar -xzf "$HOME/FPGA-topic2-v21-EQY-Linux-0.69-20261027.tar.gz" -C "$HOME/fpga-v21-review-20261027"
cd "$HOME/fpga-v21-review-20261027/FPGA-topic2-v21-EQY-Linux-0.69-20261027"
./run_verify.sh
```

每轮生成新的 `results/replay-*/`。检查其中 `formal/report.json` 的正证明计数为 `{"PASS":18}`，负对照为 `EXPECTED_COUNTEREXAMPLE`，同时保留生成的 receipt。新增包已经在异于原仓库的全新目录完成这一完整迁移复现；不是仅做版本检查。其归档 SHA 和实际结果见同目录 `.receipt.json`。此入口复证 Windows 网表，不重新综合 Linux 优化版，也不重新测量 Windows 性能。

Ubuntu 长期保存位置已安装并校验为：

```text
/home/ubuntu/FPGA/FPGA-Competition-2026/clean-v11/toolchains/portable-proof-v21-20261027/
```

该目录已保存原 tar.gz 与完整解包根，并通过包内工具、版本和资源摘要预检。可从仓库按相对路径运行：

```sh
cd /home/ubuntu/FPGA/FPGA-Competition-2026
cd clean-v11/toolchains/portable-proof-v21-20261027/FPGA-topic2-v21-EQY-Linux-0.69-20261027
./run_verify.sh
```

## 仍需处理的事项

- v21 九例面积平均下降 20.0619045293%，只比 20% 多 0.0619045293 个百分点；现有九例通过不保证新增用例或另一台机器通过。
- Windows 的既定复核解释采用“首轮触发后，另加五次均值”，但 FAQ 没有明确首轮是否包含在五次内。v21 test1 首轮为 +127.518916%；v22 首轮仍为 +117.388848%，追加五次为 -0.673505%，包含首轮的六次均值则为 +19.706595%。不利数据均保留，仍需澄清官方口径，不能用复核结果宣称所有原始样本通过。
- v22 已通过两条 18 项形式证明和边界测试，但未证明明显 CPU 收益，也未解决首轮迟滞，因此不替换默认 v21。一次独立诊断只能缩小至进程创建/首条日志前及 ABC 调用区间，尚不能确定具体系统原因。详情见 `OPTIMIZATION_FOLLOWUP_20261027.md`。
- 按三名队员的真实贡献补齐分工、实现说明、复现操作和答辩材料，复核赛题及最新答疑中的最终提交要求。设计草稿和形式证明包都不能替代这些工作。
