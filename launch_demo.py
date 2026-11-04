"""Portable launchers use the package interpreter and keep the selected mode explicit."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=('measurements','full'), required=True)
    parser.add_argument('--package', type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument('--backend', choices=('auto','windows','wsl'), default='auto')
    parser.add_argument('--oss-suite')
    parser.add_argument('--wsl-distro')
    parser.add_argument('--no-pause', action='store_true')
    parser.add_argument('--measurements-only', action='store_true')
    args = parser.parse_args()
    root = args.package.resolve()
    mode = 'measurements' if args.measurements_only else args.mode
    code = 2
    started = None
    try:
        if not root.as_posix().isascii() or any(c.isspace() for c in str(root)):
            raise RuntimeError('请将代码包解压到英文无空格路径，例如 D:\\FPGA-Windows；当前工具不支持中文或空格路径。')
        command = [str(root/'runtime/python.exe'), '-I','-S','-B','-X','utf8','-u',
                   str(root/'run_demo.py'), '--package',str(root)]
        if mode == 'measurements':
            if args.oss_suite or args.wsl_distro or args.backend != 'auto':
                raise RuntimeError('本入口不执行 EQY。要使用证明环境参数，请运行 run_full.cmd。')
            command += ['--measurements-only']
            print('九例综合与性能测试（不执行 EQY）。', flush=True)
        else:
            if args.oss_suite and (args.backend == 'wsl' or args.wsl_distro):
                raise RuntimeError('Windows 套件路径不能与 WSL 后端或发行版参数同时指定。')
            if args.wsl_distro and args.backend == 'windows':
                raise RuntimeError('Windows 后端不能指定 WSL 发行版。')
            command += ['--formal-backend',args.backend]
            if args.oss_suite:
                command += ['--oss-suite',args.oss_suite]
            if args.wsl_distro:
                command += ['--wsl-distro',args.wsl_distro]
            print('完整验证：九例测量 + EQY。', flush=True)
        started = datetime.now(timezone.utc)
        code = subprocess.call(command, cwd=root)
    except (OSError, RuntimeError) as error:
        print('启动失败：'+str(error), flush=True)
    except KeyboardInterrupt:
        print('运行被中断，不能视为通过。', flush=True)
        code = 130
    print('入口退出码：',code, flush=True)
    fresh = False
    try:
        receipt = json.loads((root/'tmp/demo-results/latest-run.json').read_text(encoding='utf-8'))
        fresh = started is not None and datetime.fromisoformat(receipt['run_started_utc']) >= started
    except (OSError, ValueError, KeyError, TypeError):
        pass
    if fresh:
        print('本轮结果：',root/'tmp/demo-results/latest-results.md', flush=True)
    else:
        print('本次未生成新的完整报告，请看终端错误；目录中的既有报告不能作为本次结果。', flush=True)
    if not args.no_pause:
        try:
            input('按回车关闭窗口……')
        except (EOFError, KeyboardInterrupt):
            pass
    return code


if __name__ == '__main__':
    raise SystemExit(main())
