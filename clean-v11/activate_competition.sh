#!/usr/bin/env bash
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    echo "Use: source ${BASH_SOURCE[0]}" >&2
    exit 1
fi
_competition_repo="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if ! _competition_candidate="$(/usr/bin/python3 -E -B - "$_competition_repo" <<'PY'
import sys
from pathlib import Path
repo = Path(sys.argv[1])
sys.path.insert(0, str(repo / 'scripts'))
from verify_current_cases import load_environment, DEFAULT_MANIFEST
_, manifest, _, _ = load_environment(repo, repo / DEFAULT_MANIFEST)
print(manifest['candidate'])
PY
)"; then
    unset _competition_repo _competition_candidate
    return 1
fi
export PATH="$(dirname -- "$_competition_candidate"):$PATH"
unset ABC YOSYS_DATDIR
"$_competition_candidate" -V
unset _competition_repo _competition_candidate
