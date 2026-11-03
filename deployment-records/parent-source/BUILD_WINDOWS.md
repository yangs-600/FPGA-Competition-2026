# Windows 源码重建说明

本文件随发布包放在 `source/BUILD_WINDOWS.md`。已经提供的 `baseline/`、`candidate/` 和 `runtime/` 用于直接运行作品；**运行现成作品不需要编译器、CMake、MSYS2 或另装 Python**。按照发布包主 README 的运行入口操作即可。

下面的工具只供需要审核源码、重新编译的人员使用。重建脚本不会下载、安装工具，不会更改原交付物，也不会自动执行综合、形式验证或性能验收。

## 本次 v26 交付程序的构建来源

v26 使用已完成全量、同参数构建的 v25 作为增量构建父版本。原版 EXE、ABC 和运行库保持父版本字节；候选仅重新编译 PMUX 源文件并重新链接，其他编译单元按原顺序复用已冻结的对象文件。统一 ABC 资源脚本另调整为 F3。增量记录绑定新源码、完整补丁、编译命令、所有复用对象及最终 EXE，并检查父目录文件前后不变。

这是增量构建，不宣称 v26 的所有对象均重新编译。两侧公共编译参数仍相同；生成版本对象继承父构建的真实 Yosys 0.69 与 dirty 元数据，增量时间记录在构建收据。最终验收只使用本轮 v26 Windows EXE 的新报告，不沿用父版本成绩。

下面的便携重建入口支持从交付的完整源码和补丁建立新的两套源码与对象目录。它不会复用上面的增量对象，也不保证新 EXE 与发布 EXE 字节相同；重新编译后仍应重新进行功能、面积、性能及形式验证。

## 所需本地工具

提供已存在的三个路径：

| 参数 | 路径内容 |
|---|---|
| `--toolchain-bin` | MSYS2 **UCRT64** 的 `bin`：GNU `gcc.exe`、`g++.exe`、`cmake.exe`、`ninja.exe`、`strip.exe`、`windres.exe` 及其正常依赖 |
| `--msys-bin` | 同一套 MSYS2 的 `usr/bin`：`bison.exe`、`flex.exe`、`m4.exe` 及其正常依赖 |
| `--python` | 完整 Python 的 `python.exe`，供 CMake 和构建生成器使用；不要填写交付包内的嵌入式 Python |

本次实验采用 GNU GCC 16.2.0、CMake 4.4.4。发布包记录具体构建身份。复现时应使用相同工具链；脚本记录实际工具文件 SHA-256，并要求 UCRT64 目录中的五个运行库与交付包一致，避免混用不匹配的运行库。若这个检查失败，请使用匹配的工具环境，不要替换交付包的 DLL 来绕过检查。

## 重建命令

在 **PowerShell** 中进入解压后的发布包根目录。将示例路径改为本机已经安装的工具路径；`--output` 必须是尚不存在的、仅含 ASCII 字符的绝对目录，并位于发布包和工具安装目录之外。

```powershell
& .\runtime\python.exe -I -S .\source\build_windows_portable.py `
  --toolchain-bin 'C:\msys64\ucrt64\bin' `
  --msys-bin 'C:\msys64\usr\bin' `
  --python 'C:\Python314\python.exe' `
  --output 'D:\fpga-rebuild-01' `
  --jobs 2
