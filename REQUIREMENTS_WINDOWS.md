# Windows 运行与复现依赖

## 直接运行

本提交的优化器是 Windows x64 原生 `yosys-candidate.exe`；原版为 `yosys-baseline.exe`。解压到英文路径，例如 `D:\FPGA\submission`，双击 `run_cases.cmd`。路径可以自行选择，脚本通过自身目录定位文件，不使用作者电脑的安装路径。此 Yosys/ABC 构建需要 ASCII 路径。

包内已附运行所需的共享 `yosys-abc.exe`、五个 DLL、一套公共 `share/` 资源、Python 运行时、九个用例和测量脚本。直接运行综合、面积统计与性能测量无需安装 Ubuntu、WSL、Python、GCC 或 OSS CAD Suite。

两个 EXE、ABC 和五个 DLL 位于同一根目录，公共资源位于根目录 `share/`。请保留目录结构，不需要另外复制两套运行依赖。程序通过 Windows 标准应用目录查找 DLL，并通过 Yosys 原有的 EXE 目录规则定位资源与 ABC。运行脚本会校验工具、资源和用例指纹，拒绝被替换的文件。每次运行会新建 `validation-current-*`，不会读取历史成绩充当本次结果。

`run_cases.cmd` 完成九例完整综合、Windows 性能测量以及形式证明对象导出。它不会将未运行的 EQY 声明为 PASS；随包的形式证明证据属于发布前对实际 Windows 对象完成的独立验证。

## 从源码重建

从源码编译才需要 GCC/G++、CMake、Ninja、Flex、Bison、M4 和完整 Python。经过验证的工具链参数、输入摘要与构建记录随包保留，具体命令见 `source/BUILD_WINDOWS.md`。

`source/yosys-0.69-pristine.tar.gz` 是完整原版源码归档；`source/synth-intel-competition.patch` 是完整五文件补丁；`source/pmux_competition_v11.cc` 为优化 pass；`source/competition_abc_dch.abc` 为所有用例统一使用的 ABC 脚本。

两侧使用相同的 `MinSizeRel -Os` 和 `-fno-declone-ctor-dtor`。后一选项规避本机 GCC/MinGW 的 C++20 构造函数编译问题，不修改标准库、ABI 或其他 pass 源码。便携重建脚本复用包内同一份已固定 ABC；ABC 的源代码也在原版源码归档中。

## 重新运行形式证明

本轮证明使用 Linux 环境中的 EQY、Yosys、SBY 及相应求解器，对 Windows 程序实际导出的18个 `postabc.il` 对象验证；Linux 证明耗时不计入 Windows 综合效率。

EQY 证明工具并非 Windows 原生运行入口的一部分。随包保留原始测量、网表、证明日志、负对照、工具身份及复现脚本；重新运行证明需要单独的 Linux EQY 环境，按证明指南配置。不要将 Linux 工具用于替代本包 Windows EXE 的性能测量，也不要把历史证明自动视为后续修改代码的证明。
