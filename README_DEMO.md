# 本包运行入口

在 Windows 10/11 x64 上，把整个包解压到可写的英文无空格目录，例如 `D:\FPGA-Windows`。不需要安装 VS Code。

## 只运行九例测量

```powershell
.\run_demo.cmd
```

使用包内 Python、Yosys 0.69、ABC 和依赖库，重新综合九个用例，输出资源降幅、耗时、根进程峰值内存和简明 Markdown 报告，并执行独立测量审计。不调用 EQY、WSL 或外部 OSS CAD Suite。

## 同时执行本轮等价验证

已预装 Windows OSS CAD Suite 时，将 `oss_cad_suite_path.txt` 改为其实际根目录，然后运行：

```powershell
.\run_full.cmd --backend windows
```

建议使用已验证的官方 2026-10-11 Windows x64 套件。其默认建议路径为 `C:\oss-cad-suite`；套件目录中应直接包含 `environment.bat` 和 `bin`。套件路径也不能含中文或空格。

若已有可用并完成初始化的 WSL Linux x86_64 发行版：

```powershell
.\run_full.cmd --backend wsl
```

包内已附 Linux EQY 证明工具归档，会自动配置到当前 WSL 用户目录。此入口不安装 WSL、不联网、不需要 sudo。实测为 WSL2 Ubuntu-24.04；其他发行版先通过工具预检。

不带 `--backend` 时，若路径文件指定的 Windows 套件目录存在，则选择 Windows；否则尝试 WSL。选定后端失败时会保留错误并返回非零退出码，不会跳过证明。

完整入口在 Windows 综合测量及审计后，针对本轮导出的网表运行 18 项 EQY 证明和一个故意错误的负对照。证明用预装工具不会替代参赛综合二进制。证明耗时不计入综合性能指标。

## 查看结果

本代码目录下：`tmp/demo-results/latest-results.md`。

- `MEASUREMENTS_PASS_FORMAL_PENDING`：测量通过，本轮证明尚未执行。
- `MEASUREMENTS_AND_FORMAL_PASS`：测量、审计及本轮证明均通过。
- 其他状态须查看该轮报告和错误日志，不能当作完整通过。

旧测试文档属于历史记录；新结果每轮重新生成。原始测量 JSON 不会因为补做证明而改写，证明回执通过报告校验值关联本轮输入。

Git 工作树采用平铺布局，启动入口位于仓库根目录。自动运行可以加 `--no-pause`。同一代码目录只运行一个测试；新入口会拒绝并发任务。旧 `run_cases.cmd` 只提供简洁测量，不要与新入口同时使用。

更详细的路径设置、可选参数和文件说明见仓库根目录的 `使用说明.md`。本次只调整运行入口、交付依赖和等价验证后端，保留原综合算法与采样规则。
