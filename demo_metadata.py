"""Presentation metadata; never used to select or alter measurement samples."""
import ctypes
from datetime import datetime
import hashlib
import html
import json
import os
from pathlib import Path
import platform
import re
import shutil
import struct
import subprocess
import sys
from urllib.parse import quote


def _stamp():
    return datetime.now().astimezone().isoformat(timespec='milliseconds')


def _run(args, cwd=None, timeout=10, env=None):
    try:
        p = subprocess.run([str(x) for x in args], cwd=cwd, env=env,
                           capture_output=True, timeout=timeout,
                           creationflags=0x08000000 if os.name == 'nt' else 0)
        return {'status': 'observed' if p.returncode == 0 else 'unavailable',
                'exit_code': p.returncode,
                'stdout': p.stdout.decode('utf-8', errors='replace').strip()[:8000],
                'stderr': p.stderr.decode('utf-8', errors='replace').strip()[:2000]}
    except (OSError, subprocess.TimeoutExpired) as e:
        return {'status': 'unavailable', 'error': type(e).__name__}


def _file(root, name):
    rel = Path(name)
    if rel.is_absolute() or rel.drive or '..' in rel.parts:
        raise ValueError('Expected package-relative file')
    p = (root / rel).resolve()
    p.relative_to(root)
    return p


