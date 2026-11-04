"""Run the frozen Windows harness once and display only the resulting fresh data."""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

def combined_result(measurement_status, runner_exit, audit_status, formal_status, measurements_only=False, audit_exit_code=0):
    if audit_status != 'INDEPENDENT_AUDIT_PASS' or audit_exit_code != 0:
        return 'VALIDATION_INCOMPLETE', runner_exit or 1
    measured_pass = runner_exit == 0 and measurement_status == 'MEASUREMENTS_PASS_FORMAL_PENDING'
    measured_exit = 0 if measured_pass else (runner_exit or 2)
    if measurements_only:
        return measurement_status, measured_exit
    if formal_status != 'PASS':
        prefix = 'MEASUREMENTS_PASS' if measured_pass else 'MEASUREMENTS_REVIEW'
        return prefix + '_FORMAL_' + formal_status, measured_exit or 3
    return ('MEASUREMENTS_AND_FORMAL_PASS' if measured_pass else 'MEASUREMENTS_REVIEW_FORMAL_PASS'), measured_exit

def _main_unlocked():
    ap = argparse.ArgumentParser()
    ap.add_argument('--package', type=Path, default=Path(__file__).resolve().parent,
                    help='Package directory; defaults to the directory containing this script')
    ap.add_argument('--measurements-only', action='store_true', help='Skip EQY; measure the nine cases only')
    ap.add_argument('--formal-backend', choices=('auto','windows','wsl'), default='auto')
    ap.add_argument('--oss-suite')
    ap.add_argument('--wsl-distro')
    args = ap.parse_args()
    root = args.package.resolve()
    # -I excludes the script directory from sys.path; load the bundled helper explicitly.
    spec = importlib.util.spec_from_file_location('demo_metadata', root/'demo_metadata.py')
    metadata_helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(metadata_helper)
    rspec = importlib.util.spec_from_file_location('compact_report', root/'compact_report.py')
    report_helper = importlib.util.module_from_spec(rspec)
    rspec.loader.exec_module(report_helper)
    demo = root/'tmp'/'demo-results'
    demo.mkdir(parents=True, exist_ok=True)
    before = {p.name for p in root.glob('validation-current-*') if p.is_dir()}
    start = datetime.now(timezone.utc)
    (demo/'latest-results.md').write_text(
        '# 本轮测试正在运行\n\n'
        f'启动时间：{start.astimezone().isoformat()}\n\n'
        '本轮尚未生成完整报告。若运行报错，请查看终端和 latest-console.log；'
        '此前各轮结果仍保留在同目录的 validation-current-*-results.md 中。\n', encoding='utf-8')
    print('开始九例测试。' + (' EQY：不执行。' if args.measurements_only else ' EQY：测量完成后执行。'), flush=True)
    cmd = [str(root/'runtime/python.exe'), '-I', '-S', '-X', 'utf8', '-u',
           str(root/'run_current_cases.py'), '--package', str(root), '--timeout', '120']
    environment_before = metadata_helper.capture_environment(root)
    (demo/'latest-environment-start.json').write_text(
        json.dumps(environment_before, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    with (demo/'latest-console.log').open('w', encoding='utf-8') as log:
        process = subprocess.Popen(cmd, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, encoding='utf-8', errors='replace')
        completed_cases = 0
        for line in process.stdout:
            # Retain the unabridged subprocess output in the log.
            log.write(line)
            log.flush()
            if ' logic ' in line and ' wall% ' in line and ' peak% ' in line:
                completed_cases += 1
                print(f'[{completed_cases}/9] {line.split()[0]} 测量完成', flush=True)
        exit_code = process.wait()
    if exit_code != 0:
        print(f'测量退出码：{exit_code}；日志末尾：', flush=True)
        print(''.join((demo/'latest-console.log').read_text(encoding='utf-8').splitlines(True)[-12:]), flush=True)
    latest = root/'latest-current.json'
    if not latest.exists():
        raise RuntimeError('本轮未生成报告，请看终端错误；不读取旧成绩。')
    report = json.loads(latest.read_text(encoding='utf-8'))
    out = (root/report['directory']).resolve()
    created = {p.name for p in root.glob('validation-current-*') if p.is_dir()} - before
    if out.parent != root or created != {out.name} or datetime.fromisoformat(report['started_utc']) < start:
        raise RuntimeError('没有确认到唯一的本轮新报告；请勿同时运行多个测试。不显示可能混淆的结果。')
    report_path = out/'report.json'
    if report_path.read_bytes() != latest.read_bytes():
        raise RuntimeError('本轮报告与最新镜像不一致')
    metadata = metadata_helper.finish_metadata(root, report, environment_before, cmd)
    environment_path = demo/(out.name+'-environment.json')
    environment_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    rows = report['cases']
    complete = report.get('status') in ('MEASUREMENTS_PASS_FORMAL_PENDING', 'MEASUREMENTS_REVIEW_FORMAL_PENDING') and len(rows)==9 and all('absolute_limits_pass' in r for r in rows) and 'average_gain_percent' in report
    audit_file = demo/(out.name+'-audit.json')
    audit_cmd = [str(root/'runtime/python.exe'), '-I', '-S', '-X', 'utf8',
                 str(root/'evidence/audit_native_measurements.py'), '--package', str(root),
                 '--report', str(report_path), '--output', str(audit_file)]
    audit_status = '未执行（测试未完成）'
    audit_exit_code = None
    if complete:
        audit = subprocess.run(audit_cmd, cwd=root, capture_output=True, text=True, encoding='utf-8', errors='replace')
        audit_exit_code = audit.returncode
        (demo/(out.name+'-audit-console.log')).write_text(audit.stdout+audit.stderr,encoding='utf-8')
        if audit_file.exists():
            audit_status = json.loads(audit_file.read_text(encoding='utf-8')).get('status', '无状态')
        else:
            audit_status = '审计未完成，见日志'
    formal = {'status': 'NOT_REQUESTED' if args.measurements_only else 'NOT_RUN',
              'error': None if args.measurements_only else '测量或独立审计未完成，未启动证明。'}
    if not args.measurements_only and complete and audit_status == 'INDEPENDENT_AUDIT_PASS' and audit_exit_code == 0:
        (demo/'latest-results.md').write_text(
            '# 本轮性能测量完成，形式证明正在运行\n\n'
            f'原始测量状态：{report["status"]}；独立审计：{audit_status}。\n\n'
            f'[本轮测量报告](../../{out.name}/report.json)\n\n'
            '正在对本轮 Windows 网表执行 EQY。完整结果将在证明结束后更新。\n', encoding='utf-8')
        print('测量完成，开始 EQY。', flush=True)
        try:
            fspec = importlib.util.spec_from_file_location('formal_dispatch', root/'formal_dispatch.py')
            formal_helper = importlib.util.module_from_spec(fspec)
            fspec.loader.exec_module(formal_helper)
            formal = formal_helper.run_formal(root, report_path, args.formal_backend, args.oss_suite, args.wsl_distro)
        except Exception as error:
            formal = {'status': 'ERROR', 'error': f'{type(error).__name__}: {error}'}
    formal_file = demo/(out.name+'-formal.json')
    formal_file.write_text(json.dumps(formal, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    overall_status, final_exit_code = combined_result(report['status'], exit_code, audit_status,
                                                    formal.get('status', 'ERROR'), args.measurements_only, audit_exit_code)
    stamp = datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %z')
    text, terminal_text = report_helper.render(report, metadata, formal, overall_status,
                                               final_exit_code, audit_status, stamp)
    (demo/(out.name+'-console.log')).write_bytes((demo/'latest-console.log').read_bytes())
    (demo/'latest-results.md').write_text(text,encoding='utf-8')
    (demo/(out.name+'-results.md')).write_text(text,encoding='utf-8')
    (demo/'latest-run.json').write_text(json.dumps({'report':str(report_path),'exit_code':final_exit_code,'runner_exit_code':exit_code,'audit_exit_code':audit_exit_code,'audit_status':audit_status,
         'run_started_utc':start.isoformat(),'vscode_term_program':os.environ.get('TERM_PROGRAM'),'summary':str(demo/'latest-results.md'),
         'environment':str(environment_path),'report_format_version':'5.0','overall_status':overall_status,
         'formal_backend':formal.get('backend'),'formal_status':formal.get('status'),'formal_record':str(formal_file)},indent=2)+'\n',encoding='utf-8')
    print('\n'+terminal_text,flush=True)
    print('测试文档：', demo/'latest-results.md', flush=True)
    return final_exit_code

def main():
    # Persistent single-byte lock: close releases it even after an interrupted run.
    if '--help' in sys.argv or '-h' in sys.argv:
        return _main_unlocked()
    import msvcrt
    probe = argparse.ArgumentParser(add_help=False)
    probe.add_argument('--package', type=Path, default=Path(__file__).resolve().parent)
    known, _ = probe.parse_known_args()
    directory = known.package.resolve()/'tmp'
    directory.mkdir(parents=True, exist_ok=True)
    with (directory/'portable-run.lock').open('a+b') as handle:
        if handle.tell() == 0:
            handle.write(b'0')
            handle.flush()
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            print('同一代码目录已有测试运行，请等待结束；本次没有启动新测试。', flush=True)
            return 4
        try:
            return _main_unlocked()
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


if __name__ == '__main__':
    raise SystemExit(main())
