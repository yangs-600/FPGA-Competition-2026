# v11 清洁构建复现与当前入口

独立工程：`/home/ubuntu/FPGA/clean-v11`。从已校验的 v11 审阅包抽取原版 0.69 源码、最终补丁和原始四用例，不复制旧对象文件、CMake 缓存或旧程序。编译器启动器关闭，CCACHE_DISABLE=1。原版所有目标重新编译；候选使用本次刚编译的基线对象和最终补丁，完全没有使用旧工程构建产物。EQY 插件也在新目录重建。

这是同一 Ubuntu、同一编译器及依赖下的清洁构建，不是另一台系统的独立复现。OSS CAD Suite 和 `/home/ubuntu/FPGA/toolchains/cmake-3.31.6` 是保留的依赖。

复现结果：四例原版/候选 LUT 286/221、25/15、12/12、35/26；DFF 222/222、0/0、17/12、10/10。平均 LUT 缩减率 22.11038961038961%。8 路正向证明、真实错误负对照、6 个边界用例全部通过。21 次 CPU/ru_maxrss 复测均通过，进程树 PSS 最大增幅约 2.18%；PSS 采样不能替代尚未提供的官方内存计量脚本。

复现发现并修复了交付补丁的 CRLF 兼容问题：三个补丁上下文文件归一化为 LF，逐字节确认归一化内容与官方 Git 提交一致后应用补丁。初次失败日志保留，成功续建使用的仍是本次全新基线。最终证据为 `clean-v11/clean-reproduction.json` 和新目录内各份日志；不能把旧 `clean-failure.json` 单独当作最终状态。

## 当前使用

清理后项目根目录保留转发入口：

```bash
cd ~/FPGA
python3 run_current.py
source ./activate_competition.sh
yosys -V
```

也可直接在 `~/FPGA/clean-v11` 运行 run_current.py、test_shared_tree.py 和 measure_competition_v11_pss.py。最终源码在该目录的 pmux_competition_v11.cc，实际编译源码位于 toolchains/yosys-0.69/src；源码归档、最终补丁、构建配置、EQY 清单和证明证据一起保留。修改算法后必须重新构建、更新程序/源码哈希清单并完整验证；现有报告只对应已锁定版本。

`start_clean_v11.py` 是一次性建立新目录的脚本；发现 clean-v11 已存在会拒绝覆盖。重新做整套清洁复现应选择另一个空目录并按 bootstrap.json 中记录的依赖路径准备环境，不能删除当前唯一工作版本后直接重跑。

## 清理边界与回退

清理仅限 `/home/ubuntu/FPGA` 内旧工具链、旧构建结果、已淘汰候选和历史实验文件。原始 competition_case、原始测试夹具、编辑器配置、CMake 与 OSS CAD Suite 保留。

所有清单内旧文件先打包到 cleanup-legacy-backup.zip，传至 Windows 后校验整包 SHA256 和包内每个文件，才允许删除原路径；文件内容发生变化或仍被进程使用会阻断删除。删除清单、备份路径和磁盘结果以 cleanup-plan.json、cleanup-windows-verified.json、cleanup-result.json 为准。旧历史文档内的路径不会自动迁移，仅作为归档记录。

本轮结果支持软件可复现性，但仍需核对官方计数字段和正式内存统计口径，不能宣称全部赛项要求已获官方认证。
