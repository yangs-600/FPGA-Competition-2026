"""Current nine-case formal and logic-resource entry; Windows efficiency is separate."""
import argparse
from pathlib import Path
import sys


def main():
    compatibility = argparse.ArgumentParser(add_help=False)
    compatibility.add_argument("--repeats", type=int)
    legacy, remaining = compatibility.parse_known_args()
    if legacy.repeats is not None:
        print("DEPRECATED: --repeats is ignored. This entry validates nine current cases; Windows performance uses its separate measurement runner.", file=sys.stderr)
    parent = Path(__file__).resolve().parents[1]
    # The second path permits inspection of this staged handoff before deployment.
    candidates = [parent / "scripts/verify_current_cases.py", parent / "verify_current_cases.py"]
    core_path = next((path for path in candidates if path.is_file()), None)
    if core_path is None:
        raise RuntimeError("Deploy scripts/verify_current_cases.py with this entry")
    sys.path.insert(0, str(core_path.parent))
    import verify_current_cases as current
    repo = current.find_repo(parent)
    if not any(arg == "--repo" or arg.startswith("--repo=") for arg in remaining):
        remaining += ["--repo", str(repo)]
    sys.argv = [sys.argv[0], *remaining]
    print("Current checks default to nine registered cases and eighteen formal proofs plus negative control, with a separate area verdict. --case is diagnostic only. Windows runtime/peak-memory acceptance is not performed here.", file=sys.stderr)
    return current.main()


if __name__ == "__main__":
    sys.exit(main())
