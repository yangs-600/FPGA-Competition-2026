# 赛题二：Yosys 0.69 PMUX 优化 v24（九用例）

当前源码为 `v24-bounded-search`。它在 v23 基础上减少共享选择树搜索的无效计算：某次排列的部分图节点数达到已有最优值时，提前丢弃该排列。第一次完整建图、严格更优的更新规则、相同成本保留首个结果的规则均不变。没有修改原版程序、其他 pass、ABC 二进制或固定 ABC 脚本。

九例 `LUT + NOT` 的逐例降幅算术平均仍为 **20.6610330696%**，各例资源与 v23 相同；DFF 单独记录。Windows 实际输出的18项等价证明和82项边界回归通过，错误输出负对照也通过。Linux 编译、证明及本机默认入口状态由 `validation/current-v24-20261027/summary.json` 记录；旧 v23 证据保留。

**严格效率仍未通过，不能称所有赛题和答疑要求全部完成。** 本轮 Windows test1 首次为原版0.3160236秒、候选1.2226647秒，增加286.89%；追加五对均值增加2.08%，但含首轮的五对/六对平均仍超过15%。九例采用已公开的追加五对解释时，选定墙钟、根峰值工作集及Job CPU均不超过原版5%；这不等同于主办方已确认该解释。根峰值工作集不含ABC；root CPU另有超5%项目，不能与Job CPU混用。

同SHA原版程序的独立副本对照也出现首次迟滞：预热后0.349秒、新副本首次1.185秒、第二次0.363秒。这说明该现象不要求新增PMUX代码存在，未确定具体系统根因。详见 [启动对照与效率记录](docs/STARTUP_IDENTITY_CONTROL_V24_20261027.md)。FAQ的不足1秒资格和复核5次是否含首轮尚有歧义，不能自行以筛除不利样本代替验收。

固定算法微基准中，test1的PMUX区间平均从2.069742毫秒降为2.002332毫秒（约3.26%，其中一对略慢）；六选择位结构从14.457800毫秒降为7.903640毫秒（约45.33%）。这是重复pass的诊断，不是完整综合评分。九例及该结构的变换结果经两处NEW_ID源行号精确重命名后逐字一致，ID数字、连接与属性不变。独立55结构/9592排列检查也通过。

在 Ubuntu 仓库根目录运行：

```bash
/usr/bin/python3 -E -B -u scripts/run_current.py
```

激活默认 manifest 的工具：

```bash
source scripts/activate_competition.sh
yosys -V
```

源码在 `src/pmux_competition_v11.cc`，镜像在 `clean-v11/pmux_competition_v11.cc`。`scripts/build_current.py` 和 [构建说明](docs/LOCAL_BUILD.md) 用于其他机器重建。本轮复用匹配的0.69编译对象，不是清洁全编译复现。九例输入 `cases_current.json` 和固定 ABC 脚本保持原字节。

Windows 运行包为 `FPGA-topic2-v24-Windows-0.69-20261027.zip`，ASCII路径解压后运行 `run_cases.cmd`。包外SHA与迁移检查收据说明交付状态。EQY在Linux/WSL上证明实际Windows输出，不据此把WSL称作赛事提交方案。

本轮修改尚未提交或推送GitHub。旧版工具、历史包、全部首轮样本、诊断准备失败记录均保留；团队分工按用户要求暂缓填写。
