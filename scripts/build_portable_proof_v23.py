"""Copy a new Linux x86_64 proof kit; never synthesize or run formal proofs.

Inputs are pinned project tools, explicit proof evidence, CPython stdlib, Click,
and an explicit system utility/library allowlist. No home/config/credential tree
is copied. The existing repository, reports, tools and Windows ZIP are read only.
"""
import argparse
import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PureWindowsPath
import platform
import re
import shutil
import subprocess
import sys
import sysconfig


SCHEMA = "fpga-v23-portable-actual-windows-eqy-v1"
COMMIT = "9f75ca1f9834a39a863915b5dae0c7b1e33533bc"
WINDOWS_REPORT = "46d8b894ecd2220300767003ef2bdce2bad375a0e3f67e7f115de160ea23294d"
WINDOWS_MANIFEST = "fcaef62a015a020bd17413c3c69f256faf39ca8e8825fa1ee1b10c71fb0f3e6c"
PINNED_NATIVE = {"baseline":"5ac190d5096b14967864d093212858bdd457155a1b5e7d2945f314e070d5c2ef",
                 "abc":"4c44e7c12e3f060861cec186cb64718e195fc5b12d7cb6c3046f4aa6b022f32b"}
FF_MODEL = "3d96aa4532000389a4ac2998cef702b7a4ed46b23707b4e0dd4cb1688b4db2d2"
HELPERS = {
    "verify_current_cases.py": "9ae28d47bd5c911777336cfdb195676c345a3cd871755056fca6d0309fc8f843",
    "verify_windows_current.py": "7f8a8484e9886065a508aba1a2244ee74cabcc134dd06d230423e0d7e1b8731d",
    "test_pmux_operators.py": "da5ed44c602bc3db0bd50d414d535562e0d183d309e13a7cf4ccfbc54f9067e5",
    "test_pmux_fastpaths.py": "74c52464b798d9aa11ddd29151cca8dd65dfbf1ef4f6ea7c1842c178f1c808d2"}
COMMANDS = ("make", "bash", "sh", "grep", "awk", "cat", "sed", "cp", "mv", "rm", "mkdir", "ln",
            "readlink", "dirname", "pwd", "env", "head", "tail", "wc", "sort", "tee", "uname", "touch", "sleep")


def sha(p):
    h = hashlib.sha256()
    with Path(p).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def rel(root, value):
    p = Path(value)
    return p.resolve() if p.is_absolute() else (root / p).resolve()


def evidence(root, value):
    p, w = Path(value), PureWindowsPath(value)
    if p.is_absolute() or w.is_absolute() or w.drive or ".." in p.parts or "\\" in str(value):
        raise RuntimeError("Unsafe evidence path: " + str(value))
    p = (root / p).resolve()
    p.relative_to(root)
    if not p.is_file():
        raise FileNotFoundError(p)
    return p


