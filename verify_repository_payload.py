"""Verify the immutable release payload and declared Git-only additions.

No compiler, optimizer, solver, Git operation or network request is performed.
The original payload-index covers the original release only; repository-release
declares the additional repository files separately. Git metadata and new local
measurement outputs are excluded from that immutable release scope.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath


def need(ok, message):
    if not ok:
        raise RuntimeError(message)


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def unique(pairs):
    d = {}
    for k, v in pairs:
        need(k not in d, 'Duplicate JSON key: '+k)
        d[k] = v
    return d


def read(path):
    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique)


def checked(root, name):
    rel = PurePosixPath(name)
    need(name and not rel.is_absolute() and '..' not in rel.parts and ':' not in name and '\\' not in name,
         'Unsafe declared path: '+name)
    path = root.joinpath(*rel.parts)
    need(path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(root), 'Missing/unsafe file: '+name)
    return path


def verify(root):
    scope = read(root/'repository-release.json')
    need(scope['schema'] == 'repository-release-scope-v1', 'Unknown repository scope')
    index_path = checked(root, 'payload-index.json')
    need(sha(index_path) == scope['release_payload_index_sha256'], 'Release index changed')
    index = read(index_path)
    need(index['schema'] == 'payload-index-v1' and index['excludes'] == ['payload-index.json'], 'Unexpected release index')
    release = dict(index['files'])
    need('payload-index.json' not in release and index['file_count'] == len(release), 'Invalid release count')
    need(index['total_bytes'] == sum(v['bytes'] for v in release.values()), 'Release byte total differs')
    release['payload-index.json'] = {'bytes': index_path.stat().st_size, 'sha256': scope['release_payload_index_sha256']}
    need(len(release) == scope['release_file_count_including_index'] == 2727, 'Unexpected frozen release size')
    extra = scope['repository_files']
    need(not set(release)&set(extra) and 'repository-release.json' not in extra, 'Repository additions overwrite frozen release')
    expected = {**release, **extra}
    for name, info in expected.items():
        p = checked(root, name)
        need(p.stat().st_size == info['bytes'] and sha(p) == info['sha256'], 'Bytes/hash mismatch: '+name)
    allowed = set(expected)|{'repository-release.json'}
    ignored = []
    unexpected = []
    for directory, dirs, files in os.walk(root, followlinks=False):
        base = Path(directory)
        for name in list(dirs):
            path = base/name
            rel = path.relative_to(root).as_posix()
            need(not path.is_symlink(), 'Unexpected directory symlink: '+rel)
            generated = name == '__pycache__' or (base == root and (name == '.git' or name == 'tmp' or
                        (name.startswith('validation-current-') and not any(p.startswith(name+'/') for p in release))))
            if generated:
                dirs.remove(name)
                ignored.append(rel+'/')
        for name in files:
            rel = (base/name).relative_to(root).as_posix()
            if rel in allowed:
                continue
            if rel in ('.git', 'latest-current.json') or name.endswith(('.pyc', '.pyo')):
                ignored.append(rel)
            else:
                unexpected.append(rel)
    need(not unexpected, 'Undeclared repository files: '+repr(unexpected))
    return {'status': 'REPOSITORY_FROZEN_RELEASE_AND_DECLARED_ADDITIONS_PASS',
            'release_files_verified': len(release), 'repository_files_verified': len(extra),
            'payload_index_sha256': scope['release_payload_index_sha256'],
            'ignored_local_metadata_or_new_run_outputs': sorted(ignored), 'program_executions': 0}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    print(json.dumps(verify(args.root.resolve(strict=True)), indent=2, ensure_ascii=True))
