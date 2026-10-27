# v21 PMUX 优化与九用例验收记录（2026-10-27）

v21-fast 的现有九例功能、面积及本轮 Windows 相对效率检查通过：`LUT + NOT` 的逐例降幅算术平均为 **20.06190452929184%**，单例逻辑资源均未增加；按既定测量/复核规则选定的正式值，九例墙钟及内存增幅均不超过 5%，正式判定没有一例超过 15%。Linux 18 项 EQY、实际 Windows 18 项 EQY、52 项运算边界 SAT、6 项快速退出 SAT 及各组错误输出负对照均通过。

本记录只覆盖清单中的九例和本轮环境。面积超过 20% 的余量为 **0.06190452929184 个百分点**，没有为未来用例或现场表现预留充分裕量；现有通过不能作为任意电路或另一台机器的保证。Ubuntu 稳定 manifest 切换后的默认入口复验及最终便携包验收状态见文末，尚未完成的项目不计为已通过。

## 算法变化及实现边界

Yosys 源码基线固定为 0.69、提交 `9f75ca1f9834a39a863915b5dae0c7b1e33533bc`。v21 保留已有的译码条件替换、PMUX 共享树、公共 XOR/AND/OR 操作数提取及保守 add/sub 共享；不改变触发器。新增工作主要减少已有算法的无效开销：

1. 模块没有选中且未设置 keep 的 mux/pmux 时，在建立 SigMap 前跳过；facts 为空时跳过后续工作；完成条件替换后，没有可用 decode 或 PMUX 时跳过重型阶段。最后一项严格放在条件替换之后，宽于六位的译码条件仍可替换数据，test3 的 16 位条件替换已专门检查。
2. 共享树的 target→bit→code 整数列只建立一次，保留原叶子注册顺序。用已选择高位的整数 code 代替递归中的 active_codes/lo/hi 临时向量，仍按低分支、高分支、父节点的顺序建立图。

整数模型对照核对了叶编号、内部图 tuple 和首次最优顺序；独立审查另有更多结构对照。`NEW_ID` 包含源码行号，修改源码行会改变对象名称，所以没有把整数图对照解释为实际 ILANG 字节不变。新候选实际输出通过新的形式证明，面积也重新统计。

九例统一固定 ABC 脚本：

```text
&dch -f; &if -K 4 -a -C 4 -F 7 -A 1
```

完整流程为 `synth_intel -family cycloneiv`，新 pass 编入 Yosys 并在该流程内调用。脚本不按用例、规模、名字或结构切换；没有修改其他优化 pass 或 ABC 源码来抵消耗时。

## 统计与测量口径

输入为 `cases_current.json` 登记的原四例和 ZIP 新增五例，九份 RTL 原始字节保持不变。每例面积降幅为 `(原版 LUT+NOT − 候选 LUT+NOT) / (原版 LUT+NOT) × 100%`，然后对九个百分比等权平均。DFF 与总 cell 数另记，不混入该逻辑面积指标。

Windows 测量每例先运行原版十次预热，再按原版→候选顺序测量。首轮原版不足一秒且候选墙钟或内存增加超过 5% 时，追加五对原版→候选，使用这五次两角色均值之比判定；首轮单独保留，不参与该复核均值。此处是对答疑未明确细节所采用并公开的固定解释。完整墙钟涵盖 Yosys 启动、综合及等待 ABC 完成；内存取同次综合的根 `yosys.exe` 峰值工作集，不包含 ABC 的内存。CPU 时间只作辅助记录。

