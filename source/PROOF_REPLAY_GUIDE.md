# Windows v26 运行与形式验证复现说明

本说明对应按拓扑深度和选择信号打包MUX的v26源码，以及全局统一的当前ABC脚本。实际成绩必须查看本包正式报告；构建完成、依赖预检或本说明本身都不代表性能或证明已通过。

包内 `source/prove_windows_native_once.py` 保持兼容的入口文件名，但内容应为v26派生manifest入口；其开发源文件名为 `prove_windows_native_v26_once.py`。不要用旧v25同名文件覆盖。入口要求v26源码SHA为 `75ed360b73180441fccbe0f5f8ed3f10e1d07147842d38eb74baedc133ce47d2`，本轮候选实际脚本为 `&dch -f; &if -K 4 -a -C 4 -F 3 -A 1`。这不是每例调参；九例使用同一脚本和候选程序。

## 1. Windows 作品运行入口

主包是 Windows 原生程序。在 Windows 上将主包解压到英文路径后，运行包根目录的 `run_cases.cmd`，或在该目录执行：

```powershell
.\runtime\python.exe -I -S -X utf8 .\run_current_cases.py --package .
```

该入口完成九个用例的原版/优化版综合、资源统计、Windows 时间与内存测量，以及实际 post-ABC RTLIL 对象导出。Windows 综合与性能测试不依赖 Ubuntu、WSL、Linux EQY 或外部 Python。

EQY 功能等价验证是单独的一步，使用 Linux 工具证明 Windows 已生成的 18 个网表。主 Windows 包不包含 Linux 工具二进制；需要独立的形式验证工具包，或自行配置符合要求的 Linux 验证环境。Linux/WSL 用于独立的形式证明复现，不是运行 Windows 作品的前提。

## 共享运行目录与证明副本

Windows 主运行目录只有两份不同角色的主程序：`yosys-baseline.exe` 和 `yosys-candidate.exe`。它们共享同目录的 ABC、DLL 与 `share/`。两个 EXE 的实际字节与 v26 分目录构建一致，PMUX 与 F3 算法未因部署方式改变。此布局在测量前固定，原版十次预热会自然访问公共依赖，不额外执行候选预热。

角色在 manifest 中仍用 baseline/candidate 标识；`roles.*.file_origins` 对每个逻辑文件给出实际包内位置。`shared_resources` 记录公共资源的完整集合，运行时不需要 baseline/、candidate/ 两个目录。

冻结 Linux helper 使用旧的逻辑文件名。新证据整理入口只在证明证据包中增加以下三个逐字节副本，并用 `proof-aliases.json` 记录原文件位置与 SHA-256：`baseline/yosys.exe`、`candidate/yosys.exe`、`candidate/share/intel/competition_abc_v11.abc`。这些文件只为冻结 helper 提供逻辑名字，不参与 Windows 测量，也不作为新的构建产物。证据同时保留实际部署文件，入口逐一核对两者指纹。

派生 Linux manifest 的 `abc_script` 指向证据包中的实际公共 `share/intel/competition_abc_v11.abc`，其 SHA 必须与当前 Windows manifest、逻辑证明副本和提交的源码脚本一致。其余 Linux 工具与证明步骤仍保持冻结。

## 2. 保留本次 Windows 证据

形式验证必须绑定本次 Windows 运行的原始报告、工具 manifest、九个 RTL 输入和 18 个 `postabc.il`。不要修改原始报告中的 `formal_status=PENDING`；形式结果另存，通过 SHA-256 关联原始测量报告。

`source/bundle_native_evidence.py` 可在 Windows 测量全部完成后，复制完整证据到一个全新目录。在主包根目录运行：

```powershell
.\runtime\python.exe -I -S .\source\bundle_native_evidence.py `
  --package . `
  --report .\latest-current.json `
  --output ..\windows-evidence
