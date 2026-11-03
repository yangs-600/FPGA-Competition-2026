# Windows 原生源码重建

运行已提供的作品，只需要完整解压本包并执行 `run_cases.cmd`。运行时使用包内的原生 Windows EXE、ABC、DLL 和嵌入式 Python，不需要编译器、MSYS2、另装 Python 或 WSL。

包根目录中的 `yosys-baseline.exe`、`yosys-candidate.exe` 共享同一份 `yosys-abc.exe`、五个 DLL 和 `share/`。两个 EXE 的字节与 v26 构建产物相同；这次部署调整只改变文件存放位置和路径解析。原生程序使用未修改的上游同目录工具查找逻辑。测量入口为两侧设置相同的包根目录 PATH 和 `share/` 资源目录。

## 交付产物的构建来源

当前基线逐字复用已经完成的 Yosys 0.69 全新 MinSizeRel 基线。候选从同次完整 v25 构建复用 341 个对象，只重新编译 PMUX 一个编译单元，再按原顺序链接，并采用全局 F3 ABC 脚本。完整命令、源补丁、对象哈希和父构建证据在 `build-records/`；布局和 runner 路径变更在 `deployment-records/`。当前候选不是一次全部对象重新编译的 v26 构建，版本对象中的构建时间也继承自 v25。

下面提供的便携脚本可从固定原版源码包**完整重新编译两侧**，不会复用上述对象，也不会覆盖交付文件或执行新 EXE。重新编译的文件须重新验证，不能直接沿用交付 EXE 的性能或形式证明结论。

## 可选重建工具

| 参数 | 本机已存在的工具 |
|---|---|
| `--toolchain-bin` | MSYS2 UCRT64 的 `bin`，包含 GNU GCC/G++、CMake、Ninja、strip、windres 及其依赖 |
| `--msys-bin` | 同一套 MSYS2 的 `usr/bin`，包含 bison、flex、m4 |
| `--python` | 完整 Python 安装的 `python.exe`，供 CMake 和生成器使用；不要选包内嵌入式 Python |
| `--output` | 包和工具安装目录之外、尚不存在的 ASCII 绝对目录 |

本次参考工具为 GCC 16.2.0、CMake 4.4.4。脚本记录实际工具哈希，并要求五个 UCRT64 运行库与交付包一致。脚本不会自动下载或安装工具。

在解压后的包根目录，用 PowerShell 执行；示例工具路径请替换成本机真实路径：

```powershell
& .\runtime\python.exe -I -S .\source\build_windows_portable.py `
  --toolchain-bin 'C:\msys64\ucrt64\bin' `
  --msys-bin 'C:\msys64\usr\bin' `
  --python 'C:\Python314\python.exe' `
  --output 'D:\fpga-rebuild-01' `
  --jobs 2
```

嵌入式 Python 仅负责运行这个标准库脚本，`--python` 指定的完整 Python 才用于构建。也可用完整 Python 3.10 以上运行脚本。完整重建需要两套源码、构建空间和编译时间；不要与性能测量同时进行。

加 `--prepare-only` 可仅校验并准备源码，不调用编译工具。后续完整重建须使用另一个新输出目录。失败输出和日志全部保留；脚本不会清理或覆盖已有目录。

## 源码及参数校验

脚本通过包内 `manifest.json` 校验四个输入：`yosys-0.69-pristine.tar.gz`、`synth-intel-competition.patch`、`pmux_competition_v11.cc`、`competition_abc_dch.abc`。完整补丁只能修改已声明的五个文件；脚本逐段核对上下文并确认重建结果与源码和 ABC 脚本一致。

固定原版来源是实际 Yosys `v0.69` tag 对应提交 `9f75ca1f9834a39a863915b5dae0c7b1e33533bc`。归档包括展开的子模块和 `.git` 元数据，来源以该提交和已经核实的 pristine 哈希绑定，不通过改版本字符串冒充原版。候选 checkout 信息保留 `-dirty` 标记。若本机 Git 不能取得距离，上游版本逻辑可能带 `+post`；实际归属仍须结合固定源码证明。

两侧使用相同工具链、MinSizeRel、`-fno-declone-ctor-dtor -Os`、完整组件和原有链接参数；不启用 LTO、编译缓存或插件方案。兼容参数用于规避 GCC 16/C++20/`-Os` 的构造函数链接问题，原独立复现证据保留在父构建记录中。脚本核对实际公共编译命令一致。

本次不重新编译 ABC。两侧共享已交付、已固定哈希的 ABC 字节；ABC 源码包含在 pristine 归档。原生输入校验要求两个 EXE、ABC、五个 DLL 和完整共享资源目录与 manifest 的每项物理路径映射一致，拒绝角色子目录或遗漏资源。

上游配置可能刷新 `.git/index` 的文件状态缓存。脚本只允许统计缓存字段改变，路径、模式、对象 ID、标志和扩展仍须一致。构建也允许上游生成三个已知资源：GateMate 的 `lut_tree_cells.genlib`、`lut_tree_map.v` 和 QuickLogic 的 `bram_types_sim.v`，并核对 pristine 生成器、Ninja 命令和对应 share 副本。其他源码改动会失败。

## 输出

| 路径 | 内容 |
|---|---|
| `sources/baseline/`、`sources/candidate/` | 分别新解压的原版、候选源码 |
| `build/baseline/`、`build/candidate/` | 两套完整构建目录 |
| `roles/yosys-baseline.exe`、`roles/yosys-candidate.exe` | 新的两份原生 EXE |
| `roles/yosys-abc.exe`、五个 DLL、`roles/share/` | 共享运行载荷；没有 `roles/baseline/` 或 `roles/candidate/` 运行子目录 |
| `inputs/`、`records/` | 输入、源码清单、配置及构建日志、工具与产物哈希 |
| `records/build-result.json` | 完成后的结果，含逻辑角色映射与完整共享资源清单 |

重建输出的 `roles/` 仅是新的工具运行目录，不自动复制整套测量器或生成验收报告。`BUILT_UNEXECUTED_VALIDATION_REQUIRED` 只表示构建成功、新 EXE 尚未执行。构建目录、工具和时间元数据都可能改变二进制，不能要求与原交付哈希相同，也不能据此直接判定功能或性能通过。

形式证明所需的逻辑路径副本只存在于独立 Windows 证据包中，详见 `PROOF_REPLAY_GUIDE.md`；它们不会加入实际共享运行目录。Linux 环境只承担形式证明，Windows 性能仍由原生 EXE 在 Windows 上测量。
