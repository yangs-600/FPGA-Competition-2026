#!/usr/bin/env bash
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    echo "Use: source ${BASH_SOURCE[0]}" >&2
    exit 1
fi
_competition_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if ! python3 - "$_competition_root" <<'PY'
import sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from run_competition_v11 import environment
_,manifest=environment()
folder=Path(sys.argv[1])/'toolchains/yosys-0.69/competition-v11/bin'
folder.mkdir(exist_ok=True)
target=folder/'yosys'
if target.is_symlink():
    if target.resolve()!=Path(manifest['candidate']).resolve():
        target.unlink()
        target.symlink_to(manifest['candidate'])
elif target.exists():
    raise RuntimeError('Unexpected existing executable in competition-v11/bin')
else:
    target.symlink_to(manifest['candidate'])
print(manifest['candidate_version'])
PY
then
    unset _competition_root
    return 1
fi
export PATH="$_competition_root/toolchains/yosys-0.69/competition-v11/bin:$PATH"
unset _competition_root
