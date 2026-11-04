# Git 工作树与完整发布包

本仓库采用平铺布局，Windows 运行入口、内嵌 Python、Yosys、ABC 和依赖位于根目录及其子目录。当前使用方式见 [.github/README.md](.github/README.md) 与 [使用说明.md](使用说明.md)。`run_demo.cmd` 只测量；`run_full.cmd` 在 Windows 测量后，使用已预装的 Windows OSS CAD Suite 或已初始化的 WSL 执行本轮 EQY。

`payload-index.json` 保留原始 **2727 文件**发布范围（含该清单自身）。原始源码、二进制、许可证、报告、根目录 README 和 `validation-current-9i4sbu6t/` 均保持其记录的字节。`repository-release.json` 另外登记运行入口、证明依赖、技术报告和仓库说明等扩展文件。此前已发布的 `verify_repository_payload.py` 保持原字节。

可自行执行以下只读完整性核对；它只比对文件大小和 SHA-256，不执行综合、性能测量或 EQY：

```powershell
.\runtime\python.exe -I -S .\verify_repository_payload.py
```

在 Linux 上可用 `python3 -E -B verify_repository_payload.py` 核对字节；Windows 运行入口仍需 Windows。发布准备阶段没有重新运行项目测试，既有验证结论见 [PORTABLE_RUNTIME_VALIDATION.md](docs/PORTABLE_RUNTIME_VALIDATION.md)。

`.gitignore` 排除 `tmp/`、新测量目录和 Python 缓存，但明确保留冻结的 `validation-current-9i4sbu6t/`。`测试文档.md` 是 2026-11-04 13:48 的历史结果；其后列出的临时证据路径属于完整 RAR，未放进本工作树。运行本仓库会创建新的结果。

完整发布附件 `全部代码.rar` 为原始打包字节：97,217,374 字节，SHA-256 为 `0fdc2fda8de15040f24b7614a15852c938a4d96227408a650202ec855055289d`。它包含额外历史运行文件和外层启动包装；Git 工作树使用适合平铺布局的内层启动脚本。

`.gitattributes` 禁用换行转换、ident 展开和外部过滤器，以保留验证过的字节。不要用 Git LFS 指针替换随包运行文件。旧 `PENDING` 字段保留原字节；冻结证据的完成状态见 `release-status.json`，本轮状态应读取新生成报告。

随包第三方工具保留原许可证。`native_support/` 保存辅助工具来源、精确源码包 URL 和许可文本；完整 Linux 证明工具归档亦保持原字节。完整性核对不等于重新验证功能或性能。