| 用例 | 原版逻辑 | v21 逻辑 | 下降比例 | 正式墙钟变化 | 正式峰值内存变化 | 选定样本 | 时间和内存 ≤5% |
|---|---:|---:|---:|---:|---:|---|---|
| test1 | 288 | 227 | 21.180556% | -0.350998% | -1.161697% | 追加五对均值 | 通过 |
| test2 | 25 | 15 | 40.000000% | -2.643562% | -0.025484% | 首轮 | 通过 |
| test3 | 13 | 13 | 0.000000% | -3.108560% | -0.738294% | 追加五对均值 | 通过 |
| test4 | 36 | 27 | 25.000000% | -4.268916% | -1.819499% | 追加五对均值 | 通过 |
| pmux_case01_balanced | 426 | 356 | 16.431925% | -2.143691% | -1.540226% | 首轮 | 通过 |
| pmux_case02_pipeline | 450 | 348 | 22.666667% | -2.895130% | -3.544385% | 首轮 | 通过 |
| pmux_case03_crossbar | 408 | 285 | 30.147059% | -13.022651% | -9.445178% | 首轮 | 通过 |
| pmux_case04_feedback | 368 | 337 | 8.423913% | -2.954609% | +0.264364% | 首轮 | 通过 |
| pmux_case05_nested | 413 | 344 | 16.707022% | -1.512720% | -2.900213% | 首轮 | 通过 |

表中负值表示减少。正式判定的九例时间、内存均满足 5% 口径，零例超过 15%；这不是“全部原始样本均在 5% 内”的结论。test1 首轮原版为 **0.2973620 秒**、候选为 **0.6765548 秒**，首轮变化 **+127.518916%**；按上述固定小例规则追加五对后，原版均值为 **0.30770016 秒**、候选均值为 **0.30662014 秒**，正式变化 **-0.350998%**。首轮异常及所有追加样本原样保留，不能将其删除或隐去。

候选全部正式/复核测量样本（含未进入复核均值的首轮）的最大墙钟为 **0.6765548 秒**，根进程峰值工作集最大为 **24,612,864 字节**。所测九例满足 60 秒/2 GB 绝对限值。九例输出总 cell 最大为原版 test1 的 **510**；这不能推导任意“≤1000 节点”输入均满足限值，也不解决主办方节点定义与网表 cell 口径的差异。

## 形式证明与证据绑定

Linux 私有 v21 工具链的九例原版/候选共 **18/18 EQY PASS**，test2 恒零错误输出负对照检出确切反例。相同 Linux 候选的 **52 项运算边界**和 **6 项快速退出边界** SAT 全部通过，每组错误输出负对照均检出反例。快速退出回归包括无 mux、无 facts、只有 mux、宽译码器条件替换等情形。

Windows 本次完整综合导出的 **18 份实际 post-ABC 原生 LUT ILANG**已逐份由固定 Linux EQY 工具链证明通过，另有错误输出负对照。Windows 原始性能报告保留 `MEASUREMENTS_PASS_FORMAL_PENDING` 和 `formal_status=PENDING`；新形式报告通过其原始报告、Windows manifest、PE 程序及 ILANG 的摘要建立绑定，不回写历史性能报告状态。

下列文件已经本地读取并重新计算摘要，形式报告的 PASS 数及负对照也已读取核对：

| 对象 | SHA-256 |
|---|---|
| Windows 原始 `latest-current.json` | `a2d12cfe60767e44bbbb8d025bea74a1b14f7811e6e45d4ff085874b8a31f7c8` |
| Windows `manifest.json` | `70e06917b35a15e183d6c4ba13c53e5b2cfef10d02933e2c60c8329ebc06e120` |
| Windows 候选 `yosys.exe` | `17508a2d928a97eba82086f0068a5d1b8e1d2bff2d454d6da23b210648f52a99` |
| Linux 私有形式报告 `v21-formal-report.json` | `de6a71f40fdb97b0288c667850d572fa86cb75d58dc8e4c20a39044e5a9618d6` |
| 实际 Windows 形式报告 `actual-windows-v21-report.json` | `f7fd0e3aab8d5f45b5458802e5957ab847018cf6bdc5f924a488852886038dde` |
| 52 项运算边界报告 | `1a6d7c569f0e9d49198f50038f80ecd8fcae194d344385fb5125fc579b7a9c10` |
| 6 项快速退出边界报告 | `03250b0d2ca5c46eaf2069b80822d12f8da3169c078d64e98ac7f5dfbc9f9271` |
| `current-v21-all-proofs-20261027.zip`（9,990,369 字节） | `bd1b939b9db419d883480fe58d33b0e3edeac78eb149b171bdc0015a71b8c6f8` |

