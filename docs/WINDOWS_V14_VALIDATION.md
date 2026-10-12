# v14 四个官方用例 Windows 验收（2026-10-12）

实现和四份原始 RTL 保持不变。Yosys 0.69 固定提交为 `9f75ca1f9834a39a863915b5dae0c7b1e33533bc`，项目算法对应 `c9b5d9c8ec95605c672dd79185b8c5545ca3da83`。原版未集成 PMUX pass；候选在 synth_intel 中内置 v14，并调用内置 abc9。两版同一 GCC 16.2.0 Release 配置、同一 ABC 文件、同机同脚本测量。

## 正式口径

根据问题汇总 C25/C67，逻辑资源按 LUT＋独立 NOT 计，四例减少率取算术平均；DFF 不混入该减少率。现有两份运行脚本已经据此修正 `gain_percent` 和 `average_gain_percent`，另保留 `lut_gain_percent` 和 `average_lut_gain_percent`。

| 用例 | 逻辑资源原版→候选 | DFF 原版→候选 | 减少率 |
|---|---:|---:|---:|
| test1 | 288→223 | 222→222 | 22.5694% |
| test2 | 25→15 | 0→0 | 40% |
| test3 | 13→13 | 17→12 | 0% |
| test4 | 36→27 | 10→10 | 25% |

正式平均为 **21.89236111%**，超过 20%；LUT 单项平均 22.11038961% 为辅助值。其他单元类型均未增加。

## Windows 性能实测

每例一次预热后，原版与候选交错运行 21 次（168 个计时进程）。计时覆盖 read/synth_intel/write，含 ABC；源代码编译不计入。CPU 采用 Windows Job Object 的累计 user＋kernel 时间，包含已结束的子进程；内存采用 yosys.exe 的 PeakWorkingSetSize。进程以 suspended 状态加入 Job 后再启动，避免漏计早期 ABC；退出后检查无存活子进程。计量器通过耗时子进程与 128 MiB 子进程的正向校验。

| 用例 | CPU 中位数原版→候选（秒） | CPU 增量 | 主进程峰值工作集增量 | 候选最大工作集（MiB） | 候选最长墙钟时间（秒） |
|---|---:|---:|---:|---:|---:|
| test1 | 0.28125→0.28125 | 0% | +0.1620% | 21.7383 | 0.356636 |
| test2 | 0.15625→0.140625 | −10% | −0.0510% | 15.3086 | 0.203648 |
| test3 | 0.171875→0.15625 | −9.0909% | −1.1154% | 15.9297 | 0.215242 |
| test4 | 0.1875→0.171875 | −8.3333% | −1.8431% | 17.0586 | 0.225840 |

上表为 21 轮正式计时的统计；报告另保留首次未预热运行，候选最长 0.727545 秒、最大工作集 22,880,256 字节，同样满足绝对限制。

四例逐一满足 CPU/内存增量 ≤5%，且完整流程实测 ≤60 秒、主进程峰值工作集 ≤2 GB。这是这四个用例在本机的测量结果，其他机器的绝对时间可能变化。

## ABC 后 ILANG 等价证明

`scripts/verify_postabc_ilang.py` 导出 Ubuntu 原版/候选八份 ABC9 后原生 `$lut` ILANG，八次 EQY 均 PASS，并检出负对照明确反例。最终映射资源与未分段的完整流程一致。

`scripts/verify_windows_ilang.py` 验证 Windows 实际输出，通过源 RTL、二进制、原始 ILANG 和 Windows 测量报告 SHA256 绑定证明对象。Windows CRLF 原件保留；仅另存逐字节可逆的 LF 副本供 Ubuntu 解析。证明准备使用标准 `lut2mux -word` 展开原生 LUT，以适配当前 SBY/SAT 引擎，不使用自定义 LUT 模型。ABC9 前已经映射的 dffeas 采用已审阅的限制功能模型并检查所有适用控制脚。

Windows 实际网表的八次 EQY 证明全部 PASS，负对照检出明确反例。与 Ubuntu 生成网表的八次证明分别保留，不能用 Ubuntu 输出替代 Windows 实际输出的证明。

原始性能报告、形式报告、日志、网表和工具指纹保存在 Windows 验收包；最终状态以包内 `acceptance.json` 汇总为准。原始阶段报告保留它生成时的状态，不能将阶段完成等同于全包验收完成。

## 交付与复测

Windows 包含原版/候选 yosys.exe、同一 yosys-abc.exe、所有非系统运行 DLL、share 资源、四例源码、运行脚本、v14 源码/ABC 脚本/集成补丁、原始 0.69 源码归档、许可证和证据。

解压到英文目录，例如 `D:\FPGA\windows-v14`，Windows PowerShell 执行：

```powershell
cd D:\FPGA\windows-v14
python .\run_windows_four_cases.py --repeats 21
```

运行无需安装编译器或 MSYS2。脚本只对被测进程设置英文 TMP/TEMP；原有 OSS CAD Suite 保留。新复测会重新生成待证明的 ILANG，不会伪造 EQY 通过状态。完整证明重放方法见包内 README。

本次没有修改算法、官方测试 RTL，也没有自动提交或推送 GitHub。剩余工作是正式技术报告、答辩材料及提交平台所需材料；平台未明确的字段应向主办方确认，不能据此虚构板卡或硬件验收要求。

## 最终交付包校验

交付文件：`FPGA-topic2-v14-Windows-0.69-20261012.zip`（71786855 字节）。SHA256：`cdcb76388fc93e2120a0ead203e06645dfc4f315b550e3de8fc9d1231f626e27`。

647 个二进制、DLL 与资源文件指纹全部吻合；926 个 ZIP 条目 CRC 校验通过。解压到新的英文目录，以仅含 Windows 系统目录的 PATH 和显式指向解压目录的 YOSYS_DATDIR 运行八次完整综合，原版与候选四例全部通过，单元类型计数与正式报告一致。
