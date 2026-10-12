# v14 稀疏 PMUX 默认分支优化

本轮保持 Yosys 0.69、Cyclone IV、内置 ABC9 和现有 v13 算法不变，重点解决 v13 只允许一个缺失编码、无法优化稀疏 `case` 表的问题。实现不包含模块名、文件名或公开用例特判。

## GitHub 调研与采用原则

- Yosys 官方 `$pmux` 语义规定：所有选择信号为 0 时输出 `A`，恰有一个选择信号为 1 时输出相应 `B` 分支；多个选择信号同时为 1 时结果未定义。因此，在本 pass 已证明所有选择信号都是同一控制向量的不同等值比较后，未列出的编码必然安全地选择 `A`。
- Yosys 官方优化流程强调在通用优化中组合清理、合并、mux-tree 与共享逻辑等 pass。v14 仍嵌入 `synth_intel`，不依赖外部脚本猜测网表结构。
- 参考开源项目 `plex1/aig-opt` 的通用思路：枚举变量顺序、以 DAG 节点数衡量候选结构、只有成本更优时替换并用等价验证兜底。本项目仅采用这些算法原则；未复制其 LGPL 源码。

参考链接：

- https://github.com/YosysHQ/yosys/blob/main/docs/source/cell/word_mux.rst?plain=true
- https://yosyshq.readthedocs.io/projects/yosys/en/stable/using_yosys/synthesis/opt.html
- https://github.com/plex1/aig-opt

## 修复与算法变化

- 只接受 3–6 位、同一控制向量、互不重复的等值译码分支；不满足证明条件的 PMUX 原样保留。
- 对任意未显式列出的编码填入 PMUX 的 `A` 输入，而不再限于只缺一个编码。
- 成本门控改为按原 PMUX 的真实显式分支数估算，避免用补全后的 `2^N` 分支数虚增“原成本”而接受负收益替换。
- 保留 v13 的选择位全排列搜索、跨输出共享 Shannon DAG、`keep` 属性保护和“不修改顺序单元”约束。
- 修复验证入口对 `manifest.json` 的硬依赖：正式清单存在时仍执行原有哈希校验；清单缺失时，只有完整 baseline/candidate/ABC/EQY、准确的 Yosys/EQY 0.69 版本、正确源码提交和 v14 内置 pass 全部验证通过，才接受已重建工具链。该路径不创建或伪造清单文件。
- 修正根目录代理脚本的错误相对路径和激活脚本中写死的 `/home/ubuntu/FPGA`，使不同用户名和安装目录都能从 `scripts/` 入口运行。

专用稀疏夹具只有 4 个显式分支、12 个编码走默认输入；v14 将其识别为可压缩结构并通过 EQY。9 个随机完整/缺省表也全部证明通过，其中成本不足的候选按门控安全跳过。选择顺序夹具继续得到 `order=201`，共享 mux 节点估算为 `48 → 24`。

## 2026-10-08 回归结果

| 用例 | LUT | `$not` | DFF | 原版/候选等价 |
|---|---:|---:|---:|---|
| test1 | 286 → 221 | 2 → 2 | 222 → 222 | PASS / PASS |
| test2 | 25 → 15 | 0 → 0 | 0 → 0 | PASS / PASS |
| test3 | 12 → 12 | 1 → 1 | 17 → 12 | PASS / PASS |
| test4 | 35 → 26 | 1 → 1 | 10 → 10 | PASS / PASS |

逐用例 LUT 缩减率算术平均值为 **22.11038961038961%**。8 路正式 EQY 证明和 11 个独立组合逻辑夹具全部 PASS；四例中的 `$not`、DFF 和所有已出现的非 LUT 单元类型均未增加。

一次预热后，原版/候选版交错运行 21 次并取 Linux 子进程 CPU 中位数，候选相对原版的变化依次为 test1 `-1.96%`、test2 `-1.36%`、test3 `-1.87%`、test4 `-4.90%`。这只是当前虚拟机交叉检查，最终仍以官方 Windows 运行与计时为准。

可重放补丁位于 `clean-v11/toolchains/yosys-0.69/competition-v11/synth-intel-competition.patch`，基于 Yosys 提交 `9f75ca1f9834a39a863915b5dae0c7b1e33533bc`，仓库规范化内容的 SHA-256 为 `dc6cf742985d96844f16f01e4edf8b41260e496352b105aa0ce5c2f72e9631b3`，并已通过反向 `git apply --check`。

## 2026-10-12 官方口径和 Windows 验收

按照问题汇总 C25/C67，应计入独立 NOT 后对四例减少率取算术平均：正式平均为 21.89236111%，LUT 单项 22.11038961% 仅作辅助。四例 Windows 每例 21 轮 CPU/主进程峰值工作集增量均不超过 5%，实际输出的 ABC9 后原生 LUT ILANG 八次 EQY 均 PASS，负对照检出明确反例。完整证据和复测方法见 [Windows 验收记录](WINDOWS_V14_VALIDATION.md)。