```

`windows-evidence` 必须尚不存在。脚本保留全部测量记录，不重新运行综合；生成的根目录包含：

- `report.json`：原始 Windows 报告的逐字节副本。
- `manifest.json`、`cases_current.json`、`run_current_cases.py`、`windows_metrics.py`。
- 原始 RTL、完整测量日志和实际 18 个 post-ABC 网表。
- 原版/候选 EXE、资源与 DLL，以及根目录共享 ABC。
- `evidence-inventory.json`：每个证据文件的 SHA-256 和字节数。

若使用随交付提供的既有证据目录，可以省略这次复制；仍需使用该证据目录自己的报告和 inventory 摘要。`source/prove_windows_native_once.py` 会检查两侧 EXE 的实际字节、共享 ABC 的实际位置、清单及网表绑定；不会用旧版本 EXE 的固定哈希代替本轮身份。

## 3. 可选的冻结 Linux EQY 工具包

可另行提供的工具包为：

| 项目 | 值 |
|---|---|
| 文件名 | `FPGA-topic2-v23-EQY-Linux-0.69-20261027.tar.gz` |
| 大小 | 43,472,415 字节，约 41.46 MiB |
| 归档 SHA-256 | `35a75c08bb0f32b6727203341c8162b4a0ce7c8b5a5b787d114bd2b8e7f9ba46` |
| `portable-index.json` SHA-256 | `ac50f798b70f4a105f8ad42e12ed16b03bb9ed87ce2ff2ad0194cdf66c4c6cd9` |

它是独立附件，不是主 Windows 包运行所需的组件。文件名中的 v23 表示冻结工具包的制作版本。该包同时保留了历史 Windows 证据；本节复用其工具及模型，新的证明对象由 `--bundle` 明确指定。

运行条件为 Linux x86_64，或兼容的 WSL2 Linux x86_64 环境；需要可执行的文件系统、`/proc`、`/dev/null`、`/bin/sh` 和可写输出空间。以下命令使用常见 Linux 工具 `tar`、`sha256sum`、`awk`。工具包自身包含 CPython 3.10、标准库及 Click、原版 Yosys 0.69/ABC/资源文件、EQY 0.69、SBY 0.68、witness、所需命令和动态库闭包。SAT/ABC PDR 策略不要求另装 SMT solver。

请用 Linux 的 `tar` 解压，以保留执行权限。工具包及工作目录使用 ASCII 路径，不含空格、引号或反斜杠。不要直接修改工具包的清单文件、脚本或旧证据。

## 4. 重定位后生成父级 manifest，再派生本轮脚本绑定

下面的目录名是可替换的示例，不依赖开发者电脑的路径。把主 Windows 包和 `windows-evidence` 放到 Linux 可以访问的目录中，按如下组织：

```text
review/
  windows-package/                         主 Windows 包
  windows-evidence/                        本轮 Windows 证据
  FPGA-topic2-v23-EQY-Linux-0.69-20261027/   独立工具包解压目录
  proof-current/                          新证明输出，开始时不得存在
```

先在 `review` 中检查归档摘要与上表相同，再解压到尚无同名目录的位置：

```bash
sha256sum FPGA-topic2-v23-EQY-Linux-0.69-20261027.tar.gz
tar -xzf FPGA-topic2-v23-EQY-Linux-0.69-20261027.tar.gz
```

在 `review` 目录中设置当前路径，并让冻结工具包生成符合本机解压位置的新 manifest：

```bash
KIT="$(pwd)/FPGA-topic2-v23-EQY-Linux-0.69-20261027"
SUBMISSION="$(pwd)/windows-package"
BUNDLE="$(pwd)/windows-evidence"

"$KIT/run_verify.sh" --preflight-only \
  --output "$KIT/results/local-preflight"

MANIFEST="$KIT/results/local-preflight/proof-tool-manifest.json"
MANIFEST_SHA=$(sha256sum "$MANIFEST" | awk '{print $1}')
REPORT_SHA=$(sha256sum "$BUNDLE/report.json" | awk '{print $1}')
INVENTORY_SHA=$(sha256sum "$BUNDLE/evidence-inventory.json" | awk '{print $1}')
```

`local-preflight` 必须是新目录。此命令检查冻结包、版本和依赖，并根据**当前**工具目录生成父级路径 manifest；不会启动 18 项形式证明。它同时检查工具包自带的历史证据身份，因此不要把这个 `PREFLIGHT_PASS` 当作当前作品已通过证明。

父级冻结manifest保留原来的F7脚本身份，其文件不被改写。v26当前Windows对象采用F3脚本，不能篡改父级记录以装作两者相同。正式运行时，新入口在新输出的 `inputs/linux-proof-tool-manifest.json` 生成派生manifest，字段差异必须恰好为以下三项：

| 字段 | 派生值 |
|---|---|
| `abc_script` | 本轮Windows证据包内实际候选脚本的路径 |
| `abc_script_sha256` | 该实际脚本的SHA-256 |
| `windows_recipe_binding` | 新增对象，记录父级manifest摘要、本轮Windows报告摘要及只绑定脚本身份的范围说明 |

其余字段保持相同，包括Linux解析器、ABC、EQY/SBY、模型、proof wrappers与证明策略。父级snapshot保存为 `inputs/frozen-linux-proof-tool-manifest.json`。派生动作只更新Windows对象的来源脚本身份；Linux证明不会执行该候选综合脚本，不会生成Linux候选网表替代Windows网表。冻结kit及其父级manifest保持原字节。

随后对明确指定的本轮 Windows 证据执行：

```bash
"$KIT/runtime/bin/python3" -I -S -B \
  "$SUBMISSION/source/prove_windows_native_once.py" \
  --run-proofs \
  --kit "$KIT" \
  --manifest "$MANIFEST" \
  --manifest-sha256 "$MANIFEST_SHA" \
  --bundle "$BUNDLE" \
  --windows-report-sha256 "$REPORT_SHA" \
  --inventory-sha256 "$INVENTORY_SHA" \
  --output "$(pwd)/proof-current"
