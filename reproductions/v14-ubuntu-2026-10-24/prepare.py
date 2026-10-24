#!/usr/bin/env python3
"""Restore the pinned v14 environment into a NEW directory, never the branch root."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile

PACKAGE = Path(__file__).resolve().parent
PIN = '2791affaa80b9bdf637cae5f60511056aec6d8ab'


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def run(args, cwd=None):
    subprocess.run(list(map(str, args)), cwd=cwd, check=True)


def unpack(name, dest):
    # Archives are hash-verified before any extraction. data_filter rejects
    # absolute/traversing paths and escaping symlinks, including Git symlinks.
    def safe_filter(member, target_dir):
        if member.issym() and not os.path.isabs(member.linkname):
            # Some Ubuntu Python 3.10 data_filter backports resolve a relative
            # symlink against the extraction root rather than its parent.
            # Validate the real target ourselves, still apply data_filter's
            # path/mode/owner checks, then retain the original relative link.
            root = Path(target_dir).resolve()
            target = (root/Path(member.name).parent/member.linkname).resolve()
            if not target.is_relative_to(root):
                raise tarfile.LinkOutsideDestinationError(member, str(target))
            checked = copy.copy(member)
            checked.linkname = target.relative_to(root).as_posix()
            checked = tarfile.data_filter(checked, target_dir)
            checked.linkname = member.linkname
            return checked
        return tarfile.data_filter(member, target_dir)
    with tarfile.open(PACKAGE/'assets'/name) as archive:
        archive.extractall(dest, filter=safe_filter)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('runtime', 'source'), default='runtime')
    parser.add_argument('--destination', type=Path, default=PACKAGE/'workspace')
    args = parser.parse_args()
    if platform.system() != 'Linux' or platform.machine() not in ('x86_64', 'AMD64'):
        parser.error('This package targets Linux x86_64 (Ubuntu 22.04); on Windows use WSL2 Ubuntu.')
    if not hasattr(tarfile, 'data_filter'):
        parser.error('Use Python with tarfile.data_filter (current Ubuntu security updates or Python >= 3.12).')
    if not shutil.which('git'):
        parser.error('Git is required')
    try:
        import click  # noqa: F401; EQY/SBY dependency
    except ImportError:
        parser.error('Install python3-click first (for example: sudo apt install python3-click)')
    destination = args.destination.resolve()
    if destination.exists():
        parser.error('Refusing to overwrite an existing directory: ' + str(destination))
    if any(ch.isspace() for ch in str(destination)):
        parser.error('Choose a path without whitespace; upstream make/proof scripts assume this.')
    metadata = json.loads((PACKAGE/'package.json').read_text())
    for relative, expected in metadata['sha256'].items():
        if digest(PACKAGE/relative) != expected:
            raise RuntimeError('Package hash mismatch: ' + relative)
    print('Package checksums verified', flush=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    run(['git', 'clone', '--no-checkout', PACKAGE/'assets/project-v14.bundle', destination])
    run(['git', 'checkout', '--detach', PIN], destination)
    actual = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=destination, text=True).strip()
    if actual != PIN:
        raise RuntimeError('Wrong project commit')
    run(['git', 'remote', 'set-url', 'origin', 'git@github.com:yangs-600/FPGA-Competition-2026.git'], destination)
    local = destination/'local-repro'
    local.mkdir()
    for name in ('build.py', 'validate.py'):
        shutil.copy2(PACKAGE/'scripts'/name, local/name)
    shutil.copy2(PACKAGE/'README.md', local/'PACKAGE-README.md')
    if args.mode == 'source':
        # Start genuinely pristine: the source archive preserves the exact
        # tested candidate patch; reverse that exact patch in this NEW copy.
        unpack('toolchain-source.tar.gz', destination)
        unpack('build-tools-linux-x86_64.tar.gz', destination)
        source = destination/'clean-v11/toolchains/yosys-0.69/src'
        patch = destination/'clean-v11/toolchains/yosys-0.69/competition-v11/synth-intel-competition.patch'
        run(['git', 'apply', '--check', '--reverse', patch], source)
        run(['git', 'apply', '--reverse', patch], source)
        state = subprocess.check_output(['git', 'status', '--porcelain'], cwd=source, text=True)
        if state.strip():
            raise RuntimeError('Source is not pristine after reversing the exact patch: ' + state)
        if (local/'baseline.json').exists():
            raise RuntimeError('Source rebuild must not reuse a baseline marker')
        print('Pristine sources ready. No prior Yosys/ABC binaries or objects were installed.')
        print(f'cd {destination}\npython3 local-repro/build.py --jobs 4\npython3 local-repro/validate.py --repeats 21')
        return

    unpack('runtime-linux-x86_64.tar.gz', destination)
    old_root = metadata['original_local_root']
    def relocate(value):
        if isinstance(value, str):
            return value.replace(old_root, str(destination))
        if isinstance(value, list):
            return [relocate(v) for v in value]
        if isinstance(value, dict):
            return {relocate(k):relocate(v) for k,v in value.items()}
        return value
    work = destination/'clean-v11/toolchains/yosys-0.69'
    manifest_path = work/'competition-v11/manifest.json'
    manifest = relocate(json.loads(manifest_path.read_text()))
    for role in ('baseline', 'candidate', 'abc', 'abc_script', 'plugin_source', 'patch'):
        if digest(Path(manifest[role])) != manifest[role+'_sha256']:
            raise RuntimeError('Restored binary/source hash mismatch: ' + role)
    eqypath = destination/'clean-v11/toolchains/eqy-0.69/manifest.json'
    eqy = relocate(json.loads(eqypath.read_text()))
    # Verify bytes before rewriting only path-dependent launchers.
    for path, expected in eqy['files'].items():
        if digest(Path(path)) != expected:
            raise RuntimeError('Restored EQY/SBY hash mismatch: ' + path)
    proof = work/'proof-bin'
    (proof/'yosys').symlink_to(Path(manifest['baseline']))
    for name in ('sby', 'yosys-witness', 'yosys-smtbmc'):
        path = proof/name
        path.write_text(path.read_text().replace(old_root, str(destination)))
        eqy['files'][str(path)] = digest(path)
    manifest['installation'] = 'Verified packaged binaries; paths relocated without modifying executables'
    manifest_path.write_text(json.dumps(manifest, indent=2)+'\n')
    eqypath.write_text(json.dumps(eqy, indent=2)+'\n')
    # Fail immediately for missing shared libraries or incompatible glibc.
    for role in ('baseline', 'candidate'):
        run([manifest[role], '-V'])
    run([manifest['abc'], '-c', 'version'])
    run(['/usr/bin/python3', '-E', eqy['executable'], '--version'])
    sys.path.insert(0, str(destination/'clean-v11'))
    from run_competition_v11 import environment
    environment()  # Original verifier checks binaries, scripts and immutable RTL.
    print('Runtime ready; no old author directory is needed.', flush=True)
    print(f'cd {destination}\npython3 local-repro/validate.py --repeats 21')


if __name__ == '__main__':
    main()
