# 赛题二 v12 最终提交包

本目录保存 2026-10-04 整理的独立提交包。压缩包内包含：

- 优化后的 Yosys 0.69 与内置 `yosys-abc`；
- 完整 `share/` 数据和运行库；
- 可从零重建的完整优化版源码；
- 相对原版 Yosys 0.69 的修改补丁；
- 四个测试用例、功能等价验证报告和冒烟测试脚本；
- 官方答疑要求与实现对应说明。

完整性检查：

```bash
sha256sum -c FPGA-Competition-2026-v12-official-submission-2026-10-04.tar.gz.sha256
```

解压和验证：

```bash
tar -xzf FPGA-Competition-2026-v12-official-submission-2026-10-04.tar.gz
cd submission-v12-official-2026-10-04
sha256sum -c SHA256SUMS
python3 tools/smoke_test.py
```

四个用例 LUT 结果为 `286→221`、`25→15`、`12→12`、`35→26`，
逐例缩减率算术平均值约为 `22.11%`，DFF 均未增加。
