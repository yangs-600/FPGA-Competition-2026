"""Configure the bundled frozen Linux proof kit in an existing WSL distro.

No system installation, sudo, network, global PATH change or proof is performed.
Call only after Windows performance measurements have completed.
"""
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile
import uuid

KIT_NAME = 'FPGA-topic2-v23-EQY-Linux-0.69-20261027'
ARCHIVE_NAME = KIT_NAME + '.tar.gz'
ARCHIVE_SHA256 = '35a75c08bb0f32b6727203341c8162b4a0ce7c8b5a5b787d114bd2b8e7f9ba46'
ARCHIVE_BYTES = 43472415
INDEX_SHA256 = 'ac50f798b70f4a105f8ad42e12ed16b03bb9ed87ce2ff2ad0194cdf66c4c6cd9'
NO_WINDOW = 0x08000000 if os.name == 'nt' else 0


def _now():
    return datetime.now(timezone.utc).isoformat()


def _sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for data in iter(lambda: f.read(1024*1024), b''):
            h.update(data)
    return h.hexdigest()


def _save(path, value):
    path = Path(path)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    os.replace(temp, path)


def _decode(data):
    if b'\x00' in data:
        return data.decode('utf-16-le', errors='replace').lstrip('\ufeff')
    return data.decode('utf-8', errors='replace').lstrip('\ufeff')


def _linux_path(value):
    return isinstance(value, str) and bool(re.fullmatch(r'/[A-Za-z0-9_./-]+', value)) and '..' not in value.split('/')


def _run(command, log, *, stdin=None, timeout=45):
    p = subprocess.run(command, input=stdin.encode('utf-8') if stdin is not None else None,
                       capture_output=True, timeout=timeout, creationflags=NO_WINDOW)
    log.write_text(json.dumps(command, ensure_ascii=False)+'\nSTDOUT:\n'+_decode(p.stdout)+
                   '\nSTDERR:\n'+_decode(p.stderr)+'\nEXIT: '+str(p.returncode)+'\n', encoding='utf-8')
    if p.returncode:
        raise RuntimeError('WSL 配置命令失败，退出码 '+str(p.returncode)+'；日志：'+str(log))
    return _decode(p.stdout).strip()


def _check_archive(archive):
    if not archive.is_file():
        raise RuntimeError('缺少随包 Linux EQY 工具归档：'+str(archive))
    if archive.stat().st_size != ARCHIVE_BYTES or _sha(archive) != ARCHIVE_SHA256:
        raise RuntimeError('随包 Linux EQY 归档大小或 SHA-256 不匹配，停止配置；请重新完整解压代码包。')
    index = None
    with tarfile.open(archive, 'r:gz') as tar:
        for item in tar:
            name = PurePosixPath(item.name)
            if (name.is_absolute() or '..' in name.parts or not name.parts or name.parts[0] != KIT_NAME
                    or not (item.isfile() or item.isdir())):
                raise RuntimeError('Linux 工具归档包含不安全成员：'+item.name)
            if item.name == KIT_NAME+'/portable-index.json':
                data = tar.extractfile(item).read()
                if hashlib.sha256(data).hexdigest() != INDEX_SHA256:
                    raise RuntimeError('Linux 工具归档索引不匹配。')
                index = json.loads(data)
    if not index or not isinstance(index.get('files'), dict):
        raise RuntimeError('Linux 工具归档没有有效索引。')
    checks = []
    for name, digest in index['files'].items():
        path = PurePosixPath(name)
        if (path.is_absolute() or '..' in path.parts or not re.fullmatch(r'[A-Za-z0-9_./+-]+', name)
                or not re.fullmatch(r'[0-9a-f]{64}', digest)):
            raise RuntimeError('Linux 工具索引含不支持的成员路径。')
        checks.append(digest+'  '+name+'\n')
    return ''.join(checks)


BOOTSTRAP = r'''set -eu
PATH=/usr/bin:/bin; export PATH
unset LD_LIBRARY_PATH LD_PRELOAD PYTHONHOME PYTHONPATH PYTHONUSERBASE BASH_ENV ENV CDPATH
[ "$(uname -m)" = x86_64 ] || { echo 'Linux x86_64 is required' >&2; exit 11; }
for cmd in tar sha256sum mktemp id readlink timeout; do command -v "$cmd" >/dev/null; done
[ -r /proc/self/stat ] && [ -c /dev/null ] || exit 12
archive=$1; prefix=$2; kitname=$3; expected=$4; indexsha=$5
[ "$(sha256sum "$archive" | cut -d ' ' -f 1)" = "$expected" ] || exit 13
# Prefer the user's home filesystem. Use /var/tmp only if HOME is unsuitable.
case ${HOME:-} in
  /*) case "$HOME" in *[!A-Za-z0-9_./-]*|*/../*|*/..) base=/var/tmp;; *) base="$HOME/.local/share/fpga-eqy";; esac;;
  *) base=/var/tmp;;
esac
mkdir -p "$base"
base=$(readlink -f "$base")
case "$base" in /*) ;; *) exit 14;; esac
case "$base" in *[!A-Za-z0-9_./-]*) echo 'Install filesystem path must be ASCII without spaces' >&2; exit 14;; esac
install=$(mktemp -d "$base/fpga-eqy-$(id -u)-$prefix-XXXXXXXX")
chmod 700 "$install"
# The authenticated archive was also checked for traversal, symlinks and special files.
tar -xzf "$archive" -C "$install" --no-same-owner
kit="$install/$kitname"
[ "$(sha256sum "$kit/portable-index.json" | cut -d ' ' -f 1)" = "$indexsha" ] || exit 15
[ -x "$kit/run_verify.sh" ] && [ -x "$kit/runtime/bin/python3" ] || exit 16
printf '%s\n' "$kit"
'''