def write(path, text, executable=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    path.chmod(0o755 if executable else 0o644)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", required=True, type=Path)
    ap.add_argument("--manifest", default="clean-v11/toolchains/yosys-0.69/competition-current-v23-add-orientation/manifest.json")
    ap.add_argument("--windows-bundle", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path, help="New ASCII stage directory; must not exist")
    ap.add_argument("--portable-entry", required=True, type=Path)
    ap.add_argument("--sby-entry", type=Path, default=Path("/home/ubuntu/oss-cad-suite/libexec/sby"))
    ap.add_argument("--witness-entry", type=Path, default=Path("/home/ubuntu/oss-cad-suite/libexec/yosys-witness"))
    ap.add_argument("--yosys-share", type=Path)
    ap.add_argument("--license-file", action="append", default=[], type=Path)
    args = ap.parse_args()
    if os.name != "posix" or platform.machine() != "x86_64" or sys.version_info[:2] != (3, 10):
        ap.error("Build this locked kit with Ubuntu x86_64 /usr/bin/python3 (3.10)")
    root, win, out = args.repo.resolve(), args.windows_bundle.resolve(), args.output.resolve()
    if out.exists():
        raise RuntimeError("Refusing to overwrite any existing stage: " + str(out))
    if not str(out).isascii() or any(c.isspace() for c in str(out)):
        raise RuntimeError("Use a new ASCII stage path without spaces")
    if not args.portable_entry.is_file():
        raise FileNotFoundError(args.portable_entry)
    manifest_path = rel(root, args.manifest)
    manifest = json.loads(manifest_path.read_text())
    if str(manifest.get("yosys_release")) != "0.69" or manifest.get("yosys_commit", COMMIT) != COMMIT:
        raise RuntimeError("The source proof tools are not pinned Yosys 0.69")
    tools = {}
    for name in ("baseline", "abc"):
        p = rel(root, manifest[name])
        if sha(p) != manifest[name + "_sha256"] or sha(p) != PINNED_NATIVE[name] or p.read_bytes()[:4] != b"\x7fELF":
            raise RuntimeError("Expected an unchanged native pinned ELF " + name)
        tools[name] = p
    eqy = rel(root, manifest["eqy"]["executable"])
    for name, digest in manifest["eqy"]["files"].items():
        if sha(rel(root, name)) != digest:
            raise RuntimeError("Pinned EQY component changed: " + name)
    eqy_prefix = eqy.parent.parent
    sby = args.sby_entry.resolve()
    sby_prefix = sby.parent.parent
    witness = args.witness_entry.resolve()
    if "SBY v0.68" not in sby.read_text() or "EQY v0.69" not in eqy.read_text():
        raise RuntimeError("Expected the already used SBY v0.68 and EQY v0.69 Python sources")
    if sha(win / "report.json") != WINDOWS_REPORT:
        raise RuntimeError("This kit is locked to the preserved v23 actual Windows measurement report")
    if sha(win / "manifest.json") != WINDOWS_MANIFEST:
        raise RuntimeError("This kit is locked to the preserved v23 Windows tool manifest")
    windows_report = json.loads((win / "report.json").read_text(encoding="utf-8-sig"))
    windows_manifest = json.loads((win / "manifest.json").read_text(encoding="utf-8-sig"))
    registry = json.loads((win / "cases_current.json").read_text(encoding="utf-8-sig"))
    cases = registry["cases"] if isinstance(registry, dict) else registry
    if len(cases) != 9 or len(windows_report["cases"]) != 9:
        raise RuntimeError("Exactly nine Windows cases are required")
    out.mkdir(parents=True)
    origins, native, library_origins, license_sources = {}, [], {}, set()

    def copy(src, name, role):
        src = Path(src).resolve()
        if not src.is_file():
            raise FileNotFoundError(src)
        dest = out / name
        if dest.exists():
            if sha(dest) != sha(src):
                raise RuntimeError("Conflicting destination: " + name)
            return dest
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
        dest.chmod(src.stat().st_mode & 0o777)
        origins[name] = {"role": role, "source": str(src), "sha256": sha(src), "bytes": src.stat().st_size}
        if src.read_bytes()[:4] == b"\x7fELF":
            native.append(src)
        return dest

    def tree(src, name, role, pattern=None):
        src = Path(src).resolve()
        if not src.is_dir():
            raise FileNotFoundError(src)
        for p in sorted(src.rglob("*")):
            if "__pycache__" in p.parts or p.suffix in (".pyc", ".pyo") or not p.is_file():
                continue
            if pattern and not pattern(p):
                continue
            copy(p, (Path(name) / p.relative_to(src)).as_posix(), role)

    for name in ("report.json", "manifest.json", "cases_current.json", "run_current_cases.py", "windows_metrics.py"):
        copy(win / name, name, "unchanged original Windows evidence")
    for case in cases:
        name = case.get("path", case.get("source"))
        if not name:
            raise RuntimeError("Case registry has no relative source path")
        copy(evidence(win, name), name, "immutable original RTL")
    for row in windows_report["cases"]:
        for role in ("baseline", "candidate"):
            item = row["roles"][role]
            name = item["path"] + "/postabc.il"
            src = evidence(win, name)
            if sha(src) != item["ilang_sha256"]:
                raise RuntimeError("Actual Windows RTLIL hash mismatch: " + name)
            copy(src, name, "actual Windows raw post-ABC RTLIL")
    scripts = [name for name in windows_manifest["roles"]["candidate"]["files"]
               if Path(name).suffix.lower() in (".abc", ".script")]
    if len(scripts) != 1:
        raise RuntimeError("Expected one fixed Windows candidate ABC script")
    abc_script = "candidate/" + scripts[0]
    copy(evidence(win, abc_script), abc_script, "original Windows unified ABC resource")
    for name, digest in HELPERS.items():
        src = root / "scripts" / name
        if sha(src) != digest:
            raise RuntimeError("A frozen helper identity changed: " + name)
        copy(src, "scripts/" + name, "unchanged frozen formal helper")
    if sha(root / "clean-v11/formal_cycloneiv.v") != FF_MODEL:
        raise RuntimeError("The canonical asynchronous-clear FF model differs from the proven v23 chain")
    copy(root / "clean-v11/formal_cycloneiv.v", "clean-v11/formal_cycloneiv.v", "canonical asynchronous-clear FF model")
    copy(args.portable_entry, "portable_verify.py", "portable relocation and fingerprint entry")
    copy(Path(__file__), "provenance/build_portable_proof.py", "copy-only bundle builder source")
    copy(tools["baseline"], "runtime/yosys/yosys.real", "pinned original Yosys ELF")
    copy(tools["abc"], "runtime/yosys/yosys-abc.real", "pinned ABC ELF")
    shares = [args.yosys_share] if args.yosys_share else [tools["baseline"].parent / "share", tools["baseline"].parent.parent / "share/yosys"]
    share = next((p for p in shares if p and p.is_dir()), None)
    if share is None:
        raise RuntimeError("Cannot locate the original Yosys share tree; use --yosys-share")
    # Explicit ld.so execution makes /proc/self/exe name the private loader in
    # runtime/lib. Yosys 0.69 reads the compiled YOSYS_DATDIR macro, not an
    # environment override. Its procdir/../share/yosys fallback works from both
    # runtime/lib (loader) and runtime/yosys (direct original ELF execution).
    tree(share, "runtime/share/yosys", "original Yosys installed data/model resources")
    copy(eqy, "runtime/eqy/bin/eqy", "pinned EQY v0.69 entry")
    tree(eqy_prefix / "share/yosys/python3", "runtime/eqy/share/yosys/python3", "EQY Python modules")
    plugins = sorted((eqy_prefix / "share/yosys/plugins").glob("eqy_*.so"))
    if len(plugins) != 3:
        raise RuntimeError("Expected the three pinned reproducible EQY plugins")
    for p in plugins:
        copy(p, "runtime/eqy/share/yosys/plugins/" + p.name, "pinned EQY plugin; never OSS-suite replacement")
    copy(sby, "runtime/sby/bin/sby", "same SBY v0.68 entry previously used through OSS wrapper")
    tree(sby_prefix / "share/yosys/python3", "runtime/sby/share/yosys/python3", "SBY import closure",
         lambda p:p.suffix == ".py" and (p.name.startswith("sby_") or p.name in ("smtio.py", "ywio.py")))
    copy(witness, "runtime/sby/bin/yosys-witness", "matching Yosys witness Python utility")
    click = importlib.util.find_spec("click")
    if not click or not click.submodule_search_locations:
        raise RuntimeError("System CPython Click package is missing")
    click_dir = Path(next(iter(click.submodule_search_locations)))
    tree(click_dir, "runtime/vendor/click", "vendored Click dependency")
    for p in click_dir.parent.glob("click-*.dist-info"):
        tree(p, "runtime/vendor/" + p.name, "Click version/license metadata")
    python = Path(sys.executable).resolve()
    copy(python, "runtime/python/bin/python3.10", "CPython 3.10 native runtime")
    stdlib = Path(sysconfig.get_paths()["stdlib"]).resolve()
    tree(stdlib, "runtime/python/lib/python3.10", "CPython standard library including dynamic extensions")
    tcl = Path("/usr/share/tcltk/tcl8.6")
    if tcl.is_dir():
        tree(tcl, "runtime/tcl8.6", "Tcl runtime data for linked Yosys library")
    utility_paths = {}
    for name in COMMANDS:
        p = shutil.which(name, path="/usr/bin:/bin")
        if not p:
            raise RuntimeError("An explicit runtime utility is missing: " + name)
        utility_paths[name] = Path(p).resolve()
        copy(p, "runtime/tools/" + name + ".real", "bundled system utility " + name)

    # ldd reports the full transitive library closure of these trusted ELF files.
    # Every SONAME alias is materialized as a regular file in one private dir.
    ldd_results = []
    for p in sorted(set(native)):
        execution = subprocess.run(["/usr/bin/ldd", str(p)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, timeout=20, env={"PATH":"/usr/bin:/bin", "LC_ALL":"C"})
        text = execution.stdout
        if execution.returncode or "not found" in text:
            raise RuntimeError("Cannot close native runtime dependencies: " + str(p) + "\n" + text)
        ldd_results.append({"source":str(p), "output":text})
        for line in text.splitlines():
            for value in re.findall(r"(?<!\S)(/[^\s()]+)", line):
                p_lib = Path(value)
                if not p_lib.is_file():
                    raise RuntimeError("Missing dependency: " + value)
                target = "runtime/lib/" + p_lib.name
                copy(p_lib, target, "transitive native shared-library/ELF-loader closure")
                library_origins[target] = str(p_lib)
    loader = out / "runtime/lib/ld-linux-x86-64.so.2"
    if not loader.is_file():
        raise RuntimeError("ELF loader was not captured")

    shell_header = '#!/bin/sh\nset -eu\nunset LD_LIBRARY_PATH LD_PRELOAD PYTHONHOME PYTHONPATH PYTHONUSERBASE PYTHONSTARTUP PYTHONEXECUTABLE BASH_ENV ENV CDPATH MAKEFLAGS GNUMAKEFLAGS MAKEFILES MFLAGS\nb=${0%/*}\n[ "$b" != "$0" ] || b=.\nR=$(CDPATH= cd -- "$b/../.." && pwd)\n'
    def elf_wrapper(name, target, extra=""):
        write(out / "runtime/bin" / name, shell_header +
              'exec "$R/runtime/lib/ld-linux-x86-64.so.2" --inhibit-cache --library-path "$R/runtime/lib" ' +
              '"$R/' + target + '" ' + extra + '"$@"\n', True)
    for name in COMMANDS:
        elf_wrapper(name, "runtime/tools/" + name + ".real",
                    '"SHELL=$R/runtime/bin/sh" ' if name == "make" else "")
    elf_wrapper("yosys", "runtime/yosys/yosys.real")
    elf_wrapper("yosys-abc", "runtime/yosys/yosys-abc.real")
    # Default ABC lookup also follows /proc/self/exe: keep both possible
    # sibling locations, for explicit loader and direct ELF invocation.
    copy(out / "runtime/bin/yosys-abc", "runtime/yosys/yosys-abc",
         "private-loader sibling for Yosys default ABC/ABC9 lookup")
    copy(out / "runtime/bin/yosys-abc", "runtime/lib/yosys-abc",
         "private-loader sibling when proc_self_dirname points to ld.so")
    write(out / "runtime/bin/python3", shell_header +
          'exec "$R/runtime/lib/ld-linux-x86-64.so.2" --inhibit-cache --library-path "$R/runtime/lib" '
          '"$R/runtime/python/bin/python3.10" -I -S -B -u "$R/runtime/python_dispatch.py" "$@"\n', True)
    for name, target in (("sby", "sby"), ("yosys-witness", "yosys-witness")):
        extra = ' --yosys "$R/runtime/bin/yosys" --abc "$R/runtime/bin/yosys-abc"' if name == "sby" else ""
        write(out / "runtime/bin" / name, shell_header +
              'exec "$R/runtime/bin/python3" "$R/runtime/sby/bin/' + target + '"' + extra + ' "$@"\n', True)
    write(out / "runtime/python_dispatch.py", '''"""Private CPython CLI dispatcher: no host site/user packages or old tools."""
import os, sys, runpy
from pathlib import Path
R = Path(__file__).resolve().parent.parent
sys.executable = str(R / "runtime/bin/python3")
os.environ["FPGA_PORTABLE_DISPATCH"] = str(Path(__file__).resolve())
sys.path[:0] = [str(R / p) for p in ("runtime/vendor", "runtime/eqy/share/yosys/python3", "runtime/sby/share/yosys/python3")]
args = sys.argv[1:]
while args and args[0] in ("-E", "-B", "-I", "-S", "-s", "-u", "-q"):
    args.pop(0)
if not args:
    raise SystemExit("This proof-runtime dispatcher requires a script, -c or -m")
if args[0] in ("--version", "-V"):
    print("Python " + sys.version.split()[0]); raise SystemExit(0)
if args[0] == "-c":
    code = args[1]; sys.argv = ["-c", *args[2:]]
    exec(compile(code, "<string>", "exec"), {"__name__":"__main__", "__builtins__":__builtins__})
elif args[0] == "-m":
    sys.argv = args[1:]; runpy.run_module(args[1], run_name="__main__", alter_sys=True)
else:
    target = Path(args[0]).resolve(); sys.argv = [str(target), *args[1:]]
    sys.path.insert(0, str(target.parent)); runpy.run_path(str(target), run_name="__main__")
''')
    write(out / "run_verify.sh", '#!/bin/sh\nset -eu\nunset LD_LIBRARY_PATH LD_PRELOAD PYTHONHOME PYTHONPATH PYTHONUSERBASE PYTHONSTARTUP PYTHONEXECUTABLE BASH_ENV ENV CDPATH MAKEFLAGS GNUMAKEFLAGS MAKEFILES MFLAGS\nb=${0%/*}\n[ "$b" != "$0" ] || b=.\n'
          'R=$(CDPATH= cd -- "$b" && pwd)\nexec "$R/runtime/bin/python3" "$R/portable_verify.py" "$@"\n', True)

    # Redistribute licenses alongside every copied Debian package dependency.
    # Query exact package ownership, never collect general /etc or home files.
    licensed_inputs = set(native) | {Path(p) for p in library_origins.values()} | {python, click_dir / "__init__.py"}
    packages = set()
    for p in sorted(licensed_inputs):
        q = subprocess.run(["/usr/bin/dpkg-query", "-S", str(p)], stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL, text=True, timeout=20)
        for line in q.stdout.splitlines():
            if ": " in line:
                packages.update(n.strip() for n in line.split(": ", 1)[0].split(","))
    package_versions = {}
    tree(Path("/usr/share/common-licenses"), "licenses/debian/common-licenses", "full common license texts referenced by Debian copyright notices")
    for package in sorted(packages):
        p = Path("/usr/share/doc") / package.split(":")[0] / "copyright"
        if p.is_file():
            copy(p, "licenses/debian/" + package.replace(":", "_") + ".copyright", "Debian package copyright/license notices")
        q = subprocess.run(["/usr/bin/dpkg-query", "-W", "-f=${Version}", package], stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL, text=True, timeout=20)
        package_versions[package] = q.stdout.strip()
    license_roots = {tools["baseline"].parent, tools["baseline"].parent.parent, eqy_prefix,
                     eqy_prefix.parent, sby_prefix, root}
    for base in license_roots:
        for name in ("COPYING", "LICENSE", "LICENSE.txt", "COPYRIGHT", "COPYING.txt"):
            p = base / name
            if p.is_file():
                license_sources.add(p.resolve())
    license_sources.update(p.resolve() for p in args.license_file)
    for i,p in enumerate(sorted(license_sources)):
        copy(p, "licenses/upstream/%03d-%s" % (i, p.name), "explicit upstream license/source notice")
    # Every Python source is syntax-checked by the same 3.10 parser used here.
    for p in out.rglob("*.py"):
        if "runtime/python/lib" not in p.as_posix():
            compile(p.read_bytes(), str(p), "exec")
    provenance = {"scope":"copy-only closure assembly; no compilation, synthesis or formal proofs",
        "source_manifest_sha256":sha(manifest_path), "yosys_commit":COMMIT,
        "origin_files":origins, "native_dependency_checks":ldd_results,
        "debian_package_versions":package_versions, "system":platform.platform(),
        "python_version":sys.version, "source_entries": {"eqy":sha(eqy), "sby":sha(sby), "witness":sha(witness)},
        "tool_versions": {"yosys":"0.69", "eqy":"0.69", "sby":"0.68"},
        "required_platform":"Linux x86_64 / compatible WSL2 Linux kernel; /bin/sh, /dev/null and writable temp storage",
        "os_configuration_or_credentials_copied":False}
    write(out / "provenance/closure.json", json.dumps(provenance, indent=2) + "\n")
    write(out / "README_PORTABLE_PROOF.md", '''# v23 actual Windows netlist proof kit

This separate package replays the preserved **eighteen actual Windows v23 post-ABC RTLIL objects**, plus the mandatory wrong-output negative control. It does not rebuild/re-measure Windows Yosys or replace the original Windows ZIP. The original frozen formal helpers, RTL, raw Windows report/manifest and raw RTLIL bytes are retained.

Platform: **Linux x86_64**, including a compatible WSL2 Linux distribution, a mounted `/proc`, `/dev/null`, `/bin/sh` for launching the relative entry, and writable temporary/output storage. CPython 3.10, its stdlib/extension-library closure, Click, original Yosys 0.69/ABC/share, EQY 0.69 plugins/modules, SBY 0.68, witness utility, GNU make/shell/text utilities, private ELF loader and shared libraries are included. No external Ubuntu repository, absolute historical tool manifest, OSS CAD Suite installation, Python site-packages, SMT solver or network service is required by the SAT/ABC-PDR proof strategy. This is **not native Windows EQY**. Portability remains subject to the Linux kernel/architecture boundary and the recorded relocation test.

Extract to a **new ASCII directory without spaces**, e.g. `/tmp/fpga-proof-v23-replay`. Keep the executable mode bits (use the `.tar.gz` distribution on Linux).

```sh
./run_verify.sh --preflight-only
./run_verify.sh
```

Every run creates a new `results/replay-*` directory. Success requires all 18 positive EQY proofs plus a definite counterexample for the intentional wrong-output control. Inspect `formal/report.json` and `portable-replay-receipt.json`. The initial copy operation and a preflight/version PASS are not a proof PASS.

`portable-index.json` binds the payload. `provenance/closure.json` lists sources, versions, dependency checks and file hashes; `licenses/` retains collected license notices. The runtime tool manifest is generated after relocation and all active proof paths refer inside this kit. The Linux `candidate` entry is explicitly an original-baseline parser alias: the optimized candidate being proved is the already-generated Windows RTLIL, not a newly synthesized Linux candidate.

Windows area/performance conclusions remain in the original measurements. Formal replay does not change them, establish performance on another machine, or guarantee future cases/onsite acceptance. Historical absolute Windows paths in preserved raw reports are metadata, not runtime dependencies.
''')
    files = {p.relative_to(out).as_posix():sha(p) for p in sorted(out.rglob("*")) if p.is_file()}
    index = {"schema":SCHEMA, "files":files, "yosys_release":"0.69", "yosys_commit":COMMIT,
        "windows_report_sha256":sha(out / "report.json"), "windows_manifest_sha256":sha(out / "manifest.json"),
        "windows_abc_script":abc_script, "sby_version":"SBY v0.68", "required_commands":list(COMMANDS),
        "tools":{"baseline":"runtime/bin/yosys", "abc":"runtime/bin/yosys-abc", "eqy":"runtime/eqy/bin/eqy",
            "candidate_aliases_baseline_for_actual_windows_proof_only":True,
            "baseline_binary_sha256":sha(tools["baseline"]), "abc_binary_sha256":sha(tools["abc"])},
        "formal_scope":"18 actual Windows v23 ILANG objects plus negative control; not performance or clean compilation",
        "platform":"Linux x86_64 / WSL2 Linux; private ELF loader, CPython and userspace proof dependencies included",
        "licenses":"licenses/ and original tool/module copyright notices"}
    write(out / "portable-index.json", json.dumps(index, indent=2) + "\n")
    print(json.dumps({"status":"COPY_ONLY_PORTABLE_KIT_ASSEMBLED_NOT_YET_PROVEN", "output":str(out),
        "files":len(files), "bytes":sum(p.stat().st_size for p in out.rglob("*") if p.is_file()),
        "portable_index_sha256":sha(out / "portable-index.json"),
        "next":["Copy/archive and extract into a fresh ASCII directory", "./run_verify.sh --preflight-only", "./run_verify.sh"]}, indent=2), flush=True)


if __name__ == "__main__":
    main()
