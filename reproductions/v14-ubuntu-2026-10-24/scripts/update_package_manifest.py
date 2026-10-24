#!/usr/bin/env python3
"""Maintainer command: hash exactly the distribution inputs, not restored workspaces."""
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
inputs = [root/'prepare.py', root/'README.md', root/'.gitignore']
inputs += [p for folder in ('assets', 'scripts', 'reports') for p in (root/folder).rglob('*')
           if p.is_file() and '__pycache__' not in p.parts]

def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

data = dict(format=1, project_commit='2791affaa80b9bdf637cae5f60511056aec6d8ab',
            target='Ubuntu 22.04 x86_64; GCC 11.4; Python 3.10',
            original_local_root='/home/jumptiger/Documents/Codex/2026-10-02/FPGA-Competition-2026-repro-v14',
            notes='Original measurements are archived; regenerated manifests preserve executable hashes and relocate only paths.',
            sha256={p.relative_to(root).as_posix():digest(p) for p in sorted(inputs)})
(root/'package.json').write_text(json.dumps(data, indent=2, ensure_ascii=False)+'\n')
print('Hashed', len(inputs), 'distribution files')
