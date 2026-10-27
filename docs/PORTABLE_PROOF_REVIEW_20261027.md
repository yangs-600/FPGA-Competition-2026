# v21 独立 Linux / WSL2 形式验证包审查说明

本轮 r4 便携包已在全新 ASCII 目录完成实际复验：18 个 Windows 原始网表正证明均通过，故意错误的负对照检出确定反例。下面将早期 r3 部署失败、修复和最后成功分开记录；组装和版本检查本身不作为证明通过。

## 最后实际结果与独立归档审计

- 工具包：`D:/杨森宇/FPGA/FPGA-topic2-v21-EQY-Linux-0.69-20261027.tar.gz`，43,472,694 字节，SHA-256 `1e310f0210e364649be7905e18b7e9ba26b1b81af59ce5002ffd0d0b8b371501`。
- payload index SHA-256：`b9ff9fdc784526dafc51d4798b8b1d22c37399e5fbd9b4d3c1553dc357190650`。独立从最终 tar 逐项重新计算 1,442 个 payload SHA，全部匹配，tar 恰包含这些文件加 index；无路径越界、软/硬链接、特殊节点或 setuid/setgid 位。60 个入口、ELF 及 loader 的执行权限均正确。
- 新运行目录：`/tmp/fpga-v21-proof-relocated-20261027-r4/FPGA-topic2-v21-EQY-Linux-0.69-20261027`。实际报告 `positive_proof_counts={"PASS":18}`，负对照为 `EXPECTED_COUNTEREXAMPLE`，明确 `definite_counterexample=true`。
- 实际 formal report SHA-256：`a2e05c107f855e47463977aaaf39c0a854ce034f10d2757f3bcfa8fccc9f53d4`；replay receipt SHA-256：`99f6e5e48c72437aaa25320eaad8fabd07a2fffe9c0bbb35e50392504a2bd8f2`。
- 独立检查 85 个活跃输入/工具 fingerprint：全部位于新 kitroot 内。84 个与 tar 中输入逐项 SHA 一致；唯一运行时生成的 manifest 已从 relocation evidence 归档重新核 SHA，所有 baseline/candidate/ABC/EQY/proof_bin 路径也在新 kitroot 内。四个冻结助手身份不变，原版 Linux Yosys / ABC ELF SHA 与 v21 已用链一致。
- Relocation evidence：`D:/杨森宇/FPGA/FPGA-topic2-v21-EQY-relocation-evidence-20261027.tar.gz`，4,143,990 字节，SHA-256 `d4ef4ff10ff0649d4f37b64b696bb5d12e10b46e6526a7eb60710f3e912894ca`。这是另存的证明证据，不放入 payload index 自引用循环。
- 实际收到上游许可：Yosys `src/COPYING`，SHA `7747e4dfc1780fd5970360ab394e0950358123c190abcc76f4c3bea5a0bccf2a`；ABC `src/abc/copyright.txt`，SHA `819151b8f059a48f806c75732ef62b1f873b49b6a04fb128aed28bf87d3dcd6c`；另有 41 份 Debian copyright、17 份 common license 正文，EQY/SBY/Witness 源码保留各自完整头部许可。来源/版本/原文件 SHA 清单位于包内 `provenance/closure.json`。
- 本地独立审计结果：`work_20261027/remote/portable-v21-independent-audit.json`。此结论是 Linux 便携形式验证复验通过；未重测 Windows 性能，没有声称全赛项或未来现场保证通过。

## r3 失败与 r4 修复

r3 复验真实失败：test1 和 test3 的 baseline/candidate 共四项到 PDR 时为 UNKNOWN，其余十四项 PASS，负对照生成失败，最终报告是 ERROR，不能列为通过。归档 `portable-failure3.zip` 保留了五份直接显示 `init_share_dirname: unable to determine share/ directory!` 的日志。

原因由固定 0.69 源码核实：Linux `proc_self_dirname()` 读 `/proc/self/exe`；显式私有 ld.so 启动使该位置成为 `runtime/lib/ld-linux-x86-64.so.2`。`init_share_dirname()` 查 `procdir/share/`、`procdir/../share/yosys/` 和编译期 `YOSYS_DATDIR`，并不读取同名环境变量。仅在实际 Yosys ELF 旁放 share、或者设置环境变量，均不足以修复此运行方式。

r4 只修包装布局：原版完整 share 唯一放入 `runtime/share/yosys`，使私有 loader 和直接 Yosys ELF 两种 procdir 都命中第二回退；另外在 `runtime/lib/yosys-abc` 补相同私有 loader wrapper，并保留 `runtime/yosys/yosys-abc`，满足默认 ABC/ABC9 sibling 查找。Yosys/ABC 二进制、四个冻结助手、18 份原始 ILANG、FF 模型、EQY 策略均未修改。r4 随后完整重跑得到上面的 18 PASS 加确定负对照。

## 已核实的依赖

