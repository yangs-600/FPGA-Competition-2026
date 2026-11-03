# Yosys 0.69 PMUX Windows 原生 v26 候选

在新的英文路径解压后运行 run_cases.cmd；已包含Windows EXE、公共ABC、DLL和Python运行时。综合和性能测量无需Ubuntu或WSL。source/PROOF_REPLAY_GUIDE.md另行说明Linux EQY如何证明本包实际Windows网表，主包不包含Linux工具。

本包保留原版v25基线的原字节，候选是在相同v25配置和旧对象基础上仅重编PMUX并重新链接，同时统一使用外部F3 ABC脚本。这不是两侧重新全量编译的v26构建。完整父构建和增量记录在build-records；源码独立重建入口在source/BUILD_WINDOWS.md。

当前v26尚未验收，不继承v25的资源、性能或形式证明结论。最终指南和验收材料待本包实际结果完成后再冻结。