CHECK_KIT = r'''set -eu
PATH=/usr/bin:/bin; export PATH
kit=$1; expected=$2; checks=$3
[ "$(uname -m)" = x86_64 ] || exit 11
[ -d "$kit" ] && [ ! -L "$kit" ] || exit 17
[ "$(readlink -f "$kit")" = "$kit" ] || exit 17
[ "$(stat -c %u "$kit")" = "$(id -u)" ] || exit 18
[ "$(sha256sum "$kit/portable-index.json" | cut -d ' ' -f 1)" = "$expected" ] || exit 15
cd "$kit"
sha256sum --quiet -c "$checks"
[ -x "$kit/run_verify.sh" ] && [ -x "$kit/runtime/bin/python3" ] || exit 16
printf 'KIT_IDENTITY_OK\n'
'''


def ensure_setup(root, distro=None):
    """Return config and atomically write this machine's WSL configuration.

    Raises on absent/unusable WSL, changed archive, failed preflight or unsafe paths.
    The saved setup receipt says PREFLIGHT_PASS only, never a proof PASS.
    """
    root = Path(root).resolve(strict=True)
    if os.name != 'nt':
        raise RuntimeError('WSL 配置入口应在 Windows 运行。')
    if not re.fullmatch(r'[A-Za-z]:\\[A-Za-z0-9_.\\/-]+', str(root)):
        raise RuntimeError('当前证明工具要求代码包放在英文无空格目录，例如 D:\\FPGA-Windows；也不支持网络 UNC 路径。')
    archive = root/'proof-tools'/ARCHIVE_NAME
    checks_text = _check_archive(archive)
    tmp = root/'tmp'
    tmp.mkdir(exist_ok=True)
    lock = tmp/'eqy-setup.lock'
    try:
        lock.mkdir()
    except FileExistsError:
        raise RuntimeError('此目录已有 WSL 配置任务或其锁文件。请勿同时启动；确认旧任务已退出后再移除 tmp/eqy-setup.lock。')
    attempt = tmp/'eqy-setup'/uuid.uuid4().hex
    attempt.mkdir(parents=True)
    receipt_path = attempt/'setup-receipt.json'
    receipt = {'schema':'portable-wsl-eqy-setup-v1', 'status':'ERROR', 'started_at':_now(),
               'archive_sha256':ARCHIVE_SHA256, 'kit_index_sha256':INDEX_SHA256,
               'proofs_executed':False, 'system_installation_performed':False,
               'package':str(root), 'attempt_directory':str(attempt)}
    _save(receipt_path, receipt)
    try:
        wsl = Path(os.environ.get('SystemRoot', 'C:/Windows'))/'System32/wsl.exe'
        if not wsl.is_file():
            raise RuntimeError('没有可用的 WSL。请先安装并初始化 WSL2 Linux 发行版，或选择已预装的 Windows OSS CAD Suite 后端。')
        raw = _run([str(wsl),'--list','--quiet'], attempt/'01-distros.log')
        distros = [line.strip().lstrip('*').strip() for line in raw.splitlines() if line.strip()]
        eligible = [name for name in distros if re.fullmatch(r'[A-Za-z0-9_.-]+', name)
                    and not any(x in name.lower() for x in ('docker','rancher','podman'))]
        install_record = tmp/'eqy-setup-install.json'
        previous = None
        if install_record.is_file():
            try:
                previous = json.loads(install_record.read_text(encoding='utf-8'))
            except (OSError,ValueError):
                previous = None
        if distro is not None:
            if distro not in eligible:
                raise RuntimeError('指定 WSL 发行版不可用：'+str(distro)+'；可选：'+', '.join(eligible))
        elif previous and previous.get('distro') in eligible:
            distro = previous['distro']
        else:
            distro = next((name for name in ('Ubuntu-24.04','Ubuntu','Ubuntu-22.04','Debian') if name in eligible), None)
            if distro is None and len(eligible) == 1:
                distro = eligible[0]
            if distro is None:
                raise RuntimeError('未能选择已初始化的普通 Linux 发行版。可选：'+', '.join(eligible)+
                                   '。请通过 --distro 指定；本入口不会安装或注销发行版。')
        receipt['distro'] = distro
        prefix = [str(wsl),'-d',distro,'--exec']
        linux_root = _run(prefix+['/usr/bin/wslpath','-a','-u',str(root)], attempt/'02-path.log')
        if not _linux_path(linux_root):
            raise RuntimeError('WSL 映射的代码目录必须是 ASCII 无空格路径。')
        linux_archive = linux_root+'/proof-tools/'+ARCHIVE_NAME
        (attempt/'frozen-files.sha256').write_text(checks_text,encoding='ascii')
        linux_checks = linux_root+'/'+(attempt/'frozen-files.sha256').relative_to(root).as_posix()
        kit = None
        if (previous and previous.get('schema') == 'portable-wsl-eqy-install-v1'
                and previous.get('archive_sha256') == ARCHIVE_SHA256 and previous.get('distro') == distro
                and _linux_path(previous.get('kit')) and previous['kit'].endswith('/'+KIT_NAME)):
            try:
                _run(prefix+['/bin/sh','-s','--',previous['kit'],INDEX_SHA256,linux_checks],
                     attempt/'03-reuse-check.log', stdin=CHECK_KIT)
                kit = previous['kit']
            except RuntimeError:
                # A removed/moved installation is rebuilt in a NEW directory. Never overwrite the old one.
                kit = None
        receipt['reused_installation'] = kit is not None
        if kit is None:
            print('首次配置 WSL EQY：从包内归档安装到 Linux 用户目录。', flush=True)
            package_token = hashlib.sha256(str(root).encode('utf-8')).hexdigest()[:10]
            kit = _run(prefix+['/usr/bin/timeout','-k','5','180','/bin/sh','-s','--',linux_archive,
                       package_token,KIT_NAME,ARCHIVE_SHA256,INDEX_SHA256],
                       attempt/'04-install.log', stdin=BOOTSTRAP, timeout=210)
            if not _linux_path(kit) or not kit.endswith('/'+KIT_NAME):
                raise RuntimeError('工具安装返回了不安全路径；未更新本机配置。')
        receipt['kit'] = kit
        _run(prefix+['/bin/sh','-s','--',kit,INDEX_SHA256,linux_checks],attempt/'05-kit-check.log',stdin=CHECK_KIT)
        output = kit+'/results/preflight-'+uuid.uuid4().hex
        print('检查冻结工具及版本，生成本机路径配置；此步骤不执行形式证明。', flush=True)
        _run(prefix+['/usr/bin/timeout','-k','5','180',kit+'/run_verify.sh','--preflight-only','--output',output],
             attempt/'06-preflight.log', timeout=210)
        validation = _run(prefix+['/bin/cat',output+'/portable-replay-receipt.json'], attempt/'07-preflight-receipt.log')
        checked = json.loads(validation)
        if (checked.get('status') != 'PREFLIGHT_PASS' or checked.get('bundle_root') != kit
                or checked.get('portable_index_sha256') != INDEX_SHA256):
            raise RuntimeError('冻结工具预检回执未通过，未更新本机配置。')
        manifest = output+'/proof-tool-manifest.json'
        manifest_bytes = _run(prefix+['/usr/bin/sha256sum',manifest],attempt/'08-manifest-sha.log')
        manifest_sha = manifest_bytes.split()[0]
        if not re.fullmatch('[0-9a-f]{64}',manifest_sha) or manifest_sha != checked.get('proof_manifest_sha256'):
            raise RuntimeError('本机 manifest 校验值不匹配。')
        config = {'schema':1, 'distro':distro, 'kit':kit, 'manifest':manifest, 'manifest_sha256':manifest_sha}
        config_path = tmp/'proof-wsl.local.json'
        if config_path.is_file():
            (attempt/'previous-proof-wsl.local.json').write_bytes(config_path.read_bytes())
        _save(install_record, {'schema':'portable-wsl-eqy-install-v1','distro':distro,'kit':kit,
                              'archive_sha256':ARCHIVE_SHA256, 'configured_at':_now()})
        _save(config_path, config)
        receipt.update(status='PREFLIGHT_PASS', config_path=str(config_path), config=config,
                       preflight_receipt=checked)
        print('WSL 证明工具预检通过；接下来仍需执行本轮 18 项证明及负对照。', flush=True)
        return config
    except Exception as error:
        receipt['error'] = str(error)
        raise
    finally:
        receipt['completed_at'] = _now()
        _save(receipt_path, receipt)
        _save(tmp/'eqy-setup/latest-setup.json', receipt)
        # Only our empty lock is removed; no tool installation or user files are deleted.
        lock.rmdir()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument('--distro')
    args = parser.parse_args()
    try:
        print(json.dumps(ensure_setup(args.package,args.distro),ensure_ascii=False,indent=2))
    except Exception as error:
        parser.exit(2, 'WSL EQY 配置未完成：'+str(error)+'\n')
