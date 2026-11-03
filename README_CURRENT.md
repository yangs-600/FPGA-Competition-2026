# Yosys 0.69 PMUX Windows 原生作品

九例平均 LUT+独立 NOT 降幅 **20.079171%**；每例资源不增加；按预先声明口径，九例时间与峰值内存增幅均不超过 5%；18 项形式证明通过，负对照成功检出反例。

解压到 ASCII 路径（例如 `D:\FPGA\submission`），双击 **run_cases.cmd**。在 PowerShell 当前目录也可运行：

```powershell
.\run_cases.cmd
```

已包含 Windows x64 的 yosys-baseline.exe 与 yosys-candidate.exe，共享根目录 ABC、五个 DLL 和一套 share 资源，另附 Python 与九个用例。直接运行无需 Ubuntu、WSL 或安装编译器。该命令重新综合、测量并导出实际网表，创建新的 `validation-current-*`；不会把随包历史证据当作本轮运行结果。

首轮原始数据全部保留。两侧首轮各自不足 1 秒且任一增幅超过 5%时，固定追加五对复核，比较两侧各自算术平均；触发首轮单列，不计入这五对。此次有 1 例进入复核，首轮单独满足两项 5% 的为 8/9 例。具体数字与口径见 [VALIDATION.md](VALIDATION.md)。

Linux EQY 只证明 Windows 实际导出的网表，未替代 Windows 性能测量。随包保存发布前的 18 项证明及负对照；普通 Windows 运行入口不会宣称已经重新运行 EQY。

- [Windows 运行依赖](REQUIREMENTS_WINDOWS.md)
- [源码重建](source/BUILD_WINDOWS.md)：完整原版源码、五文件补丁和便携脚本位于 `source/`。
- [证明复现](PROOF_REPLAY_GUIDE.md)：需要单独的 Linux EQY 工具环境。
- [完整 Windows 数据](evidence/windows/report.json)、[独立审核](evidence/independent-audit.json)、[形式证明](evidence/formal/formal/report.json)。
- [原始问题汇总](requirements/FAQ.xlsx)及 [口径说明](requirements/FAQ.md)。

根目录保留本次 `validation-current-9i4sbu6t/` 的逐字节副本，使独立审计脚本可在解压后直接复算；它属于发布证据，不是新运行的成绩。在包根目录执行以下命令只审核既有记录，不执行 Yosys：

```powershell
.\runtime\python.exe -I -S -X utf8 .\evidence\audit_native_measurements.py --package . --report .\evidence\windows\report.json --output ..\audit-release.json
```

输出文件须尚不存在。真正重新运行九例仍使用 `run_cases.cmd`，每次建立全新的测量目录。

原始 `manifest.json` 和 Windows 报告中的 PENDING 字段保留原字节；最终证据汇总在 [release-status.json](release-status.json)。`payload-index.json` 列出每个交付文件的 SHA-256 和大小（不含清单自身）。
