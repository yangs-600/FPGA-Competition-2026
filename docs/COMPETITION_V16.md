# v16 译码控制向量规范化

本轮从 GitHub `main` 的 v15 提交 `3c3e316f960146979769fc1de681228892fa5178` 继续优化。目标是处理同一组控制信号被 Verilog 拼接成不同位序时，等值译码表不能进入同一共享组的问题；没有加入模块名、文件路径或公开用例特判。

## 算法变化

对 3–6 位、所有位均为不同导线的 `$eq` 译码器，v16 在记录译码表前执行以下规范化：

1. 按导线名和位偏移为控制位建立稳定顺序；
2. 将比较常量的每一位同步移动到新的位置；
3. 使用规范化后的控制向量和编码执行完整性检查、分组与共享 Shannon DAG 构建。

因此，`sel == K` 与 `{sel[1], sel[2], sel[0]} == K'` 在 `K'` 正确对应同一逻辑编码时，可以共享 DAG。规则仍要求比较宽度一致、常量完全已知、控制位互不重复；不能证明安全的结构保持原样。

实现继续建立在 [Yosys RTLIL 与优化流程](https://github.com/YosysHQ/yosys)、[Yosys PMUX 语义](https://github.com/YosysHQ/yosys/blob/main/docs/source/cell/word_mux.rst?plain=true) 和 [Berkeley ABC](https://github.com/berkeley-abc/abc) 上。上述项目是工具链或语义参考，本轮未复制第三方实现代码。

## 新增回归

新增 `permuted_decoder_sharing`：两个 4 位 PMUX 输出使用同一组三位控制信号，但第二个译码器写成 `{sel[1], sel[2], sel[0]}`。结果为：

- 原版/候选 Cyclone IV LUT：**48 → 32**，下降 **33.33%**；
- 日志确认两个 PMUX 进入同一共享组；
- EQY：**PASS**。

包括 v12–v15 既有夹具在内，共 **14** 个组合逻辑夹具全部通过形式等价验证。

## 四个正式用例

| 用例 | LUT | `$not` | DFF | 原版/候选 EQY |
|---|---:|---:|---:|---|
| test1 | 286 → 221 | 2 → 2 | 222 → 222 | PASS / PASS |
| test2 | 25 → 15 | 0 → 0 | 0 → 0 | PASS / PASS |
| test3 | 12 → 12 | 1 → 1 | 17 → 12 | PASS / PASS |
| test4 | 35 → 26 | 1 → 1 | 10 → 10 | PASS / PASS |

正式四例保持 v15 最佳结果，平均 LUT 降幅 **22.11038961038961%**，DFF 和其他已观察单元类型均未增加，原版/候选共 8 路 EQY 证明全部 PASS。

一次预热后交错运行 21 次，候选相对原版的 Linux 子进程 CPU 中位数变化为 test1 `-1.11%`、test2 `-3.31%`、test3 `-3.20%`、test4 `-5.21%`。这些数据是 Ubuntu 虚拟机交叉证据，不替代官方 Windows 验收。

## 交付状态

集成补丁位于 `clean-v11/toolchains/yosys-0.69/competition-v11/synth-intel-competition.patch`，基于 Yosys `9f75ca1f9834a39a863915b5dae0c7b1e33533bc`，SHA-256 为 `066e74121b86fb682988a1d3042d2187833b8c34d3b9d66fec0334d79d3106d1`，并已通过反向补丁检查。机器可读结果见 `validation/v16/report.json`。
