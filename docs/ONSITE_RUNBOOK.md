# v24 WSL 现场构建、测量和证明步骤

以下在 WSL Ubuntu 24.04 x86_64 终端操作。系统须已有 GCC/G++ 13、binutils、git、dpkg-deb、Python 3.12 及配方对应运行库；归档携带其余精确构建依赖。需要 `/proc` 与 own-child ptrace。保留这份 `onsite20261027` 附录的目录结构，并在其根目录打开终端。

本轮已完整演练：新目录离线构建→新角色/新 manifest→唯一一次固定测量→新角色 18 项 EQY。原版编译约 466 秒，候选增量约 6 秒；这只是本机观察，现场先检查可用空间和系统版本，不临时替换编译器。

## 1. 设置位置、核验和解包

下面的 archive 是当前电脑的文件位置，换电脑时改成实际收到的归档。新目录必须不存在、位于 Linux 文件系统、使用 ASCII 且无空格。已有目录不要删除，换新后缀。

```bash
onsite_support="$PWD"
archive='/mnt/d/杨森宇/FPGA/FPGA-topic2-v24-WSL-0.69-20261027.tar.gz'
sha256sum "$archive"
```

应得到 `17aa6b6ed1d4794b40cabf9787ddc01e941826635fc1e51eea77e680e8b02301`。相符后：

```bash
onsite_extract="$HOME/fpga-v24-onsite-extract-02"
mkdir "$onsite_extract"
tar -xzf "$archive" -C "$onsite_extract"
onsite_pkg="$onsite_extract/FPGA-topic2-v24-WSL-0.69-20261027"
sh "$onsite_pkg/run.sh" verify
```

`PACKAGE_HASHES_MATCH` 只表示文件校验通过，没有启动 Yosys。

## 2. 全新目录离线构建

```bash
/usr/bin/g++ -dumpversion
/usr/bin/python3 --version
df -h "$HOME"
onsite_build="$HOME/fpga-v24-onsite-build-02"
sh "$onsite_pkg/offline-build/build.sh" "$onsite_build"
```

G++ 主版本应为 `13`。新目录内有 `build-receipt.json`、`roles/baseline`、`roles/candidate` 和完整 `logs/`。收据需为 `BUILD_COMPLETE_NOT_EXECUTED`、`abc_identical: true`，候选源码 SHA 为 README 所列 v24。这个状态还不是性能或形式证明通过。

配方从新的源码/对象目录编译原版和 ABC，再在同一轮未变化对象基础上编译候选。准确说法是“干净原版＋候选增量”；不是两侧分别从零全量构建。保留收据、环境和日志。

## 3. 用新构建角色建立新测量

本步骤使用附录新增入口。它核对冻结包全部文件、新 build receipt、源码/patch/flags 和实际新角色，复制到新目录并写新 manifest，不复制旧成绩。

先阅读接口不会运行候选：

```bash
/usr/bin/python3 -E -B "$onsite_support/measurement/stage_rebuilt_measurement.py" --help
```

若决定按固定协议执行一次：

```bash
/usr/bin/python3 -E -B "$onsite_support/measurement/stage_rebuilt_measurement.py" \
  --package "$onsite_pkg" \
  --build-root "$onsite_build" \
  --output "$HOME/fpga-v24-onsite-measurement-02" \
  --run
```

去掉 `--run` 时仅准备目录、不执行任何 Yosys。输出目录一旦存在，入口总是拒绝复用；如先做只 stage 演练，应为那次准备另一个目录，不把它作为重复尝试正式成绩的入口。

测量采用冻结 `a738…` runner：每例原版预热 10 次，先原版后候选，同次测时间和根内存；仅按预先声明的短例规则追加五对。完整保留首轮。正式测量时不要并行编译/证明、不要提前执行新目录候选 `-V`；后台条件按组织方安排保持一致，脚本不更改安全设置。

输出包括：

```text
manifest.json / stage-receipt.json / provenance/build-receipt.json
run-once.json / measurement-process.log
latest-current.json / efficiency-interpretation-view-v2.json
validation-once/（逐例日志、sidecar、保留网表）
```

检查 `run-once.json` 的退出码和 `input_tools_unchanged`；再查看 raw 的九例、面积及首轮/复核视图。完成状态仍是 `RAW_MEASUREMENTS_COMPLETE_REVIEW_AND_FORMAL_REQUIRED`，视图仍是 `RAW_MEASUREMENT_INTERPRETATION_REQUIRES_CONFIRMATION`，不是官方全验收标记。不要只看 exit 0 就省略首轮数据。

冻结包自身的 `run.sh measure` 只使用包内旧角色，不能替代上面的新构建入口。`run.sh check --output 新目录` 是搬迁综合计数检查，没有性能或 EQY 结论。

## 4. 用新构建角色复跑 18 项 EQY

另准备完整的 `FPGA-topic2-v23-EQY-Linux-0.69-20261027` kit，在 ASCII Linux 路径解包。以下 `onsite_kit` 必须指向实际解包根；在新机器上按收到的文件位置设置，不沿用别人的主机路径。

```bash
onsite_kit="$HOME/fpga-proof-kit/FPGA-topic2-v23-EQY-Linux-0.69-20261027"
sh "$onsite_support/proof/run_proof.sh" \
  --package "$onsite_pkg" \
  --proof-kit "$onsite_kit" \
  --roles-root "$onsite_build/roles" \
  --build-receipt "$onsite_build/build-receipt.json" \
  --output "$HOME/fpga-v24-onsite-proof-02"
```

入口核验 kit 索引 `ac50f798b70f4a105f8ad42e12ed16b03bb9ed87ce2ff2ad0194cdf66c4c6cd9`，用新角色另外综合后证明，不借历史 PASS。`roles-root` 与 `build-receipt` 必须同时提供；省略时验证的是旧包角色。新输出必须不存在。

成功条件为 `ONSITE_FRESH_FORMAL_PASS`、18 PASS、常零错误输出 `EXPECTED_COUNTEREXAMPLE`。该链另次生成未计时的 post-ABC 网表，与同 ELF/RTL 的性能计数绑定，不直接证明计时进程内部对象；不同路径可能产生不同 IL 字节，不能把 cell 数相同表述为逐字一致。

## 5. 保存与交付

分别保存新 build receipt、测量 raw/view/全部样本、证明报告/日志/索引，并列出各自摘要。新的文件应和旧结果同时保留。发现非零退出、缺失退出事件、摘要不符、样本缺失时停止引用该轮为有效成绩，先保留现场和原因；不通过改状态、删除首轮或多跑取最好值处理。

当前演练的实际目录为 `~/fpga-v24-wsl-onsite-build-20261027`、`~/fpga-v24-onsite-measurement-20261027`、`~/fpga-v24-onsite-proof-20261027/run-once`。这些目录已完成，**不能复制以上命令的输出参数来再次复用它们**。