```

嵌入式 Python 在这里仅运行标准库重建脚本；`--python` 指定的完整 Python 才是 CMake 使用的构建工具。可以将命令开头的 `runtime/python.exe` 换成完整 Python 3.10 或更高版本。

脚本依次准备源码、配置两侧、核对公共编译命令，再分别编译原版和候选版。默认最多同时启动两个编译任务。完整重建耗时和磁盘用量取决于电脑，需要保留两套源码和构建目录；不要在性能验收期间同时编译。

只检查输入和解压源码时，可在命令末尾加 `--prepare-only`。此模式不调用编译工具；随后进行完整构建时须选择另一个全新的 `--output`，不会复用检查目录。任何失败都会保留已生成文件和日志。再次尝试也需使用新目录，脚本不会清理或覆盖已有目录。

## 源码、配置及 ABC

脚本读取发布包根目录的 `manifest.json`，检查四个源码输入：

- `source/yosys-0.69-pristine.tar.gz`：包含展开后的子模块的固定原版源码包。
- `source/synth-intel-competition.patch`：相对于上述原版的完整五文件补丁。
- `source/pmux_competition_v11.cc`：当前候选 PMUX 实现；文件名保留历史兼容命名，具体版本以 manifest 和源码日志为准。
- `source/competition_abc_dch.abc`：候选使用的固定 ABC 脚本。

原版来源绑定到真实 Yosys `v0.69` tag 的提交 `9f75ca1f9834a39a863915b5dae0c7b1e33533bc`，以及已经核实的 pristine SHA-256。脚本同时检查压缩包内 `.gitcommit`、版本数据和子模块展开情况；补丁必须精确匹配上下文、重建出清单指定的源码，且只能改动五个已声明文件。

下述完整重建脚本使两侧都从新解压的源码编译，使用相同 GNU 工具链、`MinSizeRel`、上游实际 `-Os` 及统一兼容参数 `-fno-declone-ctor-dtor`，保留完整组件；不启用 LTO、编译缓存、动态插件、组件裁剪或额外链接优化。兼容参数在 `CMAKE_CXX_FLAGS` 中，作用于两侧全部 C++ 编译单元。脚本检查实际命令中该参数位于 `-Os` 之前，并要求两侧公共编译单元的命令在路径归一化后相同；候选新增一个 PMUX 编译单元，版本元数据以 `-dirty` 标记补丁状态。生成的头文件和版本内容允许随真实源码状态不同。

这个兼容参数用于规避 GCC 16、C++20、`-Os` 组合下的 `std::string` 移动构造函数链接问题，见 [MSYS2 上游问题 #31015](https://github.com/msys2/MINGW-packages/issues/31015) 和 [GCC 问题 #125359](https://gcc.gnu.org/bugzilla/show_bug.cgi?id=125359)。本机独立小程序已验证：单独 `-Os` 失败，`-Os` 加该参数成功，`-O3` 成功；参数放在 `-Os` 前也成功。这项验证只说明小程序可以链接，不是作品的功能或性能验收。重建没有改动 C++ ABI 宏、标准库源码或其他 Yosys pass 来绕开问题。

**这次不重新编译 ABC。** 两侧采用发布包根目录已有的同一个 `yosys-abc.exe` 字节，脚本对照 manifest 的 `file_origins` 和 `shared_files` 检查共享 ABC 与运行库 SHA-256。新运行目录根也只放一份 ABC 和其所需的五个 DLL；两角色目录各放相同五个 DLL，不放 ABC，防止角色目录副本遮蔽共享 ABC。ABC 源码已包含在 pristine 包内。使用未修改的 Yosys 上游代码中“本目录未找到 ABC 时，查找父目录”的逻辑，不嵌入原电脑的 ABC 路径。

当前固定源码归档**包含 `.git` 元数据**。若本机 Git 可用，上游 CMake 会读取它来确定版本信息；若 Git 工具不可用或不能取得提交距离，上游逻辑可能显示 **`0.69+post`**。这并不表示使用了别的版本，版本归属以真实 tag 对应提交及已核实的源码哈希为依据。脚本没有伪造 Git 历史或修改源码中的版本逻辑。

CMake 查询 Git 状态时可能刷新 `.git/index` 中的文件状态缓存。脚本仅允许该缓存字段改变，并另记变前、变后哈希；索引的路径、文件模式、对象 ID、标志和扩展内容必须保持一致，其余全部源码文件继续逐字校验。这个例外不会放过实际源码、补丁或 Git 索引内容的改动。

上游完整构建还会在源码目录生成三个资源：`techlibs/gatemate/lut_tree_cells.genlib`、`techlibs/gatemate/lut_tree_map.v`、`techlibs/quicklogic/qlf_k6n10f/bram_types_sim.v`。脚本只允许新增这三个路径，并核对生成器与 pristine 源码哈希一致、生成命令来自已记录的 Ninja 规则、生成文件与 `build/share` 副本相同。原始文件集合仍完整检查；其他新增、删除或内容改动都会使构建校验失败。这些是上游生成资源，不属于 PMUX 修改补丁。

## 输出与验收边界

新输出目录包含：

| 目录/文件 | 内容 |
|---|---|
| `sources/baseline/`、`sources/candidate/` | 原版和补丁候选的独立源码 |
| `build/baseline/`、`build/candidate/` | 完整构建目录 |
| `roles/` | 新运行目录根，包含共享固定 `yosys-abc.exe` 和相同五个 DLL |
| `roles/baseline/`、`roles/candidate/` | 新 EXE、五个 DLL 和 `share/`；通过上游父目录查找逻辑使用共享 ABC |
| `inputs/` | 本次使用的 manifest 及源码输入副本 |
| `records/` | 配置与编译日志、源码清单、实际命令核对、工具及产物哈希 |
| `records/build-result.json` | 全部完成后的构建结果；未完成时不存在 |

成功状态为 `BUILT_UNEXECUTED_VALIDATION_REQUIRED`，意思是 **编译完成，但新 EXE 尚未执行或验收**。它不等于九例通过、形式证明通过或性能通过。重新编译生成的是新产物，不能套用原交付 EXE 的性能报告；应在另外的运行副本中记录新的功能、面积、形式和 Windows 性能证据，保留首轮数据。

本脚本不要求重建 EXE 与原交付 EXE 的哈希一致。不同构建目录、工具版本、生成元数据等可能影响二进制字节，源码和配置一致也不能替代实际验证。
