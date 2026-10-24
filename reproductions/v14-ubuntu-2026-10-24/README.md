# v14 Ubuntu 独立复现包（2026-10-24）

本目录只新增在 **zWang 分支**，不改该分支原有源码，不修改 main。实际测试对象是最新 main 快照 `2791affaa80b9bdf637cae5f60511056aec6d8ab`，在新的 workspace 里恢复；请不要把本分支根目录的旧算法误当成 v14。

已从源码构建 Yosys 0.69 原版、内置 v14 的候选版、固定子模块 ABC，并构建/安装 EQY、SBY。没有修改优化算法。四例 LUT 为 **286→221、25→15、12→12、35→26**；DFF 均未增加。纯 LUT 平均降幅 22.1104%，LUT+独立 NOT 口径为 21.8924%。27 组等价证明通过，两个故意错误负例均被检出。本次本机性能采样通过 5% 检查，**不代表 Windows 或隐藏用例验收通过**。

## 队友最快重跑

需要 Linux x86_64；推荐 Ubuntu 22.04/WSL2 Ubuntu，Python3、Git、python3-click，以及系统的 glibc、libstdc++、zlib。若缺 Python 依赖，可先 `sudo apt install git python3 python3-click`。不能直接在原生 Windows 运行这些 Linux 二进制。

从 GitHub 下载/克隆 zWang 分支后：

```bash
cd reproductions/v14-ubuntu-2026-10-24
python3 prepare.py
cd workspace
python3 local-repro/validate.py --repeats 21
```

`prepare.py` 默认恢复到全新的 `workspace/`；若目录已存在会拒绝覆盖。可以用 `--destination /另一个/不存在的/无空格目录` 指定位置。它核对压缩包和产物 SHA256，恢复固定项目快照，重新定位启动脚本和真实工具清单；**不是创建一个空清单假装依赖齐全**。默认路径不下载东西，也不依赖原作者目录。

重跑会依次执行四例最终网表 EQY、实际 ABC9 后 ILANG EQY、11 个边界用例，以及 21 对完整综合的耗时和根 Yosys 内存采样。结果在 `workspace/local-repro/result.json`，完整证明日志在其报告引用的目录。只重跑仓库四例可在 workspace 执行 `python3 scripts/run_current.py --repeats 21`。

## 从源码重新编译两版（可选）

需要 GCC/G++、make、pkg-config、zlib 开发文件，例如 Ubuntu 的 `build-essential pkg-config zlib1g-dev`。包内附带 CMake 3.31.6、Flex 2.6.4、Bison 3.8.2；不会 sudo 安装它们。

```bash
python3 prepare.py --mode source --destination ./workspace-source
cd workspace-source
python3 local-repro/build.py --jobs 4
python3 local-repro/validate.py --repeats 21
```

源码模式不装已有 Yosys/ABC 二进制或对象文件。源码包包含固定 Git 对象和子模块，以及实际测试的补丁状态；准备脚本只在新目录反向应用该精确补丁、验证源码干净，再由 build.py 先编译原版、冻结其哈希，再应用原补丁编译候选。两版编译选项相同，ABC 不修改。源码模式适用于受支持 Linux；不是 Windows 原生构建脚本。

固定版本：Yosys `9f75ca1f9834a39a863915b5dae0c7b1e33533bc`；ABC `a51bf4a7bb38ce06ea3a544b1463b40832213917`；EQY `4a72eb94fc253062464afee4d0018359017bb846`；SBY `b1a1e98cba941ec8433f8dc27f416cd7bb7f14be`。SBY 的 v0.68/v0.69/v0.70 标签恰好指向同一提交，脚本验证 v0.69 标签后指定相应显示版本。

## 文件与证据

| 文件 | 内容 |
|---|---|
| `prepare.py` | 完整性核对、独立恢复、路径重定位；拒绝覆盖已有目录 |
| `scripts/build.py` | 两版同配置的源码构建、ABC 哈希冻结及真实 manifest 生成 |
| `scripts/validate.py` | 原仓库测试调用与根进程采样汇总；区分功能和效率状态 |
| `assets/project-v14.bundle` | 固定项目提交的 Git 离线快照，不包含私人 Git 配置 |
| `assets/runtime-linux-x86_64.tar.gz` | 实际编译的 Yosys/ABC、share 数据、EQY/SBY 和清单 |
| `assets/toolchain-source.tar.gz` | 对应完整源码及 Git 子模块元数据；无编译对象 |
| `assets/build-tools-linux-x86_64.tar.gz` | 本地 CMake/Flex/Bison 及其随附文档/许可 |
| `assets/evidence.tar.gz` | 本轮原始网表、证明、负例和测量/构建日志 |
| `reports/` | 发布前本机报告和原始 JSON，原绝对路径保留作溯源 |
| `package.json` | 包内文件 SHA256、平台和来源元数据 |

查看详细结果：[本轮原始报告](reports/复现报告.md)、[原始采样汇总](reports/result.json)。报告中本机绝对路径/相对链接反映原测试环境，队友需解压 evidence 后按同名目录查看，不代表需要访问该作者电脑。

发布前还在另一全新目录恢复了二进制包，重新运行 27 组等价验证、两个负例及 3 对测量，均通过，见 [路径迁移复验](reports/relocation-smoke.json)。这次 3 对运行仅用于检查分发包，21 对原始性能数据仍以 result.json 为准。源码恢复模式也已实测，恢复出的 Yosys/SBY Git 工作区干净；没有在恢复目录再次耗时完整重编译一遍。重复指定已有目标目录会被拒绝，不会覆盖源码。

展开完整证据（独立目录，不改源码）：

```bash
mkdir evidence
tar -xzf assets/evidence.tar.gz -C evidence
```

根 Yosys VmHWM 以约 1ms 间隔采样，可能遗漏退出前最后瞬间的新峰值；原始样本和首对运行均保留。原仓库脚本顶层 PASS 不单独代表效率合规，本包额外区分相关字段。没有重跑千级压力集，也没有解决此前发现的隐藏用例退化风险。

## 许可与发布边界

项目和上游组件保留各自许可。对应 Yosys/ABC/EQY/SBY 完整源码在源码压缩包；各组件 COPYING/LICENSE 以及 CMake/Flex/Bison 随附许可位于各自原始目录，未移除。二进制可能依赖系统动态库，不能只复制一个 yosys 文件。GitHub 的源码压缩包下载会包含这些 Git 跟踪资产；本目录不是正式竞赛最终提交包。