```

需要先只检查当前证据时，将 `--run-proofs` 换为 `--preflight-only`；该模式不创建证明输出。正式证明可以随后使用同一个尚未创建的输出路径。实际证明开始后，失败或中断也应保留目录，下一次使用新目录。

不要直接运行冻结包的 `run_verify.sh` 默认证明模式来表示当前作品通过：默认模式证明的是该工具包中封存的历史对象。也不要把旧 `onsite_kit.py proof` 作为本次入口；旧现场套件绑定的是另一套 Linux 构建流程。这里使用本机新生成的 manifest 加上当前 `--bundle`，才能绑定实际 Windows 对象。

入口复算冻结工具和输入清单，保留原始 Windows 字节，只允许可逆的 CRLF→LF 换行转换。18 个正确网表分别对其 RTL 证明；负对照使用固定 Linux 工具生成故意错误的 test2 网表，并要求检出反例。不会使用 Linux 候选重新综合的网表替换 Windows 的 18 个被测对象。

## 5. 审阅输出

查看新输出目录中的：

- `launch.json`：入口状态、工具/报告身份、实际命令及完整性检查。`frozen_linux_proof_manifest_sha256` 绑定父级，`linux_proof_manifest_sha256` 绑定实际派生manifest；不能将两者混用。
- `inputs/frozen-linux-proof-tool-manifest.json`：未经改写的父级快照。
- `inputs/linux-proof-tool-manifest.json`：本轮实际传给冻结helper的派生manifest。
- `inputs/`其余文件、`verified-inputs.json`：原始Windows元数据快照、派生文件及输入指纹清单。
- `process.log`：完整运行日志。
- `formal/report.json`：九例两侧共 18 项证明及负对照。
- `formal/<case>/<role>/`：归一化网表、审核记录、EQY 配置、日志和证明产物。

成功必须同时满足：`status=PASS`、`positive_proof_counts={"PASS":18}`、`negative_control.status=EXPECTED_COUNTEREXAMPLE`；报告中的 `windows_report_sha256` 必须等于本轮Windows `report.json` 的摘要，Windows manifest/EXE/RTLIL绑定也须一致。`formal/report.json` 中的 `linux_proof_manifest_sha256` 必须等于派生manifest实际摘要和 `launch.json` 同名字段；父级摘要单独核对。`derived_manifest_changed_fields` 必须恰好包含上述三项，实际逐字段差异也必须一致；`windows_unified_abc_script.sha256` 必须匹配本轮Windows脚本。入口返回0才表示这一整套检查通过。

形式通过说明这些被测网表与相应 RTL 等价。面积和 Windows 性能结论来自原始 Windows 测量；EQY 的 Linux 耗时、负对照和工具预检不能替代性能验收。

## 6. 验证脚本所需的 repo 结构

直接调用 `verify_windows_current.py` 时，`--repo` 不是任意源码目录。它至少需要：

```text
repo/
  cases_current.json
  competition_case/...                  与清单一致的九个 RTL
  clean-v11/formal_cycloneiv.v           规范 dffeas 功能模型
  scripts/verify_current_cases.py         核心证明辅助脚本
  scripts/verify_windows_current.py
  ... manifest 指定的 Linux Yosys/ABC/EQY/SBY、插件、模块和资源
```

上述冻结工具包已经提供这套结构，因此本说明的入口把 `--repo` 指向 kit。只有 Windows 主包内两份 Python 验证脚本，不能替代这些模型、资源和 Linux 可执行程序。

`formal_cycloneiv.v` 的规范模型保留动态低有效异步清零；其 SHA-256 为 `3d96aa4532000389a4ac2998cef702b7a4ed46b23707b4e0dd4cb1688b4db2d2`。模型不能随意改为常量复位或简化触发器。父级和派生Linux manifest分别保留工具、EQY插件/模块、proof wrappers及对应ABC脚本身份；不能把Windows脚本身份更新扩展为更换证明工具或简化模型。

如自行安装工具而不使用独立冻结包，需要提供上述结构和对应身份清单，再通过 `verify_windows_current.py --repo ... --manifest ... --bundle ... --output ...` 验证。该环境应单独记录版本、指纹及验证结果；不能沿用冻结包的完整性结论。通用包装入口 `prove_windows_native_once.py` 当前只接受本说明中指定的冻结 kit。