实现绑定如下。Linux 可执行文件摘要来自已核验的形式报告所记录的工具身份，源码、脚本与 patch 同时由两平台 manifest 绑定；不能用另一候选的性能或网表替换这些对象。

| 对象 | SHA-256 |
|---|---|
| Linux 候选 `yosys` | `011e1142ef3bb909d2ece4ce66e4b32e934016e541ad1d7543b36053a6eac0ea` |
| v21 纯 LF PMUX 源码 | `0231002c240a080e7eebe1734b9dab49f2db78159c38a68769c885599eb43678` |
| 统一 ABC 脚本 | `bb92697ba7adcd8f97827885daaf8ef501d49d79428b54e51122fbffc45c5fa7` |
| 匹配集成 patch | `fa6123b1ef9ea137576cd8e24333d6ae842642d7252a01aa603ace4429836ee8` |

Windows 工作目录为 `D:/fpga-current-optimization-20261027/windows-v21-fast/`，报告与网表位于其 `validation-current-0r4u0d7f/`。Linux 私有工具位于 `clean-v11/toolchains/yosys-0.69/competition-current-v21-fast/`。文档中的本机路径是证据位置，不是提交包的运行依赖。

## 复现、构建与部署状态

在仓库根目录使用相对入口：

```bash
/usr/bin/python3 -E -B -u scripts/run_current.py
source scripts/activate_competition.sh
yosys -V
```

默认验证入口与激活脚本读取 `clean-v11/toolchains/yosys-0.69/competition-current/manifest.json`。独立构建使用 `scripts/build_current.py`，依赖和参数见 `docs/LOCAL_BUILD.md`；应选择新的 `--work`，按实际输入 SHA 重建并保留原工具。构建器的 Linux 证明不等同于 Windows 性能验收。

**本轮 Linux/Windows v21 工具均基于保留的匹配 Yosys 0.69 对象增量编译。** 已重新综合九例并验证输出，但没有把增量编译称为完整清洁重建，也没有声称清空操作系统页缓存。

| 部署/交付项目 | 当前记录 |
|---|---|
| v21 私有 Linux 18 项 EQY 及负对照 | 已通过，报告摘要见上表 |
| 实际 Windows 18 项 EQY 及负对照 | 已通过，报告摘要见上表 |
| 稳定 current manifest 切换后默认入口 18 项复验 | 见 `validation/current-v21-20261027/summary.json` 中 `linux_deployed_formal`，与私有证明分开记录 |
| 部署后的 current manifest SHA、复验报告路径/SHA | 见 `validation/current-v21-20261027/summary.json` |
| 新 Windows 完整包 | 目标 `D:/杨森宇/FPGA/FPGA-topic2-v21-Windows-0.69-20261027.zip`，生成记录由外层 `.sha256.json` 绑定 |
| 新包迁移解压及包内相对入口 18 次完整综合 | 见 ZIP 外层 `.portable-smoke.json`，从最终 ZIP 全新解压后验证 |
| 最终 ZIP SHA | 在外层 sidecar/交付索引记录，不将含该 ZIP SHA 的记录重新放回同一 ZIP |
| Git 上下文 | HEAD `2791affaa80b9bdf637cae5f60511056aec6d8ab`；本轮未 commit、未 push |

Windows 包须携带 Python、DLL、share、九例及测量/证明脚本，在 ASCII 路径解压后由包根 `run_cases.cmd` 运行。v19/v20 私有工具、原始不利测量、形式报告、旧 ZIP 及 sidecar 保留；历史文档不改写为 v21 成绩。部署前 current manifest 原始字节及其引用的旧可变源码/patch 应保存到版本化备份，新的部署记录冻结后再打包，ZIP SHA 放在独立外层 sidecar，避免摘要循环。