- 原 Windows v21 ZIP 中四个 `formal/tools` 助手与工作目录副本逐字节相同。新增包不修改这四个助手。
- `verify_windows_current.py` 必须能找到 `cases_current.json`、`clean-v11/formal_cycloneiv.v`、验证核心和 Linux 工具 manifest。它只需一个满足此接口的独立目录，不需要 Git、原 Ubuntu 仓库或其历史提交。
- 18 个正证明针对九个源 RTL 与原 Windows 报告中绑定的 baseline/candidate `postabc.il`。原始 ILANG 不改，只允许验证助手进行可逆 CRLF→LF 标准化。另用原版 Yosys 生成故意错误的 test2 网表，经同一 EQY 链要求检出确定反例。
- 实际 EQY 策略为 SAT 加 ABC PDR。现有 `strategies.mk` / `run.sh` 依赖 GNU make、bash、grep、awk、cat；当前策略不需要 SMT 求解器。
- EQY 固定为自行构建的 0.69 安装。其入口按 `bin/../share/yosys` 查 Python 模块和三个插件。不能替换成 OSS CAD Suite 的同名插件：依赖探针实际发现后者要求当前系统不满足的 GLIBC_2.38 / GLIBCXX_3.4.32。
- 已实际使用的 SBY 为 0.68；原 OSS wrapper 使用 tabby Python 3.11。新增包直接保留 `libexec/sby` Python 源码和其模块，以包内 CPython 3.10 运行，版本/导入兼容性必须由 preflight 和完整证明检验。
- 已核实原版 Yosys / ABC / 固定 EQY 插件的本机 ELF 依赖，包括 libffi.so.8、libz.so.1、libtcl8.6.so、libreadline.so.8、libstdc++.so.6、libm.so.6、libgcc_s.so.1、libc.so.6、libtinfo.so.6 和 ELF loader。复制 CPython 扩展及 shell/text utilities 时还会按各自实际 ldd 输出补齐传递闭包。

## 新增实现

- `build_portable_proof.py` 只读原仓库/工具/证据，拒绝覆盖现有 stage。它复制原版 Yosys 0.69、固定相对回退布局的完整 share、ABC、固定 EQY 0.69、SBY 0.68、Click、CPython 3.10 / stdlib / 扩展、明确 allowlist 的系统命令以及其完整 ldd 库闭包；生成 origins / package versions / licenses 和逐文件索引。组装步骤没有编译、综合或运行证明。
- 所有 native ELF 通过私有 loader 和私有 library-path 启动。原版 Yosys 实际 ELF 目录与私有 loader 目录同时提供 `yosys-abc` wrapper，满足默认 ABC/ABC9 sibling 查找。
- 相对入口 `run_verify.sh` 调包内 Python dispatcher。dispatcher 强制 isolated/no-site，提供包内 Click/EQY/SBY 模块，并将 `sys.executable` 指向包内 Python wrapper，避免子进程退回原系统 Python。
- `portable_verify.py` 固定 v21 Windows raw report / manifest 和原版 Linux Yosys / ABC ELF SHA，核验所有索引文件，然后清空继承环境。活跃 PATH、HOME、TMPDIR、Tcl 数据和 proof_bin 都在包内。manifest 在异目录运行后重新生成，旧绝对路径只可保留为 provenance 或原 Windows 历史元数据。
- 为适配原 core 强制 baseline/candidate 两字段，Linux candidate 明确写成 baseline parser alias。优化候选对象是包中实际 Windows candidate ILANG；此入口不重新运行优化 Linux 综合。
- 原 Window ZIP 及其资源/性能报告完全保留。新 Linux proof tar.gz 与其共同组成可审阅交付，不覆盖冻结 ZIP，不重新解释原性能数据。

## 已执行的验收方法与后续复用

1. 组装 stage，并检查上游 Yosys / ABC / EQY / SBY 各许可已纳入。自动收集 Debian copyright 与源码头部许可；必要时通过 `--license-file` 显式补足 upstream COPYING。
2. 将包解压到全新 ASCII、无空格目录，例如 `/tmp/fpga-v21-proof-replay`，使用干净环境启动 `./run_verify.sh --preflight-only`。
3. 运行 `./run_verify.sh`，要求新报告正证明 `{"PASS":18}`，负对照 `EXPECTED_COUNTEREXAMPLE`，所有工具/输入在证明前后 SHA 不变。
4. 审查报告 `fingerprints`：每个活跃文件必须落在新 kitroot 中。原 Ubuntu 仓库、OSS 安装及其绝对 manifest 不得被打开为活跃工具。原 Windows 绝对路径仅作为 raw 报告历史字段允许存在。
5. 将新报告/receipt 留档，生产单独 tar.gz，外置 SHA sidecar。若将 receipt 放回包内，重新生成 payload index 时注意不要形成 index/receipt/hash 自引用循环。

平台边界为 Linux x86_64 / 兼容 WSL2 Linux 内核、挂载的 `/proc`、`/dev/null`、启动脚本所需 `/bin/sh` 以及可写临时/输出空间。它不是普通 Windows 原生 EQY 包，也不是对任意其他内核、未来用例或现场环境的保证。
