# v15 窄 PMUX 共享与默认数据专化

本轮先同步并审计 GitHub `main`，确认远端最新版本为 v14 提交 `c9b5d9c8ec95605c672dd79185b8c5545ca3da83`，再基于该版本继续通用优化。没有引入模块名、路径或公开测试用例特判。

## 开源实现参考

- [Yosys `opt_expr`](https://github.com/YosysHQ/yosys/blob/main/passes/opt/opt_expr.cc) 说明通用优化会做常量折叠和简单表达式重写，但不会利用本 pass 已证明的“特定 PMUX 缺失编码”上下文。本轮因此在共享 DAG 构建前做安全 cofactor，而不是修改全局表达式语义。
- [Yosys FSM 文档](https://github.com/YosysHQ/yosys/blob/main/docs/source/using_yosys/synthesis/fsm.rst) 展示了根据状态/控制赋值计算输出和合并表项的思路；本项目只在互斥等值译码证明成立时应用同类思想。
- [Berkeley ABC](https://github.com/berkeley-abc/abc) 继续作为 Yosys 内置 ABC9 映射器。窄 PMUX 的接受范围按 Cyclone IV 4 输入 LUT 特性限制，避免与 ABC9 的跨位打包发生负交互。

以上只作为语义与算法参考，未复制第三方实现代码。

## v15 变化

1. 取消原先笼统的 `width < 8` 跳过规则，使同一 3 位译码器驱动的窄 PMUX 可以跨输出共享 Shannon DAG。
2. 窄 PMUX 只接受 3 位选择器，因为 3 个选择输入加 1 个数据输入与 Cyclone IV 4-LUT 的输入规模一致；4–6 位窄表继续交给 ABC9。
3. 窄组与宽组分开搜索变量顺序，避免新增窄输出改变 v14 已验证的宽输出最优顺序。
4. 窄组必须满足 `mux_nodes <= 75% * estimate_before` 的额外安全余量；宽组继续沿用 v14 门控。
5. 对缺失编码使用默认输入 `A` 时，若 `A` 的某一位直接引用控制向量位，则按当前编码将其专化为常量，再构建共享 DAG。

开发中曾观察到将 4 位选择器窄 PMUX 与宽输出混合会使 test1 从 221 回退到 224。上述分组和 3 位选择器限制将正式四例恢复到 v14 最佳结果；这一失败尝试没有保留为正式策略。

## 新增回归

- `default_ctrl_specialization`：缺省表中 96 个直接控制位表项被安全专化，EQY PASS。
- `narrow_shared_4`：两个 4 位输出共享同一 3 位完整译码器；原版/候选 Cyclone IV LUT 为 **48 → 32**，降幅 **33.33%**，EQY PASS。
- 既有选择顺序、稀疏默认及 9 个随机完整/缺省夹具继续通过。

独立组合逻辑夹具总数增至 **13**，全部证明 PASS。

## 四个正式用例

| 用例 | LUT | `$not` | DFF | 原版/候选等价 |
|---|---:|---:|---:|---|
| test1 | 286 → 221 | 2 → 2 | 222 → 222 | PASS / PASS |
| test2 | 25 → 15 | 0 → 0 | 0 → 0 | PASS / PASS |
| test3 | 12 → 12 | 1 → 1 | 17 → 12 | PASS / PASS |
| test4 | 35 → 26 | 1 → 1 | 10 → 10 | PASS / PASS |

平均 LUT 降幅为 **22.11038961038961%**；DFF、`$not` 和所有已观察到的其他非 LUT 单元类型均未增加。原版/候选共 8 路 EQY 证明全部 PASS。

一次预热后交错运行 21 次，候选相对原版的 Linux 子进程 CPU 中位数变化为 test1 `-2.61%`、test2 `-1.30%`、test3 `-2.10%`、test4 `-3.09%`。这些仍是 Ubuntu 虚拟机交叉证据，最终以官方 Windows 环境为准。

## 交付状态

可重放补丁仍位于 `clean-v11/toolchains/yosys-0.69/competition-v11/synth-intel-competition.patch`，基于 Yosys 提交 `9f75ca1f9834a39a863915b5dae0c7b1e33533bc`，规范化 SHA-256 为 `3815e43cd31636e8365035401124812bf9ac2bb8b1d959733873c63aacfb5695`，并已通过反向 `git apply --check`。机器可读结果见 `validation/v15/report.json`。
