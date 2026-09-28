# 四用例优化 v11：共享译码选择树

2026-09-27。已将当前默认入口切换到 v11，v9 源码、二进制、报告和审阅包保留。原始四个测试用例未修改。

## 本轮结果

Yosys 与 EQY 均锁定准确 0.69；使用 synth_intel / Cyclone IV。四例的基线、候选分别对原始 RTL 的 8 路证明全部通过，错误输出负对照检出真实反例。新增 6 个通用组合逻辑测试（8/16/32 路选择、打乱分支顺序、完整和不完整译码）也全部通过；完整译码触发共享树，不完整译码跳过。

| 用例 | 原版 LUT | v9 LUT | v11 LUT | 原版 DFF | v11 DFF |
|---|---:|---:|---:|---:|---:|
| test1 | 286 | 286 | 221 | 222 | 222 |
| test2 | 25 | 15 | 15 | 0 | 0 |
| test3 | 12 | 12 | 12 | 17 | 12 |
| test4 | 35 | 26 | 26 | 10 | 10 |

四例 LUT 缩减率的算术平均从 **16.43% 提升到 22.11%**，提升约 5.68 个百分点。test1 缩减 22.73%；test3 的 LUT 仍无收益。这里计数为 cycloneiv_lcell_comb，DFF 独立约束，未宣称物理 LE 面积或官方最终得分。

## 算法及边界

保留 v9 的选择条件常量传播与固定 ABC9 面积映射脚本。在此基础上，对由同一组 3–6 位独立信号完整译码的 PMUX，建立低位选择信号位于外层的 Shannon 分解树。对 `(选择位、低分支、高分支)` 进行模块内哈希复用，使不同输出可以共享相同子树。叶子相同的分支直接折叠。

只处理数据宽度至少 8 位、8–64 路、所有编码恰好覆盖一次且比较位宽一致的完整译码，保留 keep 属性，不修改顺序逻辑单元。不完整译码或无法证明覆盖关系时跳过。所有输出候选的共享二选一节点数不高于 AND/OR LUT 估算时才提交；这是结构启发式，并非任意电路面积不退化的数学保证。

没有按 test1 等文件名或模块名识别用例，也没有在运行时执行多次综合择优。最初的 PMUX 移位/普通树形转换让 test1 增至 367/335 LUT，已拒绝；映射参数实验也没有提供更好的整体结果。最终采用共享树，test1 的 264 个树节点经标准映射形成 221 个总 LUT。固定策略的全部探索摘要保存在 explore-v10-latest.json、mapping-v10-latest.json。

源码为 pmux_competition_v11.cc，补丁位于 toolchains/yosys-0.69/competition-v11/synth-intel-competition.patch，已在准确 0.69 源码上通过 git apply --check。构建、验证都使用独立 v11 清单，未覆盖 v9 证明。实际测试报告目录：`competition-v11-0uwy1zis`。

## 性能证据

每路预热一次，21 次交替测量；CPU 采用含被等待 ABC 子进程的 wait4 user+system 中位数；ru_maxrss 采用各路测得的最大高水位。

| 用例 | CPU 增幅 | ru_maxrss 增幅 | 进程树 PSS 采样峰值增幅 |
|---|---:|---:|---:|
| test1 | -9.67% | -2.83% | -3.12% |
| test2 | -1.41% | 0.97% | 1.34% |
| test3 | -1.06% | -0.95% | -0.20% |
| test4 | -3.86% | 0.47% | 2.61% |

当前这些测量的各例增幅均低于 5%。PSS 通过 /proc/*/smaps_rollup 分摊共享驻留页，减少 RSS 在 fork 时重复计入页面的影响；21 次完整原始采样保存在 competition-v11-tree-pss.json。不过采样不是精确内核进程组峰值，各进程读数也不是同一时刻的原子快照，短峰值可能遗漏。

v9 的旧 RSS 初测 test2 +12.82% 仍保留，不能用 PSS 重测覆盖或声称旧异常已被确证解释。官方到底使用 ru_maxrss、进程树 RSS/PSS 还是 cgroup memory.peak 尚未核对。因此这些结果支持性能目标，但不等于官方全过程内存约束的最终认证。

## 运行与交付

Ubuntu 当前工程已构建完成：

```bash
cd ~/FPGA
python3 run_current.py
python3 test_shared_tree.py
python3 measure_competition_v11_pss.py
source ./activate_competition.sh
yosys -V
```

run_current.py 固定调用 run_competition_v11.py，每次新建证据目录、校验源码/程序/ABC/EQY 哈希及四例原始文件哈希，强制检查每份证明日志的 Yosys 0.69 版本。当前终端激活脚本也指向 v11。重建用 python3 build_competition_v11.py；旧 v9 可显式运行 run_competition.py 和 activate_competition_v9.sh。

交付包包含最终源码、补丁、固定源码归档、网表、正向证明、负对照、6 个边界测试、性能原始样本和逐文件哈希。它是审阅/复现实验材料，不是免依赖安装包；没有声称已在另一台清洁机器完成构建。此前 EQY 误用旧引擎的历史更正、限制过的 DFFE 功能模型以及 test2 敏感列表问题，仍按 COMPETITION_V9.md 的说明适用。

剩余验收事项：获得并核对官方计数/内存脚本；在清洁构建环境完成复现；按官方模板整理提交文档与答辩材料。当前平均 LUT 缩减已超过 20%，但不能仅凭这个数字宣布全部赛项要求完成。
