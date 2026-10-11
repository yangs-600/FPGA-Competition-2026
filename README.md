# 当前工程：v16 译码控制向量规范化（兼容原 v11 路径）

从仓库根目录运行 `python3 scripts/run_current.py`；激活 `source scripts/activate_competition.sh`。

工作源码、工具链和最新证据在 `clean-v11/`，详细复现和清理记录见 `CLEAN_REPRODUCTION.md`、`cleanup-postcheck.json`。

v16 在 v15 的窄 PMUX 与默认数据专化基础上，规范化同源控制向量的位顺序并同步重排比较常量，使不同拼接位序的等值译码 PMUX 可以共享同一 DAG；文件名仍保留 v11，避免破坏现有构建入口。四个公开用例平均 LUT 缩减 22.11%，8 路正式等价验证及 14 个独立组合逻辑夹具全部通过。详细说明见 `docs/COMPETITION_V16.md`。

评测流程保持 Yosys 0.69、`synth_intel -family cycloneiv` 和内置 ABC9。资源检查同时审计 LUT、`$not`、DFF 及全部已出现的非 LUT 单元类型；正式评测目标是 Windows，仓库内 Linux 复现仅作为交叉验证。
