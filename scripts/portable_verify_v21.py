"""Relocated Linux/WSL replay of the eighteen actual Windows RTLIL proofs.

This entry does not rebuild or measure Windows programs. The frozen verification
helpers remain unchanged. The immutable bundle index pins their inputs/tools;
fresh, relocation-specific wrappers and manifests are written only to results/.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PureWindowsPath
import platform
import shutil
import subprocess
import sys


SCHEMA = "fpga-v21-portable-actual-windows-eqy-v1"
COMMIT = "9f75ca1f9834a39a863915b5dae0c7b1e33533bc"
CORE_SHA = "9ae28d47bd5c911777336cfdb195676c345a3cd871755056fca6d0309fc8f843"
HELPER_SHA = "7f8a8484e9886065a508aba1a2244ee74cabcc134dd06d230423e0d7e1b8731d"
WINDOWS_REPORT = "a2d12cfe60767e44bbbb8d025bea74a1b14f7811e6e45d4ff085874b8a31f7c8"
WINDOWS_MANIFEST = "70e06917b35a15e183d6c4ba13c53e5b2cfef10d02933e2c60c8329ebc06e120"
BASELINE_ELF = "5ac190d5096b14967864d093212858bdd457155a1b5e7d2945f314e070d5c2ef"
ABC_ELF = "4c44e7c12e3f060861cec186cb64718e195fc5b12d7cb6c3046f4aa6b022f32b"
FF_MODEL = "3d96aa4532000389a4ac2998cef702b7a4ed46b23707b4e0dd4cb1688b4db2d2"


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for data in iter(lambda: f.read(1024 * 1024), b""):
            h.update(data)
    return h.hexdigest()


def inside(root, value, must_exist=True):
    p = Path(value)
    w = PureWindowsPath(value)
    if p.is_absolute() or w.is_absolute() or w.drive or ".." in p.parts or "\\" in str(value):
        raise RuntimeError("A bundle path must be relative without traversal: " + str(value))
    lexical = root / p
    resolved = lexical.resolve()
    resolved.relative_to(root)
    if must_exist and not resolved.is_file():
        raise FileNotFoundError(resolved)
    if lexical.is_symlink():
        raise RuntimeError("Bundle payload must use regular files, not symlinks: " + str(value))
    return resolved


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def fingerprints(root, index):
    files = index.get("files")
    if not isinstance(files, dict) or not files:
        raise RuntimeError("Missing immutable bundle file inventory")
    for name, expected in files.items():
        path = inside(root, name)
        if sha(path).lower() != expected.lower():
            raise RuntimeError("Bundle payload changed: " + name)
    required = {"portable_verify.py", "scripts/verify_current_cases.py", "scripts/verify_windows_current.py",
                "report.json", "manifest.json", "cases_current.json", "run_current_cases.py", "windows_metrics.py",
                "clean-v11/formal_cycloneiv.v", "runtime/bin/python3", "runtime/bin/yosys", "runtime/bin/yosys-abc",
                "runtime/bin/sby", "runtime/eqy/bin/eqy", "runtime/python_dispatch.py"}
    if required - set(files):
        raise RuntimeError("Required payload is not indexed: " + repr(sorted(required - set(files))))
    for name, expected in (("scripts/verify_current_cases.py", CORE_SHA),
                           ("scripts/verify_windows_current.py", HELPER_SHA),
                           ("clean-v11/formal_cycloneiv.v", FF_MODEL)):
        if files[name] != expected:
            raise RuntimeError("The frozen formal helper identity differs: " + name)
    return len(files)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", type=Path, help="A new directory inside bundle results/ (default timestamp)")
    ap.add_argument("--strategy-timeout", type=int, default=300)
    ap.add_argument("--preflight-only", action="store_true", help="Check hashes, runtime and versions; do not prove")
    args = ap.parse_args()
    if os.name != "posix" or platform.machine().lower() not in ("x86_64", "amd64"):
        ap.error("This package requires Linux x86_64, including a compatible WSL2 Linux distribution")
    if args.strategy_timeout < 1:
        ap.error("--strategy-timeout must be positive")
    root = Path(__file__).resolve().parent
    if not str(root).isascii() or any(c.isspace() for c in str(root)):
        raise RuntimeError("Extract to a new ASCII directory without spaces, for example /tmp/fpga-proof-v21")
    # Always use the packaged interpreter/dispatcher. No host site-packages or
    # source-tree Python environment is part of the proof runtime.
    python = inside(root, "runtime/bin/python3")
    if (Path(os.environ.get("FPGA_PORTABLE_DISPATCH", "")).resolve() != root / "runtime/python_dispatch.py"
            or Path(sys.prefix).resolve() != root / "runtime/python"
            or not sys.flags.isolated or not sys.flags.no_site):
        os.execv(str(python), [str(python), "-I", "-S", "-B", str(Path(__file__).resolve()), *sys.argv[1:]])
    sys.executable = str(python)
    index_path = root / "portable-index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    if index.get("schema") != SCHEMA:
        raise RuntimeError("Unsupported portable bundle schema")
    count = fingerprints(root, index)
    if sha(root / "report.json") != WINDOWS_REPORT or index["windows_report_sha256"] != WINDOWS_REPORT:
        raise RuntimeError("The actual Windows measurement report binding differs")
    if sha(root / "manifest.json") != WINDOWS_MANIFEST or index["windows_manifest_sha256"] != WINDOWS_MANIFEST:
        raise RuntimeError("The Windows tool manifest binding differs")
    # A strict runtime PATH prevents accidental reuse of the original repository,
    # OSS CAD Suite, host Python packages or another synthesis/proof tool version.
    os.environ.clear()
    os.environ.update(PATH=str(root / "runtime/bin"), LC_ALL="C", LANG="C", TERM="dumb",
                      TCL_LIBRARY=str(root / "runtime/tcl8.6"),
                      FPGA_PORTABLE_DISPATCH=str(root / "runtime/python_dispatch.py"))
    results = root / "results"
    if results.is_symlink():
        raise RuntimeError("results must not be a symlink")
    results.mkdir(exist_ok=True)
    results.resolve().relative_to(root)
    if args.output:
        out = args.output.resolve()
        out.relative_to(results.resolve())
    else:
        out = results / ("replay-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f"))
    if out.exists():
        raise RuntimeError("Output must be a new directory: " + str(out))
    out.mkdir(parents=True)
    for name in ("home", "tmp"):
        (out / name).mkdir()
    os.environ["HOME"] = str(out / "home")
    os.environ["TMPDIR"] = str(out / "tmp")
    tools = index["tools"]
    if (tools["baseline_binary_sha256"] != BASELINE_ELF or tools["abc_binary_sha256"] != ABC_ELF
            or sha(inside(root, "runtime/yosys/yosys.real")) != BASELINE_ELF
            or sha(inside(root, "runtime/yosys/yosys-abc.real")) != ABC_ELF):
        raise RuntimeError("The bundled original Linux Yosys/ABC identity differs from the proven v21 chain")
    baseline = inside(root, tools["baseline"])
    abc = inside(root, tools["abc"])
    candidate = inside(root, tools.get("candidate", tools["baseline"]))
    if "candidate" not in tools and tools.get("candidate_aliases_baseline_for_actual_windows_proof_only") is not True:
        raise RuntimeError("A baseline parser alias must be explicitly identified; it is not a Linux candidate build")
    eqy = inside(root, tools["eqy"])
    script = inside(root, index["windows_abc_script"])
    # Generated after relocation. No prior absolute Linux manifest is consulted.
    proof_bin = root / "runtime/bin"
    manifest = {"schema": SCHEMA, "yosys_release": "0.69", "yosys_commit": COMMIT,
        "baseline": str(baseline), "baseline_sha256": sha(baseline),
        "candidate": str(candidate), "candidate_sha256": sha(candidate),
        "candidate_role": ("baseline_parser_alias_for_actual_windows_netlists_only" if candidate == baseline
                           else "bundled_linux_candidate_not_resynthesized_by_this_replay"),
        "abc": str(abc), "abc_sha256": sha(abc), "abc_script": str(script), "abc_script_sha256": sha(script),
        "baseline_binary_sha256": tools["baseline_binary_sha256"], "abc_binary_sha256": tools["abc_binary_sha256"],
        "proof_bin": str(proof_bin), "proof_wrapper_hashes": {name:sha(proof_bin / name) for name in ("yosys", "sby")},
        "eqy": {"executable": str(eqy), "files": {str(root / name):digest for name,digest in index["files"].items()
                   if name.startswith(("runtime/eqy/", "runtime/sby/", "runtime/vendor/"))
                   or name in ("runtime/python_dispatch.py", "runtime/bin/python3")}},
        "portable_index_sha256": sha(index_path), "formal_scope": "18 actual Windows post-ABC ILANG objects plus mandatory negative control"}
    generated = out / "proof-tool-manifest.json"
    write_json(generated, manifest)
    spec = importlib.util.spec_from_file_location("portable_frozen_core", root / "scripts/verify_current_cases.py")
    core = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(core)
    env, checked, _, versions = core.load_environment(root, generated)
    receipt = {"schema": SCHEMA, "status": "PREFLIGHT_PASS", "bundle_root": str(root),
        "portable_index_sha256": sha(index_path), "payload_files_checked": count,
        "windows_report_sha256": sha(root / "report.json"), "windows_manifest_sha256": sha(root / "manifest.json"),
        "proof_manifest_sha256": sha(generated), "versions": versions,
        "python": sys.version, "python_executable": sys.executable, "machine": platform.machine(),
        "scope": "Formal replay only; original Windows resource/time evidence remains unchanged",
        "native_windows_eqy_claim": False, "prior_repository_required": False,
        "completed_utc": datetime.now(timezone.utc).isoformat()}
    for name in index["required_commands"]:
        selected = shutil.which(name, path=env["PATH"])
        if not selected or Path(selected).parent != proof_bin:
            raise RuntimeError("A bundled runtime command is missing/shadowed: " + name)
    # Verify SBY's copied Python closure before starting the eighteen proofs.
    sby_version = subprocess.check_output([proof_bin / "sby", "--version"], env=env, cwd=root,
                                           text=True, timeout=30).strip()
    receipt["versions"]["sby"] = sby_version
    if sby_version != index["sby_version"]:
        raise RuntimeError("Unexpected SBY version: " + sby_version)
    write_json(out / "portable-replay-receipt.json", receipt)
    if args.preflight_only:
        print(json.dumps(receipt, indent=2))
        return 0
    formal_out = out / "formal"
    command = [python, "-I", "-S", "-B", root / "scripts/verify_windows_current.py", "--repo", root,
               "--bundle", root, "--manifest", generated, "--output", formal_out,
               "--strategy-timeout", str(args.strategy_timeout)]
    execution = subprocess.run([str(x) for x in command], env=env, cwd=root)
    report_path = formal_out / "report.json"
    formal = json.loads(report_path.read_text(encoding="utf-8")) if report_path.is_file() else {}
    success = (execution.returncode == 0 and formal.get("status") == "PASS"
               and formal.get("positive_proof_counts") == {"PASS": 18}
               and formal.get("negative_control", {}).get("status") == "EXPECTED_COUNTEREXAMPLE")
    fingerprints(root, index)
    receipt.update(status="PASS" if success else "FAIL", formal_exit_code=execution.returncode,
                   formal_report=str(report_path), formal_report_sha256=sha(report_path) if report_path.is_file() else None,
                   positive_proof_counts=formal.get("positive_proof_counts"),
                   negative_control_status=formal.get("negative_control", {}).get("status"),
                   completed_utc=datetime.now(timezone.utc).isoformat())
    write_json(out / "portable-replay-receipt.json", receipt)
    print("PORTABLE_ACTUAL_WINDOWS_FORMAL_" + receipt["status"], out, flush=True)
    return 0 if success else 2


if __name__ == "__main__":
    sys.exit(main())
