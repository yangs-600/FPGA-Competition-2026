# 当前工程：v16 译码控制向量规范化（兼容原 v11 路径）

从仓库根目录运行 `python3 scripts/run_current.py`；激活 `source scripts/activate_competition.sh`。

工作源码、工具链和最新证据在 `clean-v11/`，详细复现和清理记录见 `CLEAN_REPRODUCTION.md`、`cleanup-postcheck.json`。

v16 在 v15 的窄 PMUX 与默认数据专化基础上，规范化同源控制向量的位顺序并同步重排比较常量，使不同拼接位序的等值译码 PMUX 可以共享同一 DAG；文件名仍保留 v11，避免破坏现有构建入口。四个公开用例按 LUT＋NOT 计的逻辑资源平均减少 21.8924%（LUT 单项平均 22.1104%），8 路正式等价验证及 14 个独立组合逻辑夹具全部通过。详细说明见 `docs/COMPETITION_V16.md`。

评测流程保持 Yosys 0.69、`synth_intel -family cycloneiv` 和内置 ABC9。资源检查同时审计 LUT、`$not`、DFF 及全部已出现的非 LUT 单元类型；正式评测目标是 Windows，仓库内 Linux 复现仅作为交叉验证。

本机 v14 从保留依赖重新构建的历史入口是 `scripts/build_current.py`，方法和验证摘要见 [docs/LOCAL_BUILD.md](docs/LOCAL_BUILD.md)。该脚本仍严格检查 v14 与 11 个夹具；当前仓库源码为 v16，不能直接把历史构建脚本或保留的 v14 二进制当作 v16 构建结果。

2026-10-12 已完成的是 **v14** 四例 Windows 构建、21 轮 CPU/主进程峰值工作集验收，以及 Windows 实际 ABC9 后 ILANG 八次 EQY 证明和负对照。见 [Windows 验收记录](docs/WINDOWS_V14_VALIDATION.md)。该验收包对应源码提交 `c9b5d9c8ec95605c672dd79185b8c5545ca3da83`；此证据不覆盖 v16。
