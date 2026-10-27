# 当前九用例本地构建与验证

本机仓库为 `/home/ubuntu/FPGA/FPGA-Competition-2026`。运行时从入口文件和仓库根目录定位，不再将仓库外 `clean-v11` 当作当前源码目录。

## 使用本机已经验证的工具

```bash
cd /home/ubuntu/FPGA/FPGA-Competition-2026
/usr/bin/python3 -E -B -u scripts/run_current.py
source scripts/activate_competition.sh
```

入口默认检查显式登记的九例、原版/候选 18 项 ABC 后原生 LUT ILANG EQY 和恒零输出负对照，并单独给出面积结论。`--case test2` 只作局部诊断，状态为 `SUBSET_PASS`，不能替代全量验收。Linux 入口不生成 Windows 性能结论。

## 独立目录重建

`scripts/build_current.py` 从保留的 Yosys 0.69 归档建立全新源码树和编译目录，先编译原版，再应用与工作区源码一致的补丁编译候选。默认目录为 `clean-v11/toolchains/yosys-0.69-current`；已有构建计划的输入发生变化时，必须另用 `--work` 新目录，不能混用缓存。原有工具、OSSCAD Suite 和原版 ABC 均保留。

```bash
/usr/bin/python3 -E -B -u scripts/build_current.py --jobs 2
```

需要系统 Python 3.10+、click、Git、Make、GCC/G++、Bison、Flex、pkg-config 及 Tcl/readline/libffi/zlib 开发库。默认保留依赖根为仓库父目录，可用 `--dependencies` 指定；需要的本机归档/工具为：

- `clean-v11/toolchains/yosys-0.69/source.tar.gz` 和对应原版工具 manifest；源码提交 `9f75ca1f9834a39a863915b5dae0c7b1e33533bc`。
- `clean-v11/toolchains/eqy-0.69/source.tar`；EQY v0.69。
- `toolchains/cmake-3.31.6/bin/cmake`，也可通过 `--cmake` 指定。
- OSSCAD Suite 的 SBY 与 `tabbypy3`，默认 `~/oss-cad-suite`，也可通过 `--oss-suite` 指定。

上述保留依赖未纳入 Git。脚本逐一校验归档和保留工具 SHA，缺失时直接报出缺项，不会下载未知版本或删除旧工具。它支持 Python 3.10 的安全解包路径，并使用独立、带哈希的 proof-bin 避免旧 SBY 包装器抢先。当前工作区输入由实际 SHA 绑定；Git HEAD 仅为上下文，不把尚未提交的改动误称已发布。

重建脚本完成后保存新的 `competition-current/manifest.json`、构建日志、18 项形式证明及 `local-build-current-receipt.json`。本轮现用二进制由相同固定 0.69 源码树增量编译；新的独立重建入口已静态检查，未把它宣称为本轮已经完成的全新重编译。

## 运算边界回归

```bash
/usr/bin/python3 -E -B -u scripts/test_pmux_operators.py \
  --candidate clean-v11/toolchains/yosys-0.69/competition-current-v19-mfs2/yosys \
  --arithmetic
```

52 项覆盖 XOR/AND/OR、add/sub 共享操作数、双输入 PMUX、signed、X/default、keep、外部用户、宽度与成本保护；通过 SAT、变换次数和错误输出负对照核验。它们是算法边界回归，不加入官方九例的面积平均值，也不当作性能验收。

Windows 实际网表复证使用 `scripts/verify_windows_current.py --bundle <证据目录>`，保留原始 Windows 字节和 SHA。完整交付包自带运行依赖；Windows 性能测量与 Linux EQY 证据分开保存，当前耗时相对 5% 指标仍有未达标用例。