def _read(root, name):
    try:
        value = json.loads(_file(root, name).read_text(encoding='utf-8-sig'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def capture_environment(root):
    """One bounded, privacy-minimised snapshot; no Yosys/ABC execution."""
    root = Path(root).resolve()
    data = {'started_at': _stamp(), 'platform': platform.platform(),
            'machine_architecture': platform.machine(),
            'python': {'version': sys.version, 'executable': sys.executable,
                       'bits': struct.calcsize('P') * 8},
            'terminal': {k: os.environ[k] for k in ('TERM_PROGRAM', 'TERM_PROGRAM_VERSION')
                         if os.environ.get(k)},
            'logical_processors_python': os.cpu_count(),
            'snapshot_scope': 'Before/after snapshots only; no temperature, background-process or continuous-load monitoring.'}
    try:
        disk = shutil.disk_usage(root)
        data['disk'] = {'status': 'observed', 'volume': root.anchor,
                        'total_bytes': disk.total, 'free_bytes': disk.free}
    except OSError as e:
        data['disk'] = {'status': 'unavailable', 'error': type(e).__name__}
    data['cim'] = data['memory'] = data['power'] = {'status': 'unavailable'}
    if os.name == 'nt':
        ps = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
        script = """$ErrorActionPreference='Stop';[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false);
$o=Get-CimInstance Win32_OperatingSystem -OperationTimeoutSec 3;
$c=@(Get-CimInstance Win32_Processor -OperationTimeoutSec 3);
[ordered]@{os_caption=$o.Caption;os_version=$o.Version;os_build=$o.BuildNumber;os_architecture=$o.OSArchitecture;
cpu=@($c|ForEach-Object{[ordered]@{name=$_.Name;cores=$_.NumberOfCores;logical_processors=$_.NumberOfLogicalProcessors}})}|ConvertTo-Json -Depth 4 -Compress"""
        raw = _run([ps, '-NoProfile', '-NonInteractive', '-Command', script], timeout=12)
        try:
            data['cim'] = {'status': 'observed', 'values': json.loads(raw['stdout'])} if raw['status'] == 'observed' else raw
        except (KeyError, ValueError):
            data['cim'] = {'status': 'unavailable', 'error': 'CIM output was not JSON'}
        try:
            class MemoryStatus(ctypes.Structure):
                _fields_ = [('length', ctypes.c_uint32), ('load', ctypes.c_uint32)] + [
                    (n, ctypes.c_uint64) for n in ('total', 'available', 'total_page', 'available_page',
                                                  'total_virtual', 'available_virtual', 'extended')]
            mem = MemoryStatus()
            mem.length = ctypes.sizeof(mem)
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            if not kernel.GlobalMemoryStatusEx(ctypes.byref(mem)):
                raise OSError('GlobalMemoryStatusEx failed')
            data['memory'] = {'status': 'observed', 'source': 'GlobalMemoryStatusEx',
                              'total_physical_bytes': mem.total,
                              'available_physical_bytes': mem.available, 'memory_load_percent': mem.load}
            class PowerStatus(ctypes.Structure):
                _fields_ = [(n, ctypes.c_ubyte) for n in ('ac', 'flag', 'percent', 'saver')] + [
                    ('life', ctypes.c_uint32), ('full_life', ctypes.c_uint32)]
            power = PowerStatus()
            if not kernel.GetSystemPowerStatus(ctypes.byref(power)):
                raise OSError('GetSystemPowerStatus failed')
            data['power'] = {'status': 'observed', 'source': 'GetSystemPowerStatus',
                             'ac_line_status': {0: 'battery', 1: 'AC', 255: 'unknown'}.get(power.ac, 'unknown'),
                             'battery_percent': None if power.percent == 255 else power.percent,
                             'battery_saver': bool(power.saver)}
        except (OSError, AttributeError) as e:
            data['power'] = {'status': 'unavailable', 'error': type(e).__name__}
        scheme = "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false); powercfg.exe /getactivescheme"
        data['power_scheme'] = _run([ps, '-NoProfile', '-NonInteractive', '-Command', scheme], timeout=5)
    else:
        data['power_scheme'] = {'status': 'unavailable', 'error': 'Windows-only metadata'}
    data['completed_at'] = _stamp()
    return data


def finish_metadata(root, report, before, command):
    """Bind metadata to this report; tool version probes run after measurements."""
    root = Path(root).resolve()
    after = capture_environment(root)
    manifest = _read(root, 'manifest.json')
    release = _read(root, 'repository-release.json')
    prepared = _read(root, 'build-records/prepared.json')
    parity = _read(root, 'build-records/pair-config-parity.json')
    config = _read(root, 'build-records/parent-v25/configure-candidate/started.json')
    report_name = report['directory'] + '/report.json'
    bound_report = _file(root, report_name)
    data = {'schema': 'windows-demo-environment-v1', 'generated_at': _stamp(),
            'report_path': report_name, 'report_sha256': _digest(bound_report),
            'report_directory': report['directory'], 'before': before, 'after': after,
            'measurement_command': [str(x) for x in command],
            'version_probe_timing': 'After all synthesis measurements and report creation; excluded from measured samples.',
            'declared': {k: manifest.get(k) for k in ('yosys_release', 'yosys_commit', 'candidate_version',
                          'build_mode', 'build_mode_code', 'version_note', 'compiler_compatibility_option')},
            'files': [], 'versions': {}}
    data['declared'].update(release_name=release.get('release_name'),
        abc_source_commit=manifest.get('source_origin_check', {}).get('submodule_gitlinks', {}).get('abc'),
        flags=prepared.get('flags'), common_flags_record_status=parity.get('status'),
        cmake_options=[x for x in config.get('command', []) if x.startswith(('-DCMAKE_BUILD_TYPE=',
            '-DCMAKE_CXX_FLAGS=', '-DCMAKE_INTERPROCEDURAL_OPTIMIZATION=', '-DBUILD_SHARED_LIBS=',
            '-DYOSYS_WITHOUT_TCL=', '-DYOSYS_COMPONENTS='))])
    try:
        log = _file(root, 'build-records/parent-v25/configure-candidate/cmake.log').read_text(encoding='utf-8', errors='replace')
        match = re.search(r'The CXX compiler identification is ([^\r\n]+)', log)
        data['declared']['compiler'] = match.group(1) if match else None
    except OSError:
        data['declared']['compiler'] = None
    def pin(name, expected=None, source='manifest.json'):
        entry = {'path': name, 'declared_sha256': expected, 'declaration_source': source}
        try:
            entry['actual_sha256'] = _digest(_file(root, name))
            entry['matches'] = entry['actual_sha256'].lower() == expected.lower() if expected else None
            entry['status'] = ('match' if entry['matches'] else 'mismatch') if expected else 'observed_only'
        except (OSError, ValueError, TypeError):
            entry.update(status='unavailable', matches=None, actual_sha256=None)
        data['files'].append(entry)
    pin('manifest.json', report.get('manifest_sha256'), '本轮 report.json')
    pin('cases_current.json', report.get('case_manifest_sha256'), '本轮 report.json')
    pin('run_current_cases.py', report.get('harness_sha256'), '本轮 report.json')
    pin('windows_metrics.py', report.get('meter_sha256'), '本轮 report.json')
    for role in ('baseline', 'candidate'):
        observed = {r.get('roles', {}).get(role, {}).get('executable_sha256') for r in report.get('cases', [])}
        observed.discard(None)
        expected = next(iter(observed)) if len(observed) == 1 else None
        pin('yosys-' + role + '.exe', expected, '本轮各例 executable_sha256')
    pin('yosys-abc.exe', manifest.get('shared_files', {}).get('yosys-abc.exe'))
    pin('source/pmux_competition_v11.cc', manifest.get('source_sha256'))
    pin('source/synth-intel-competition.patch', manifest.get('source_patch_sha256'))
    pin('share/intel/competition_abc_v11.abc', manifest.get('script_sha256'))
    pin('runtime/python.exe', manifest.get('runtime_sha256', {}).get('python.exe'))
    for name in ('run_demo.py', 'run_demo.cmd', 'demo_metadata.py', 'demo_formal.py'):
        pin(name, release.get('repository_files', {}).get(name, {}).get('sha256'), 'repository-release.json')
    for row in report.get('cases', []):
        if row.get('source_path'):
            pin(row['source_path'], row.get('source_sha256'), '本轮用例 source_sha256')
    try:
        data['abc_script'] = _file(root, 'share/intel/competition_abc_v11.abc').read_text(encoding='utf-8').strip()
    except OSError:
        data['abc_script'] = None
    env = dict(os.environ)
    env['PATH'] = str(root) + ';' + os.environ.get('SystemRoot', 'C:/Windows') + '/System32'
    env['YOSYS_DATDIR'] = str(root / 'share')
    for key in ('ABC', 'YOSYS_ABC'):
        env.pop(key, None)
    for name, args in [('baseline', ['yosys-baseline.exe', '-V']),
                       ('candidate', ['yosys-candidate.exe', '-V']),
                       ('abc', ['yosys-abc.exe', '-c', 'version'])]:
        data['versions'][name] = dict(_run([root / args[0]] + args[1:], cwd=root, timeout=5, env=env),
                                     observed_at=_stamp())
    data['identity_status'] = 'MATCH' if data['files'] and all(x['status'] == 'match' for x in data['files']) else 'CHECK_DETAILS'
    data['completed_at'] = _stamp()
    return data


def _s(value):
    if value is None or value == '':
        return '未采集 / unavailable'
    return html.escape(str(value), quote=False).replace('|', '\\|').replace('\r', '').replace('\n', '<br>')


def _table(headers, rows):
    return ['| ' + ' | '.join(headers) + ' |', '|' + '|'.join(['---'] * len(headers)) + '|'] + [
        '| ' + ' | '.join(_s(x) for x in r) + ' |' for r in rows]


def _gib(value):
    return None if value is None else f'{value / 2**30:.3f} GiB'


def _link(label, path):
    return '[' + label + '](' + quote(str(path).replace('\\', '/'), safe='/.:_-') + ')'


def render_intro(meta, report):
    before, after = meta.get('before', {}), meta.get('after', {})
    cim = before.get('cim', {}).get('values', {})
    cpus = cim.get('cpu', [])
    if isinstance(cpus, dict):
        cpus = [cpus]
    physical = sum(x.get('cores', 0) or 0 for x in cpus) or None
    logical = sum(x.get('logical_processors', 0) or 0 for x in cpus) or before.get('logical_processors_python')
    mem, mem_end = before.get('memory', {}), after.get('memory', {})
    power = before.get('power', {})
    lines = ['## 测试环境与版本', '',
             '环境数据由本次运行入口在测量前、测量后采集；下面同时区分本轮观测与随包构建记录。', '']
    rows = [('测试开始（原报告时区）', report.get('started_utc')),
            ('测试结束（原报告时区）', report.get('completed_utc')),
            ('环境快照（开始 / 结束）', f"{before.get('started_at', 'unavailable')} / {after.get('started_at', 'unavailable')}"),
            ('系统（本轮 report.json）', report.get('platform')),
            ('系统名称 / 构建 / 位数（CIM）', ' / '.join(str(cim.get(k) or 'unavailable') for k in ('os_caption', 'os_build', 'os_architecture'))),
            ('CPU 型号', '; '.join(str(x.get('name', '')) for x in cpus)),
            ('物理核心 / 逻辑处理器', f'{physical or "unavailable"} / {logical or "unavailable"}'),
            ('物理内存总量', _gib(mem.get('total_physical_bytes'))),
            ('可用物理内存（开始 / 结束）', f"{_gib(mem.get('available_physical_bytes')) or 'unavailable'} / {_gib(mem_end.get('available_physical_bytes')) or 'unavailable'}"),
            ('代码包所在卷 / 总容量 / 开始可用', f"{before.get('disk', {}).get('volume', 'unavailable')} / {_gib(before.get('disk', {}).get('total_bytes')) or 'unavailable'} / {_gib(before.get('disk', {}).get('free_bytes')) or 'unavailable'}"),
            ('供电（开始 / 结束）', f"{power.get('ac_line_status', 'unavailable')} / {after.get('power', {}).get('ac_line_status', 'unavailable')}"),
            ('当前电源方案（开始）', before.get('power_scheme', {}).get('stdout')),
            ('Python（本入口进程）', before.get('python', {}).get('version')),
            ('Python 位数', before.get('python', {}).get('bits')),
            ('终端声明 TERM_PROGRAM / VERSION', json.dumps(before.get('terminal', {}), ensure_ascii=False))]
    lines += _table(['项目', '记录值'], rows)
    decl = meta.get('declared', {})
    lines += ['', '终端字段为空表示未设置，不能据此认定由 VS Code 启动。Python 是测试入口运行时；下述编译器属于历史构建环境。', '']
    versions = [('发布名称（声明）', decl.get('release_name')),
                ('Yosys 上游版本 / 提交（声明）', f"{decl.get('yosys_release')} / {decl.get('yosys_commit')}"),
                ('优化版本（声明）', decl.get('candidate_version')),
                ('ABC 源码提交（声明）', decl.get('abc_source_commit'))]
    for key, label in [('baseline', '原版 Yosys'), ('candidate', '优化版 Yosys'), ('abc', 'ABC')]:
        item = meta.get('versions', {}).get(key, {})
        versions.append((label + ' 版本输出（测量后）', item.get('stdout') if item.get('status') == 'observed' else None))
    versions += [('构建编译器（CMake 记录）', decl.get('compiler')),
                 ('编译参数（构建记录）', decl.get('flags')),
                 ('关键 CMake 选项（构建记录）', '; '.join(decl.get('cmake_options', []))),
                 ('构建方式（声明）', decl.get('build_mode')),
                 ('版本时间戳说明（声明）', decl.get('version_note')),
                 ('文件与本轮/随包声明对照', meta.get('identity_status'))]
    lines += _table(['项目', '版本 / 说明'], versions)
    lines += ['', '工具版本命令均在本轮测量完成后执行，不计入性能样本；文件完整标识见文末。', '']
    return lines


def render_appendix(meta, report, out_name):
    rows = report.get('cases', [])
    completed = sum('absolute_limits_pass' in r and all(
        r.get('roles', {}).get(role, {}).get('formal_object_status') == 'EXPORTED_NOT_PROVED'
        for role in ('baseline', 'candidate')) for r in rows)
    reviewed = sum(bool(r.get('review_triggered')) for r in rows)
    first_ok = sum(all(r.get('first_pair_overheads', {}).get(k, float('inf')) <= 5
                       for k in ('wall_overhead_percent', 'memory_overhead_percent')) for r in rows)
    warmups = sum(len(r.get('warmup_samples', [])) for r in rows)
    measured = sum(len(v.get('samples', [])) for r in rows for v in r.get('roles', {}).values())
    selected = sum(v.get('selected_summary', {}).get('sample_count', 0) for r in rows for v in r.get('roles', {}).values())
    lines = ['', '## 7. 测试方法与输入', '',
             f'本轮有 {len(rows)} 例记录，其中 {completed} 例已完成测量及证明对象导出；首轮时间和内存增幅均≤5%的有 {first_ok} 例，触发复核 {reviewed} 例。', '',
             f'原版预运行共 {warmups} 次；正式测量（原版与优化版合计，含保留的首轮与复核）共 {measured} 次，最终统计采用 {selected} 个样本。', '',
             '计分资源 = LUT + 独立 NOT；单例降幅 = (原版资源 − 优化资源) / 原版资源 ×100%；平均降幅为九个单例降幅的算术平均。DFF 单列，不加入该资源降幅。', '',
             '时间/内存增幅 = (优化值 / 原版值 −1) ×100%。复核时分别取五次的均值，再计算两均值之比，不是逐对百分比的均值。', '',
             '每例十次原版预运行后，按“原版→优化版”执行首对。两次均小于1秒且任一增幅>5%时追加固定五对；首对独立保留，不计入复核均值。其余用例沿用首对。该解释尚未另获主办方书面确认。', '',
             '计时从 Windows 进程创建前至 Yosys 退出，含读取、完整综合、ABC 等待及网表输出；不包括 C++ 编译、环境采集、独立审计或 EQY。内存取根进程 PeakWorkingSetSize；CPU 补充项含 Job Object 后代。', '',
             '绝对限值对优化版全部正式样本检查：耗时≤60秒、根进程峰值≤2,000,000,000字节。120秒是测试进程的故障终止超时，不是合格限值。MiB=2²⁰字节，GiB=2³⁰字节。', '',
             '所有用例统一执行 `synth_intel -family cycloneiv -top <top>` 并经过 ABC9；候选版统一使用以下脚本：', '',
             '```text', meta.get('abc_script') or 'unavailable', '```', '',
             '| 用例 | 顶层模块 | RTL 输入 |', '|---|---|---|']
    for r in rows:
        src = r.get('source_path')
        lines.append('| ' + _s(r.get('name')) + ' | ' + _s(r.get('top')) + ' | ' + (_link(src, '../../' + src) if src else 'unavailable') + ' |')
    lines += ['', '## 8. 逐次样本与证据', '', '<details>', '<summary>展开全部首轮与复核样本（秒 / MiB）</summary>', '']
    sample_rows = []
    for r in rows:
        pairs = [('首轮', r.get('first_pair', {}))] + [('复核' + str(i + 1), p) for i, p in enumerate(r.get('review_pairs', []))]
        for label, pair in pairs:
            b, c = pair.get('baseline', {}), pair.get('candidate', {})
            fmt = lambda d, k, divisor=1: f'{d[k] / divisor:.6f}' if k in d else None
            sample_rows.append([r.get('name'), label, fmt(b, 'wall_seconds'), fmt(c, 'wall_seconds'),
                                fmt(b, 'peak_working_set_bytes', 2**20), fmt(c, 'peak_working_set_bytes', 2**20)])
    lines += _table(['用例', '样本', '原版秒', '优化秒', '原版MiB', '优化MiB'], sample_rows)
    lines += ['', '</details>', '',
              '- 原始测量报告：' + _link('report.json', '../../' + out_name + '/report.json'),
              '- 本轮环境与版本记录：' + _link('environment.json', out_name + '-environment.json'),
              '- 独立审计记录：' + _link('audit.json', out_name + '-audit.json'),
              '- 本轮 Windows 测量终端日志：' + _link('console.log', out_name + '-console.log'), '',
              '| 用例 | 原版流程 / 日志 / 证明对象 | 优化流程 / 日志 / 证明对象 |', '|---|---|---|']
    for r in rows:
        cols = []
        for role in ('baseline', 'candidate'):
            info = r.get('roles', {}).get(role, {})
            p = info.get('path')
            if not p:
                cols.append('未建立')
                continue
            links = [_link('flow.ys', '../../' + p + '/flow.ys')]
            if r.get('first_pair', {}).get(role, {}).get('log'):
                links.append(_link('first.log', '../../' + p + '/first.log'))
            if info.get('formal_object_status') == 'EXPORTED_NOT_PROVED':
                links.append(_link('postabc.il', '../../' + p + '/postabc.il'))
            else:
                links.append('证明对象未完成导出')
            cols.append(' / '.join(links))
        lines.append('| ' + _s(r.get('name')) + ' | ' + ' | '.join(cols) + ' |')
    lines += ['', '表中只为标记为已导出的 `postabc.il` 提供链接；导出与计数一致检查不等同于形式等价证明。原始测量报告的 `formal_status=PENDING` 保留测量结束时的状态；本轮是否完成 EQY，以第6节另存且绑定本轮报告的证明结果为准。', '',
              '<details>', '<summary>展开完整文件标识与声明对照</summary>', '',
              f'本轮 report.json SHA-256：`{meta.get("report_sha256", "unavailable")}`', '']
    lines += _table(['文件', '实际 SHA-256（测量后读取）', '声明 SHA-256', '来源 / 对照'], [
        [v['path'], v.get('actual_sha256'), v.get('declared_sha256'), v.get('declaration_source', '') + ' / ' + v.get('status', '')]
        for v in meta.get('files', [])])
    lines += ['', '</details>', '', '## 9. 复现与适用范围', '',
              '在解压目录运行：', '', '```powershell', '.\\run_demo.cmd', '```', '',
              '本轮内部测量调用（完整参数）：', '', '```text',
              subprocess.list2cmdline(meta.get('measurement_command', [])), '```', '',
              '环境信息仅为开始与结束快照，没有持续监测温度、频率、后台负载，也未证明系统处于空闲。结果限于本电脑与这九个输入，不能据此保证所有≤1000节点电路或后续每轮都一次通过。', '',
              '开始快照之后的测试进程准备、预运行及正式综合会改变缓存和系统状态；本入口未主动清空操作系统页缓存。版本查询、报告整理在测量之后完成，不计入性能指标。', '']
    return lines
