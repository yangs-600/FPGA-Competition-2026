# Yosys 0.69 PMUX 优化：Windows 运行与 EQY 验证

本项目提供九个 RTL 用例、原版与优化版 Yosys 0.69、Windows 运行依赖、源码补丁和验证脚本。既有九例结果的 LUT + 独立 NOT 平均降幅为 **20.079171%**；逐例资源不增加，按声明的采样规则通过时间与根进程峰值内存判定，并完成 18 项 EQY 证明及负对照。详见[历史测试记录](../测试文档.md)与[采样口径](../README_PROTOCOL.md)。这些记录不代表下一次运行必然通过。

将仓库完整下载或克隆到 Windows 10/11 x64 的可写英文无空格路径，例如 `D:\FPGA-Windows`，在仓库根目录运行。源码重新编译需要另备工具链；下面的运行入口使用已附的程序。

## 仅测量：无需另装开发软件

```powershell
.\run_demo.cmd
```

使用包内 Python、Yosys、ABC 和依赖库，重新执行九例综合、资源与性能测量、独立测量审计并生成报告。无需另装 Python、Yosys 或编译器；此模式不运行 EQY，也不调用 WSL 或外部 OSS CAD Suite。`MEASUREMENTS_PASS_FORMAL_PENDING` 表示测量通过、本轮证明未执行。

## 完整验证：选择一种证明环境

**Windows 原生 EQY：**先安装 Windows x64 OSS CAD Suite，将根目录的 `oss_cad_suite_path.txt` 写成套件根目录，再运行：

```powershell
.\run_full.cmd --backend windows
```

默认配置为 `C:\oss-cad-suite`，该目录应直接包含 `environment.bat` 和 `bin`。也可用 `--oss-suite D:\oss-cad-suite` 临时指定路径。完整 Windows 套件未包含在仓库内；本包附有 EQY 所需的 make、Bash 等辅助工具。[使用说明](../使用说明.md)提供已验证的官方 2026-10-11 套件下载地址与版本信息。其他版本需另行验证兼容性。

**WSL EQY：**已有完成首次初始化的 WSL Linux x86_64 发行版时，运行：

```powershell
.\run_full.cmd --backend wsl
```

首次运行从 `proof-tools/` 内的冻结 Linux 工具归档配置当前 WSL 环境，不需要另行下载 EQY、sudo 或手工填写他人的 Linux 路径。此入口不负责安装 WSL；已验证环境为 WSL2 Ubuntu-24.04。多发行版可加 `--wsl-distro Ubuntu-24.04`。

两种完整模式都先用包内参赛 Yosys 完成 Windows 测量，再对本轮网表执行 EQY；预装证明用 Yosys 不替代测量程序，证明耗时不计入综合耗时。只有测量、审计、18 项正向证明及负对照全部通过，状态才是 `MEASUREMENTS_AND_FORMAL_PASS`。

不指定 `--backend` 时，配置的 Windows 套件目录存在则选 Windows，否则选 WSL；选定后端失败会报错，不会静默切换或跳过证明。

## 查看结果与源码

每轮新报告位于 `tmp/demo-results/latest-results.md`；原始数据和失败日志一并保留。同一目录只运行一个入口，自动运行可加 `--no-pause`。旧 `run_cases.cmd` 仅提供冻结的简洁测量入口。

- [详细使用说明](../使用说明.md) · [本次交付环境验证记录](../docs/PORTABLE_RUNTIME_VALIDATION.md)
- [源码和完整重建方法](../source/BUILD_WINDOWS.md) · [技术报告 PDF](../docs/technical-report.pdf)
- [冻结发布证据](../release-status.json) · [仓库完整性范围](../REPOSITORY.md)
- [第三方许可证](../THIRD_PARTY_NOTICES.md) · [新增辅助工具来源及许可证](../native_support/README.txt)

Git 工作树包含运行依赖及冻结发布证据，排除后续生成的 `tmp/` 和测量目录；完整历史运行文件见发布附件 `全部代码.rar`。根目录旧 `README.md` 属于冻结证据，保留原字节；当前入口说明以本页和 `使用说明.md` 为准。
