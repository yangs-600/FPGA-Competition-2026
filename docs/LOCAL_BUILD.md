# 在当前 Ubuntu 上构建仓库中的 v14

本机仓库位置为 `/home/ubuntu/FPGA/FPGA-Competition-2026`。仓库中的 `clean-v11` 文件名和目录名兼容历史入口，当前算法来自提交 `c9b5d9c` 的 v14。

## 构建与完整验证

```bash
cd /home/ubuntu/FPGA/FPGA-Competition-2026
/usr/bin/python3 -E -u scripts/build_current.py --dependencies /home/ubuntu/FPGA --jobs 1
```

脚本使用仓库中的当前源码和补丁，创建 `clean-v11/toolchains/yosys-0.69/src` 与 `build-repro`，从源码构建原版基线，然后使用本次新编译的对象构建 v14。不会复制旧环境的二进制或编译缓存。2026-10-10 本轮原版构建中途将并行度从 1 调整为 2，保留本轮已经编译的对象继续；对应的主动终止与继续记录保留在日志中。

随后编译匹配 Yosys 0.69 的 EQY 插件，生成真实工具清单，执行四个用例的 8 路等价证明、实际错误输出的反例测试、21 次交错 CPU/RSS 测量、11 个 v14 夹具，以及补充的进程树 PSS 测量。

原始依赖保留在仓库之外：

- `/home/ubuntu/FPGA/clean-v11/toolchains/yosys-0.69/source.tar.gz`
- `/home/ubuntu/FPGA/clean-v11/toolchains/eqy-0.69/source.tar`
- `/home/ubuntu/FPGA/toolchains/cmake-3.31.6/`
- `/home/ubuntu/oss-cad-suite/`
- 系统 GCC/G++、Make、Git、Bison、Flex、pkg-config 和 Tcl/readline/libffi/zlib 开发依赖。

两个源码包在复制及解压前验证 SHA-256：

```text
Yosys: 086045e23253917b93c71fc2d9db495df3c153cdc5d212bac505df7c4ad62e2f
EQY:   dd1a4c5edcf83353c66e9765661cc332f4c7f6f122585c97da68290eab230291
```

这是利用本机保留依赖的构建入口；队友机器若没有这些依赖，仍须按相同版本准备。脚本不是自动下载安装器。

## 构建完成后运行

快速检查：

```bash
cd /home/ubuntu/FPGA/FPGA-Competition-2026
/usr/bin/python3 -E -u scripts/run_current.py --repeats 3
```

完整 CPU/RSS 回归：

```bash
/usr/bin/python3 -E -u scripts/run_current.py --repeats 21
```

补充夹具：

```bash
/usr/bin/python3 -E -u clean-v11/test_shared_tree.py
```

需要在终端直接调用本仓库的优化版 Yosys 时，使用：

```bash
source scripts/activate_competition.sh
yosys -V
yosys -Q -T -p 'pmux_competition_opt'
```

最后一条应显示 `Executing PMUX_COMPETITION_OPT v14.`。仅检查 `yosys -V` 只能确认 Yosys 基础版本，不能区分 PMUX 算法版本。

## 证据和边界

构建状态和结果：`clean-v11/local-build-v14-status.json`、`local-build-v14-receipt.json`。详细编译与验证日志：`clean-v11/toolchains/yosys-0.69/rebuild-logs/`。本轮验证摘要位于 `validation/local-v14/summary.json`。

本轮验收结果：四个公开用例的 8 路证明、真实错误输出反例、11 个独立夹具和 v14 激活入口均通过。LUT 降幅算术平均值为 22.11038961038961%；DFF 和其他已出现的非 LUT 单元均未增加。21 次测量中，各例 CPU 变化约为 -2.70%、-2.72%、-4.60%、-5.31%；补充进程树 PSS 最大增幅出现在 test2，约 +0.18%，其余三个用例均下降。详细数据以验证摘要和原始报告为准。

仓库内的新清单固定源码、补丁、程序及 ABC 脚本的哈希。修改算法源码后需要重新编译并更新真实清单；不应继续用旧程序验证新代码。构建入口遇到输入改变会停止，避免复用错误基线。

Linux CPU/RSS 和 PSS 数据用于本机交叉检查。功能 PASS 不等于性能限制已经通过，应同时检查回执中的两个性能布尔字段。这次 Linux 复现也不代替比赛最终 Windows 环境和官方资源统计方式的验收。
