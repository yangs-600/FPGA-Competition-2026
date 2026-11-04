"""Select one proof backend after Windows measurements; never hide proof failures."""
from datetime import datetime, timezone
import importlib.util
from pathlib import Path


def load(root, name):
    spec = importlib.util.spec_from_file_location(name, root/(name+'.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def suite_path(root, override=None):
    if override is None:
        lines = [s.strip() for s in (root/'oss_cad_suite_path.txt').read_text(encoding='utf-8-sig').splitlines() if s.strip()]
        if len(lines) != 1:
            raise ValueError('oss_cad_suite_path.txt 应只有一行路径。')
        override = lines[0]
    path = Path(override).expanduser()
    if path.anchor and not path.is_absolute():
        raise ValueError('请填写完整绝对路径或相对代码目录的普通路径。')
    return (path if path.is_absolute() else root/path).resolve()


def run_formal(root, report_path, backend='auto', oss_suite=None, wsl_distro=None):
    root, report_path = Path(root).resolve(), Path(report_path).resolve()
    start = datetime.now(timezone.utc).isoformat()
    chosen = backend
    try:
        if backend not in ('auto', 'windows', 'wsl'):
            raise ValueError('Unknown formal backend: '+str(backend))
        if oss_suite and (backend == 'wsl' or wsl_distro):
            raise ValueError('Windows 套件路径不能与 WSL 后端或发行版参数同时指定。')
        if wsl_distro and backend == 'windows':
            raise ValueError('Windows 后端不能指定 WSL 发行版。')
        if wsl_distro and backend == 'auto':
            backend = chosen = 'wsl'
        # An explicit suite path means Windows was requested, even if it is missing.
        install = suite_path(root, oss_suite) if backend != 'wsl' else None
        if backend == 'auto':
            chosen = 'windows' if oss_suite is not None or install.exists() else 'wsl'
        print('本轮形式证明后端：'+chosen, flush=True)
        if chosen == 'windows':
            if not install.is_dir():
                raise RuntimeError('没有找到预装 Windows OSS CAD Suite：'+str(install)+
                                   '。请修改 oss_cad_suite_path.txt，或明确选择 --backend wsl。')
            result = load(root, 'native_formal').run_formal(root, report_path, install)
        else:
            load(root, 'setup_wsl_eqy').ensure_setup(root, distro=wsl_distro)
            result = load(root, 'demo_formal').run_formal(root, report_path)
        result['backend'] = chosen
        result['automatic_fallback_after_failure'] = False
        return result
    except Exception as error:
        return {'status':'ERROR', 'backend':chosen, 'started_at':start,
                'completed_at':datetime.now(timezone.utc).isoformat(),
                'positive_proof_counts':{}, 'negative_control':{'status':'NOT_COMPLETED'},
                'error':str(error), 'automatic_fallback_after_failure':False}
