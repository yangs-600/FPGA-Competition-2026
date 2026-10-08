# 当前工程：v14 稀疏 PMUX 优化（兼容原 v11 路径）

从仓库根目录运行 `python3 scripts/run_current.py`；激活 `source scripts/activate_competition.sh`。

工作源码、工具链和最新证据在 `clean-v11/`，详细复现和清理记录见 `CLEAN_REPRODUCTION.md`、`cleanup-postcheck.json`。

v14 在 v13 的选择位顺序搜索基础上，把 PMUX 默认输入安全补齐从“恰好缺一个编码”扩展到任意数量的缺失编码，并改用真实显式分支数进行收益门控；文件名仍保留 v11，避免破坏现有构建入口。四个公开用例平均 LUT 缩减 22.11%，8 路正式等价验证及 11 个独立组合逻辑夹具全部通过。详细说明见 `docs/COMPETITION_V14.md`。

评测流程保持 Yosys 0.69、`synth_intel -family cycloneiv` 和内置 ABC9。资源检查同时审计 LUT、`$not`、DFF 及全部已出现的非 LUT 单元类型；正式评测目标是 Windows，仓库内 Linux 复现仅作为交叉验证。
