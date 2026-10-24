#!/usr/bin/env python3
"""Build upstream Yosys/ABC, then the unchanged repository patch and matching EQY.

Run from any directory. Source checkouts and local build dependencies must exist;
see README.md for their pinned revisions and acquisition commands.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import time

REPO = Path(__file__).resolve().parents[1]
LOCAL = REPO / 'local-repro'
ROOT = REPO / 'clean-v11'
WORK = ROOT / 'toolchains/yosys-0.69'
SRC = WORK / 'src'
BUILD = WORK / 'build-repro'
DEPS = LOCAL / 'dependencies'
LOGS = LOCAL / 'logs'
YOSYS = '9f75ca1f9834a39a863915b5dae0c7b1e33533bc'
EQY = '4a72eb94fc253062464afee4d0018359017bb846'
SBY = 'b1a1e98cba941ec8433f8dc27f416cd7bb7f14be'


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def output(cmd, cwd=None):
    return subprocess.check_output(cmd, cwd=cwd, text=True).strip()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--jobs', type=int, default=4)
    args = p.parse_args()
    if not 1 <= args.jobs <= 8:
        p.error('Use 1..8 jobs; 4 is recommended on this 16 GiB host')
    LOGS.mkdir(exist_ok=True)
    env = dict(os.environ, PATH=str(DEPS/'host-tools/usr/bin') + ':/usr/bin:/bin',
               BISON_PKGDATADIR=str(DEPS/'host-tools/usr/share/bison'), CCACHE_DISABLE='1')
    for key in ('PYTHONHOME', 'PYTHONPATH'):
        env.pop(key, None)

    def stage(name):
        save(LOCAL/'status.json', dict(stage=name, time=time.time()))
        print(name, flush=True)

    def run(cmd, name, cwd=REPO):
        with (LOGS/(name+'.log')).open('a') as log:
            log.write('\nCOMMAND ' + shlex.join(map(str, cmd)) + '\n')
            log.flush()
            subprocess.run(list(map(str, cmd)), cwd=cwd, env=env,
                           stdout=log, stderr=subprocess.STDOUT, check=True)

    eqysrc = ROOT/'toolchains/eqy-0.69/src-repro'
    sbysrc = DEPS/'sby-src'
    for path, commit in ((SRC, YOSYS), (eqysrc, EQY), (sbysrc, SBY)):
        if output(['git', 'rev-parse', 'HEAD'], path) != commit:
            raise RuntimeError('Wrong source revision: ' + str(path))
    # Verify every bundled source against the gitlink, without depending on the
    # original author's archive checksum or copying any object/binary from it.
    submodules = {}
    for line in output(['git', 'ls-tree', '-r', 'HEAD'], SRC).splitlines():
        mode, kind, rest = line.split(' ', 2)
        if mode != '160000':
            continue
        commit, name = rest.split('\t', 1)
        path = SRC/name
        if output(['git', 'rev-parse', 'HEAD'], path) != commit:
            raise RuntimeError('Wrong bundled revision: ' + name)
        if output(['git', 'status', '--porcelain', '--untracked-files=no'], path):
            raise RuntimeError('Modified bundled source: ' + name)
        submodules[name] = commit
    cmake = DEPS/'cmake-3.31.6/bin/cmake'
    cfg = [cmake, '-S', SRC, '-B', BUILD, '-G', 'Unix Makefiles',
           '-DCMAKE_BUILD_TYPE=Release', '-DCMAKE_C_COMPILER=/usr/bin/gcc',
           '-DCMAKE_CXX_COMPILER=/usr/bin/g++', '-DYOSYS_WITHOUT_SLANG=ON',
           '-DYOSYS_USE_BUNDLED_LIBS=ON', '-DBUILD_SHARED_LIBS=OFF',
           '-DYOSYS_WITH_PYTHON=OFF', '-DYOSYS_WITHOUT_LIBFFI=ON',
           '-DYOSYS_WITHOUT_READLINE=ON', '-DYOSYS_WITHOUT_TCL=ON',
           '-DYOSYS_ENABLE_UNIT_TESTS=OFF', '-DYOSYS_ENABLE_FUNCTIONAL_TESTS=OFF',
           '-DYOSYS_WITHOUT_ABC=OFF', '-DPython3_EXECUTABLE=/usr/bin/python3',
           '-DYOSYS_COMPILER_LAUNCHER=', '-DCMAKE_C_COMPILER_LAUNCHER=',
           '-DCMAKE_CXX_COMPILER_LAUNCHER=']
    compile_cmd = [cmake, '--build', BUILD, '--parallel', args.jobs]
    baseline = BUILD/'yosys-original'
    abc = BUILD/'yosys-abc'
    marker = LOCAL/'baseline.json'
    if not marker.exists():
        if output(['git', 'status', '--porcelain', '--untracked-files=all'], SRC):
            raise RuntimeError('Baseline must be built from pristine upstream source')
        stage('building_fresh_yosys_069_and_bundled_abc')
        run(cfg, 'baseline')
        run(compile_cmd, 'baseline')
        shutil.copy2(BUILD/'yosys', baseline)
        save(marker, dict(baseline=sha(baseline), abc=sha(abc),
                         source_commit=YOSYS, submodules=submodules,
                         config=list(map(str, cfg)), external_objects_copied=0))
    frozen = json.loads(marker.read_text())
    if sha(baseline) != frozen['baseline'] or sha(abc) != frozen['abc']:
        raise RuntimeError('Baseline or shared ABC changed')
    if frozen['config'] != list(map(str, cfg)):
        raise RuntimeError('Build configuration changed')
    rejected = subprocess.run([baseline, '-Q', '-T', '-p', 'pmux_competition_opt'],
                              capture_output=True, text=True)
    if rejected.returncode == 0 or 'No such command' not in rejected.stderr + rejected.stdout:
        raise RuntimeError('Baseline contains candidate pass')
    patch = WORK/'competition-v11/synth-intel-competition.patch'
    plugin = ROOT/'pmux_competition_v11.cc'
    integrated = SRC/'passes/opt/pmux_competition_opt.cc'
    stage('building_unchanged_repository_v14')
    if not integrated.exists():
        run(['git', 'apply', '--check', patch], 'patch', SRC)
        run(['git', 'apply', patch], 'patch', SRC)
    run(['git', 'apply', '--check', '--reverse', patch], 'patch', SRC)
    # The tracked source has mixed CRLF/LF while the patch adds LF text.
    # Compare universal-newline text, retaining both raw hashes as evidence.
    if integrated.read_text() != plugin.read_text() or sha(plugin) != sha(REPO/'src/pmux_competition_v11.cc'):
        raise RuntimeError('Integrated algorithm differs from repository')
    run(cfg, 'candidate')
    run(compile_cmd, 'candidate')
    candidate = BUILD/'yosys-competition-reconstructed'
    shutil.copy2(BUILD/'yosys', candidate)
    if sha(baseline) != frozen['baseline'] or sha(abc) != frozen['abc']:
        raise RuntimeError('Candidate rebuild modified baseline or ABC')
    versions = {role: output([str(path), '-V']) for role, path in
                (('baseline', baseline), ('candidate', candidate))}
    if not all(v.startswith('Yosys 0.69 (') for v in versions.values()):
        raise RuntimeError('Wrong compiled versions: ' + repr(versions))
    if 'PMUX_COMPETITION_OPT v14.' not in output([candidate, '-Q', '-T', '-p', 'pmux_competition_opt']):
        raise RuntimeError('Candidate is not v14')
    stage('building_eqy_and_installing_sby_069')
    prefix = ROOT/'toolchains/eqy-0.69/install-repro'
    run(['make', '-j'+str(args.jobs), 'install', 'YOSYS_CONFIG='+str(BUILD/'yosys-config'),
         'PREFIX='+str(prefix)], 'eqy', eqysrc)
    sbyprefix = DEPS/'sby-install'
    # Upstream v0.68/v0.69/v0.70 tags share this commit. Unrestricted
    # git describe chooses v0.70; use the requested verified tag explicitly.
    if output(['git', 'rev-parse', 'v0.69^{commit}'], sbysrc) != SBY:
        raise RuntimeError('SBY v0.69 tag does not identify the pinned commit')
    sby_release = 'SBY ' + output(['git', 'describe', '--exact-match', '--match', 'v0.69'], sbysrc)
    run(['make', 'install', 'PREFIX='+str(sbyprefix),
         'YOSYS_RELEASE_VERSION='+sby_release], 'sby', sbysrc)
    eqy = prefix/'bin/eqy'
    sby = sbyprefix/'bin/sby'
    if output(['/usr/bin/python3', '-E', str(eqy), '--version']) != 'EQY v0.69':
        raise RuntimeError('Wrong EQY release')
    if output(['/usr/bin/python3', '-E', str(sby), '--version']) != 'SBY v0.69':
        raise RuntimeError('Wrong SBY release')
    proof = WORK/'proof-bin'
    proof.mkdir(exist_ok=True)
    link = proof/'yosys'
    if not link.exists():
        link.symlink_to(baseline)
    if link.resolve() != baseline.resolve():
        raise RuntimeError('Unexpected proof yosys symlink')
    wrapper = proof/'sby'
    wrapper.write_text('#!/bin/sh\nexec /usr/bin/python3 -E ' + shlex.quote(str(sby)) +
                       ' --yosys ' + shlex.quote(str(baseline)) + ' --abc ' +
                       shlex.quote(str(abc)) + ' "$@"\n')
    wrapper.chmod(0o755)
    # Keep witness/SMTBMC helpers from this same build available to SBY, without
    # falling back to a system installation or an unrelated OSS CAD Suite.
    for name in ('yosys-witness', 'yosys-smtbmc'):
        helper = proof/name
        helper.write_text('#!/bin/sh\nexec /usr/bin/python3 -E ' +
                          shlex.quote(str(BUILD/name)) + ' "$@"\n')
        helper.chmod(0o755)
    eqym = dict(commit=EQY, version='EQY v0.69', executable=str(eqy), sby_commit=SBY,
                files={str(f):sha(f) for base in (prefix, sbyprefix) for f in base.rglob('*')
                       if f.is_file() and '__pycache__' not in f.parts})
    eqym['files'][str(wrapper)] = sha(wrapper)
    for name in ('yosys-witness', 'yosys-smtbmc'):
        eqym['files'][str(proof/name)] = sha(proof/name)
        eqym['files'][str(BUILD/name)] = sha(BUILD/name)
    save(ROOT/'toolchains/eqy-0.69/manifest.json', eqym)
    mapping = BUILD/'share/intel/competition_abc_v11.abc'
    if mapping.read_text().strip() != (ROOT/'competition_abc_dch.abc').read_text().strip():
        raise RuntimeError('ABC9 script mismatch')
    paths = dict(baseline=baseline, candidate=candidate, abc=abc, abc_script=mapping,
                 plugin_source=plugin, patch=patch)
    m = dict(yosys_release='0.69', yosys_commit=YOSYS,
             repository_commit=output(['git', 'rev-parse', 'HEAD'], REPO),
             build_config=list(map(str, cfg)), submodules=submodules,
             external_objects_copied=0, baseline_version=versions['baseline'],
             candidate_version=versions['candidate'], source_provenance='Pinned Git objects, clean upstream baseline',
             integrated_source=str(integrated), integrated_source_sha256=sha(integrated),
             integrated_source_matches_normalized_repository_text=True)
    for role, path in paths.items():
        m[role] = str(path)
        m[role+'_sha256'] = sha(path)
    save(WORK/'competition-v11/manifest.json', m)
    stage('TOOLCHAIN_READY')
    print(json.dumps(versions, indent=2), flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        save(LOCAL/'status.json', dict(stage='FAIL', error=str(exc), time=time.time()))
        raise
