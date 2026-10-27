#!/usr/bin/env python3
"""Rebuild the current nine-case PMUX implementation in an independent Linux work tree.

This creates a fresh pinned upstream baseline before applying the exact working-tree
patch. Its final checks are Linux formal proofs and area diagnostics; they do not
establish the separate official Windows CPU/memory acceptance.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import inspect
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import time

YOSYS_COMMIT = "9f75ca1f9834a39a863915b5dae0c7b1e33533bc"
YOSYS_ARCHIVE_SHA = "086045e23253917b93c71fc2d9db495df3c153cdc5d212bac505df7c4ad62e2f"
EQY_COMMIT = "4a72eb94fc253062464afee4d0018359017bb846"
EQY_ARCHIVE_SHA = "dd1a4c5edcf83353c66e9765661cc332f4c7f6f122585c97da68290eab230291"
SAFE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def output(command, cwd=None, env=None):
    return subprocess.check_output([str(x) for x in command], cwd=cwd, env=env, text=True).strip()


def beneath(root, path):
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
    except ValueError:
        raise RuntimeError("Path escapes its extraction/input root: " + str(path))
    return Path(path)


def unpack(archive, destination, force_fallback=False):
    """Use the data filter when present, with a checked Python 3.10 fallback.

    All headers are checked before extraction. The fallback checks current parent
    resolution before each write and creates links only after regular files.
    Device nodes, FIFOs, absolute/traversing names and escaping links are refused.
    """
    destination = Path(destination).resolve()
    if destination.exists():
        raise RuntimeError("Refusing to overwrite source directory: " + str(destination))
    destination.mkdir(parents=True)
    with tarfile.open(archive) as bundle:
        members = bundle.getmembers()
        seen = {}
        for member in members:
            name = PurePosixPath(member.name)
            if name.is_absolute() or ".." in name.parts or "\\" in member.name or "\x00" in member.name:
                raise RuntimeError("Unsafe archive member name: " + member.name)
            if not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
                raise RuntimeError("Unsupported archive member type: " + member.name)
            key = name.as_posix()
            if key in seen and not (member.isdir() and seen[key].isdir()):
                raise RuntimeError("Duplicate archive payload: " + member.name)
            seen[key] = member
            target = destination.joinpath(*name.parts)
            beneath(destination, target)
            if member.issym() or member.islnk():
                link = PurePosixPath(member.linkname)
                if link.is_absolute() or "\\" in member.linkname or "\x00" in member.linkname:
                    raise RuntimeError("Unsafe archive link: " + member.name)
                linked = (target.parent if member.issym() else destination).joinpath(*link.parts)
                beneath(destination, linked)
        supports_filter = "filter" in inspect.signature(bundle.extractall).parameters
        if supports_filter and not force_fallback:
            bundle.extractall(destination, members=members, filter="data")
        else:
            # No filter keyword is passed to Python 3.10's tarfile API.
            for member in members:
                if member.issym() or member.islnk():
                    continue
                target = destination.joinpath(*PurePosixPath(member.name).parts)
                beneath(destination, target)
                beneath(destination, target.parent)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with bundle.extractfile(member) as source, target.open("xb") as sink:
                        shutil.copyfileobj(source, sink)
                    target.chmod(member.mode & 0o777)
            for member in members:
                if not (member.issym() or member.islnk()):
                    continue
                target = destination.joinpath(*PurePosixPath(member.name).parts)
                beneath(destination, target.parent)
                target.parent.mkdir(parents=True, exist_ok=True)
                linked = (target.parent if member.issym() else destination).joinpath(*PurePosixPath(member.linkname).parts)
                beneath(destination, linked)
                if target.exists() or target.is_symlink():
                    raise RuntimeError("Archive link would overwrite a path: " + member.name)
                if member.issym():
                    target.symlink_to(member.linkname)
                else:
                    if not linked.is_file() or linked.is_symlink():
                        raise RuntimeError("Archive hardlink target is not a regular file: " + member.name)
                    os.link(linked, target)
            # A newly created link can change resolution of an earlier link.
            for member in members:
                beneath(destination, destination.joinpath(*PurePosixPath(member.name).parts))


def find_repo(explicit=None):
    choices = [Path(explicit).resolve()] if explicit else [Path.cwd().resolve(), *Path(__file__).resolve().parents]
    for path in choices:
        if (path / "cases_current.json").is_file() and (path / "clean-v11").is_dir():
            return path
    raise RuntimeError("Cannot locate repository with cases_current.json and clean-v11; use --repo")


def normalized(path):
    return Path(path).read_text(encoding="utf-8").replace("\r\n", "\n")


def checked_file(path, expected):
    path = Path(path).resolve()
    if not path.is_file() or digest(path).lower() != expected.lower():
        raise RuntimeError("Missing or changed pinned file: " + str(path))
    return path


def copy_archive(origin, target, expected):
    origin = checked_file(origin, expected)
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        shutil.copy2(origin, target)
    checked_file(target, expected)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path)
    parser.add_argument("--dependencies", type=Path)
    parser.add_argument("--oss-suite", type=Path, default=Path.home() / "oss-cad-suite")
    parser.add_argument("--work", type=Path, help="New independent work directory; existing inputs must match its build plan")
    parser.add_argument("--cmake", type=Path)
    parser.add_argument("--jobs", type=int, default=1, choices=(1, 2))
    parser.add_argument("--eqy-mode", choices=("auto", "rebuild"), default="auto")
    parser.add_argument("--strategy-timeout", type=int, default=300)
    parser.add_argument("--synthesis-timeout", type=int, default=120)
    args = parser.parse_args()
    if sys.platform != "linux":
        parser.error("Run the reconstruction and formal verifier on Linux")
    if args.strategy_timeout < 1 or args.synthesis_timeout < 1:
        parser.error("Timeouts must be positive")
    repository = find_repo(args.repo)
    root = repository / "clean-v11"
    dependencies = (args.dependencies or repository.parent).resolve()
    old_root = dependencies / "clean-v11"
    work = (args.work if args.work and args.work.is_absolute() else
            repository / args.work if args.work else root / "toolchains/yosys-0.69-current").resolve()
    protected = [old_root.resolve(), (root / "toolchains/yosys-0.69").resolve(),
                 (root / "toolchains/eqy-0.69").resolve()]
    if work in (repository, root, *repository.parents) or any(path == work or path in work.parents for path in protected):
        raise RuntimeError("Choose a separate reconstruction directory with --work")
    work.mkdir(parents=True, exist_ok=True)
    source, build, logs = work / "src", work / "build-repro", work / "rebuild-logs"
    logs.mkdir(exist_ok=True)
    status_file, receipt_file = work / "build-current-status.json", root / "local-build-current-receipt.json"
    env = dict(os.environ, PATH="/usr/bin:/bin:" + os.environ.get("PATH", ""), CCACHE_DISABLE="1")
    for name in ("PYTHONHOME", "PYTHONPATH", "ABC", "YOSYS_DATDIR"):
        env.pop(name, None)

    def stage(name, **extra):
        write_json(status_file, dict(stage=name, utc=datetime.now(timezone.utc).isoformat(), **extra))
        print(name, flush=True)

    def run(command, logfile, cwd=None):
        with (logs / logfile).open("a", encoding="utf-8") as stream:
            stream.write("\nCOMMAND " + repr([str(x) for x in command]) + "\n")
            stream.flush()
            subprocess.run([str(x) for x in command], cwd=cwd, env=env, stdout=stream,
                           stderr=subprocess.STDOUT, check=True)

    receipt = dict(status="BUILD_IN_PROGRESS", repository=str(repository), work=str(work),
                   official_windows_performance_acceptance=False, competition_acceptance=False)
    retained_hashes = {}
    inputs = {}
    try:
        stage("checking_dependencies")
        for name in ("git", "make", "gcc", "g++", "bison", "flex", "pkg-config"):
            if not shutil.which(name, path=env["PATH"]):
                raise RuntimeError("Missing build dependency: " + name)
        subprocess.run(["pkg-config", "--exists", "tcl", "readline", "libffi", "zlib"], env=env, check=True)
        cmake = (args.cmake or dependencies / "toolchains/cmake-3.31.6/bin/cmake").resolve()
        suite = args.oss_suite.resolve()
        sby, build_python = suite / "bin/sby", suite / "bin/tabbypy3"
        for path in (cmake, sby, build_python):
            if not path.is_file():
                raise RuntimeError("Missing retained dependency: " + str(path))
            retained_hashes[str(path.resolve())] = digest(path)
        subprocess.run(["/usr/bin/python3", "-E", "-B", "-c", "import click"], env=env, check=True)
        if shutil.disk_usage(work).free < 4 * 2**30:
            raise RuntimeError("At least 4 GiB free space is required on the independent work filesystem")

        old_manifest = old_root / "toolchains/yosys-0.69/competition-v11/manifest.json"
        old_data = json.loads(old_manifest.read_text(encoding="utf-8"))
        if old_data.get("yosys_release") != "0.69" or old_data.get("yosys_commit") != YOSYS_COMMIT:
            raise RuntimeError("Retained baseline manifest is not the pinned Yosys 0.69")
        retained_hashes[str(old_manifest.resolve())] = digest(old_manifest)
        for role in ("baseline", "candidate", "abc"):
            path = Path(old_data[role])
            if not path.is_absolute():
                path = old_root / path
            path = checked_file(path, old_data[role + "_sha256"])
            retained_hashes[str(path)] = old_data[role + "_sha256"].lower()

        patch = root / "toolchains/yosys-0.69/competition-v11/synth-intel-competition.patch"
        plugin, canonical_plugin = root / "pmux_competition_v11.cc", repository / "src/pmux_competition_v11.cc"
        abc_script = root / "competition_abc_dch.abc"
        registry, verifier = repository / "cases_current.json", repository / "scripts/verify_current_cases.py"
        model = root / "formal_cycloneiv.v"
        if normalized(plugin) != normalized(canonical_plugin):
            raise RuntimeError("The two working-tree PMUX source copies differ")
        banner_match = re.search(r'log_header\s*\(\s*design\s*,\s*"([^"\n]*PMUX_COMPETITION_OPT[^"\n]*)"', normalized(plugin))
        if not banner_match:
            raise RuntimeError("Cannot identify the current pass banner in its working-tree source")
        expected_banner = banner_match.group(1).replace("\\n", "\n").strip()
        registered = json.loads(registry.read_text(encoding="utf-8"))
        cases = registered["cases"] if isinstance(registered, dict) else registered
        if len(cases) != 9:
            raise RuntimeError("The current registry must contain exactly nine explicit cases")
        names = set()
        case_paths = []
        for row in cases:
            name = str(row.get("name", row.get("id", "")))
            top = str(row.get("top", name))
            relative = Path(row["path"])
            if not SAFE_NAME.fullmatch(name) or not SAFE_NAME.fullmatch(top) or name in names:
                raise RuntimeError("Invalid or duplicate case identity")
            if relative.is_absolute() or ".." in relative.parts:
                raise RuntimeError("Case path must be repository-relative")
            path = beneath(repository, repository / relative).resolve()
            checked_file(path, row["sha256"])
            case_paths.append(path)
            names.add(name)
        for path in (Path(__file__).resolve(), plugin, canonical_plugin, abc_script, patch, registry, verifier, model, *case_paths):
            if not path.is_file():
                raise RuntimeError("Missing current build/validation input: " + str(path))
            inputs[str(path.resolve())] = digest(path)
        # HEAD is context only. Authorized, uncommitted source edits are bound
        # by their real working-tree hashes rather than silently rejected.
        head = output(["git", "rev-parse", "HEAD"], repository, env)
        tool_versions = {name: output([name, "--version"], env=env).splitlines()[0]
                         for name in ("gcc", "g++", "bison", "flex")}
        tool_versions["cmake"] = output([cmake, "--version"], env=env).splitlines()[0]
        plan = dict(schema=1, repository=str(repository), repository_commit_context=head,
                    working_tree_inputs=inputs, expected_pass_banner=expected_banner,
                    case_count=len(cases), work=str(work), compiler_versions=tool_versions,
                    cmake=str(cmake), build_python=str(build_python), eqy_mode=args.eqy_mode,
                    external_objects_copied=0, yosys_source_sha256=YOSYS_ARCHIVE_SHA,
                    eqy_source_sha256=EQY_ARCHIVE_SHA)
        plan_path = work / "rebuild-plan.json"
        if plan_path.exists():
            previous = json.loads(plan_path.read_text(encoding="utf-8"))
            incoming = dict(plan)
            # Committing unchanged working-tree inputs does not invalidate a
            # partially completed build. HEAD itself is provenance, not input.
            previous.pop("repository_commit_context", None)
            incoming.pop("repository_commit_context", None)
            if previous != incoming:
                raise RuntimeError("Build inputs changed; preserve this work tree and choose a new --work")
        else:
            if source.exists() or build.exists():
                raise RuntimeError("Unrecorded source/build directory; refusing to reuse it")
            write_json(plan_path, plan)
        copy_archive(old_root / "toolchains/yosys-0.69/source.tar.gz", work / "source.tar.gz", YOSYS_ARCHIVE_SHA)
        eqy_work = work / "eqy-0.69"
        copy_archive(old_root / "toolchains/eqy-0.69/source.tar", eqy_work / "source.tar", EQY_ARCHIVE_SHA)
        retained_hashes[str((old_root / "toolchains/yosys-0.69/source.tar.gz").resolve())] = YOSYS_ARCHIVE_SHA
        retained_hashes[str((old_root / "toolchains/eqy-0.69/source.tar").resolve())] = EQY_ARCHIVE_SHA

        if not source.exists():
            stage("extracting_pristine_yosys")
            unpack(work / "source.tar.gz", source)
        if output(["git", "rev-parse", "HEAD"], source, env) != YOSYS_COMMIT:
            raise RuntimeError("Wrong pinned Yosys source commit")
        cfg = [cmake, "-S", source, "-B", build, "-G", "Unix Makefiles",
               "-DCMAKE_BUILD_TYPE=Release", "-DCMAKE_C_COMPILER=/usr/bin/gcc",
               "-DCMAKE_CXX_COMPILER=/usr/bin/g++", "-DYOSYS_WITHOUT_SLANG=ON",
               "-DYOSYS_USE_BUNDLED_LIBS=ON", "-DBUILD_SHARED_LIBS=OFF", "-DYOSYS_WITH_PYTHON=OFF",
               "-DPython3_EXECUTABLE=" + str(build_python),
               "-DCMAKE_C_COMPILER_LAUNCHER=", "-DCMAKE_CXX_COMPILER_LAUNCHER="]
        compile_command = [cmake, "--build", build, "--parallel", str(args.jobs)]
        baseline, abc = build / "yosys-original", build / "yosys-abc"
        baseline_marker = work / "rebuild-baseline.json"
        integrated = source / "passes/opt/pmux_competition_opt.cc"
        if not baseline_marker.exists():
            if integrated.exists():
                raise RuntimeError("Refusing to build an upstream baseline from an already patched tree")
            subprocess.run(["git", "diff", "--quiet", "HEAD", "--"], cwd=source, env=env, check=True)
            stage("building_fresh_upstream_baseline", log=str(logs / "baseline.log"))
            run(cfg, "baseline.log", source)
            run(compile_command, "baseline.log", source)
            shutil.copy2(build / "yosys", baseline)
            write_json(baseline_marker, dict(baseline=digest(baseline), abc=digest(abc), source_commit=YOSYS_COMMIT))
        frozen = json.loads(baseline_marker.read_text(encoding="utf-8"))
        checked_file(baseline, frozen["baseline"])
        checked_file(abc, frozen["abc"])
        rejected = subprocess.run([str(baseline), "-Q", "-T", "-p", "pmux_competition_opt"], env=env,
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        if rejected.returncode == 0 or "No such command" not in rejected.stdout:
            raise RuntimeError("Fresh baseline unexpectedly contains the candidate pass")

        stage("applying_exact_working_tree_patch")
        patch_marker = work / "rebuild-patch.json"
        if not patch_marker.exists():
            if integrated.exists():
                raise RuntimeError("Unrecorded patched source; choose another --work")
            # Normalize archive checkout line endings only when identical to
            # their pinned HEAD after newline normalization.
            for name in ("passes/opt/CMakeLists.txt", "techlibs/intel/CMakeLists.txt", "techlibs/intel/synth_intel.cc"):
                path = source / name
                pristine = subprocess.check_output(["git", "show", "HEAD:" + name], cwd=source, env=env)
                if path.read_bytes().replace(b"\r\n", b"\n") != pristine.replace(b"\r\n", b"\n"):
                    raise RuntimeError("Unexpected source modification before patch: " + name)
                path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n"))
            run(["git", "apply", "--check", "--index", patch], "patch.log", source)
            run(["git", "apply", "--index", patch], "patch.log", source)
            write_json(patch_marker, dict(patch_sha256=digest(patch), index_tree=output(["git", "write-tree"], source, env)))
        applied = json.loads(patch_marker.read_text(encoding="utf-8"))
        if applied["patch_sha256"] != digest(patch) or applied["index_tree"] != output(["git", "write-tree"], source, env):
            raise RuntimeError("Applied source index no longer matches the recorded exact patch")
        subprocess.run(["git", "diff", "--quiet", "--"], cwd=source, env=env, check=True)
        run(["git", "apply", "--check", "--reverse", "--index", patch], "patch.log", source)
        if normalized(integrated) != normalized(plugin):
            raise RuntimeError("Exact patch implementation differs from the working-tree source")
        integrated_script = source / "techlibs/intel/competition_abc_v11.abc"
        if normalized(integrated_script).strip() != normalized(abc_script).strip():
            raise RuntimeError("Exact patch ABC script differs from the working-tree script")

        stage("building_current_candidate", log=str(logs / "candidate.log"))
        run(cfg, "candidate.log", source)
        run(compile_command, "candidate.log", source)
        candidate = build / "yosys-competition-current"
        shutil.copy2(build / "yosys", candidate)
        checked_file(baseline, frozen["baseline"])
        checked_file(abc, frozen["abc"])
        subprocess.run(["git", "diff", "--quiet", "--"], cwd=source, env=env, check=True)
        versions = {role: output([path, "-V"], env=env)
                    for role, path in (("baseline", baseline), ("candidate", candidate))}
        if any(not value.startswith("Yosys 0.69 (") for value in versions.values()):
            raise RuntimeError("A fresh binary does not identify Yosys 0.69: " + repr(versions))
        help_text = output([candidate, "-Q", "-T", "-p", "help pmux_competition_opt"], env=env)
        banner = output([candidate, "-Q", "-T", "-p", "pmux_competition_opt"], env=env)
        if "pmux_competition_opt" not in help_text or expected_banner not in banner:
            raise RuntimeError("Compiled candidate does not match the current source banner")
        (logs / "candidate-version-check.log").write_text(help_text + "\n" + banner + "\n", encoding="utf-8")
        mapping = build / "share/intel/competition_abc_v11.abc"
        if normalized(mapping).strip() != normalized(abc_script).strip():
            raise RuntimeError("Built ABC9 mapping script differs from the working-tree script")

        stage("preparing_pinned_proof_environment")
        proof = work / "proof-bin"
        proof.mkdir(exist_ok=True)
        link = proof / "yosys"
        if link.is_symlink():
            if link.resolve() != baseline.resolve():
                raise RuntimeError("Unexpected proof Yosys link")
        elif link.exists():
            raise RuntimeError("Unexpected existing proof executable")
        else:
            link.symlink_to(baseline)
        wrapper = proof / "sby"
        wrapper_text = ("#!/bin/sh\nexec " + shlex.quote(str(sby)) + " --yosys " +
                        shlex.quote(str(baseline)) + " --abc " + shlex.quote(str(abc)) + ' "$@"\n')
        if wrapper.exists() and wrapper.read_text(encoding="utf-8") != wrapper_text:
            raise RuntimeError("Existing independent SBY wrapper changed")
        wrapper.write_text(wrapper_text, encoding="utf-8")
        wrapper.chmod(0o755)
        env["PATH"] = str(proof) + os.pathsep + env["PATH"]

        eqy_manifest = None
        if args.eqy_mode == "auto":
            for path in (root / "toolchains/eqy-0.69/manifest.json", old_root / "toolchains/eqy-0.69/manifest.json"):
                if not path.is_file():
                    continue
                retained = json.loads(path.read_text(encoding="utf-8"))
                if (retained.get("commit") != EQY_COMMIT or retained.get("version") != "EQY v0.69" or
                        retained.get("source_sha256") != EQY_ARCHIVE_SHA or not retained.get("files")):
                    continue
                # A full matching retained manifest must be intact; a mismatch
                # is an error, not permission to silently bless different files.
                files = {str(checked_file(name, checksum)): checksum.lower() for name, checksum in retained["files"].items()}
                executable = Path(retained["executable"]).resolve()
                if str(executable) not in files:
                    raise RuntimeError("Retained EQY executable lacks a manifest fingerprint")
                if output(["/usr/bin/python3", "-E", "-B", executable, "--version"], env=env) != "EQY v0.69":
                    raise RuntimeError("Retained EQY runtime version changed")
                eqy_manifest = dict(retained, files=files, executable=str(executable), retained_manifest=str(path.resolve()),
                                    retained_manifest_sha256=digest(path), reused_matching_files=True)
                retained_hashes[str(path.resolve())] = digest(path)
                retained_hashes.update(files)
                break
        if eqy_manifest is None:
            stage("building_independent_eqy_069")
            eqy_source, prefix = eqy_work / "src-repro", eqy_work / "install-repro"
            if not eqy_source.exists():
                unpack(eqy_work / "source.tar", eqy_source)
            if (eqy_source / ".gittag").read_text(encoding="utf-8").strip() != "v0.69":
                raise RuntimeError("Wrong EQY source release tag")
            run(["make", "-j" + str(args.jobs), "install", "YOSYS_CONFIG=" + str(build / "yosys-config"),
                 "PREFIX=" + str(prefix)], "eqy.log", eqy_source)
            executable = prefix / "bin/eqy"
            eqy_version = output(["/usr/bin/python3", "-E", "-B", executable, "--version"], env=env)
            if eqy_version != "EQY v0.69":
                raise RuntimeError("Wrong EQY runtime version")
            eqy_manifest = dict(commit=EQY_COMMIT, version=eqy_version, source_sha256=EQY_ARCHIVE_SHA,
                                executable=str(executable), reused_matching_files=False,
                                files={str(path.resolve()): digest(path) for path in sorted(prefix.rglob("*")) if path.is_file()})
        for path in (wrapper, link, sby):
            eqy_manifest["files"][str(path)] = digest(path)
        write_json(eqy_work / "manifest.json", eqy_manifest)
        manifest = dict(schema=2, yosys_release="0.69", yosys_commit=YOSYS_COMMIT,
                        source_sha256=YOSYS_ARCHIVE_SHA, repository_commit_context=head,
                        repository_working_tree_inputs=inputs, build_work=str(work),
                        baseline=str(baseline), candidate=str(candidate), abc=str(abc),
                        patch=str(patch), plugin_source=str(plugin), abc_script=str(mapping),
                        integrated_source=str(integrated), proof_bin=str(proof),
                        proof_wrapper_hashes={str(path): digest(path) for path in (wrapper, link)},
                        eqy=eqy_manifest,
                        build_config=[str(x) for x in cfg], external_objects_copied=0,
                        baseline_version=versions["baseline"], candidate_version=versions["candidate"],
                        expected_pass_banner=expected_banner,
                        acceptance_scope="Linux formal proofs and area diagnostics; Windows performance is separate")
        for role in ("baseline", "candidate", "abc", "patch", "plugin_source", "abc_script", "integrated_source"):
            manifest[role + "_sha256"] = digest(manifest[role])
        manifest_path = root / "toolchains/yosys-0.69/competition-current/manifest.json"
        before = work / "manifest-before-rebuild.json"
        if manifest_path.is_file() and not before.exists():
            shutil.copy2(manifest_path, before)
        write_json(manifest_path, manifest)
        write_json(work / "built-manifest.json", manifest)

        for path, checksum in {**retained_hashes, **inputs}.items():
            checked_file(path, checksum)
        # The verifier must actually prioritize the manifest's proof_bin; an
        # old repository SBY wrapper must not silently select old binaries.
        preflight = (
            "import pathlib,runpy,shutil,sys; "
            "ns=runpy.run_path(sys.argv[1]); "
            "env=ns['load_environment'](pathlib.Path(sys.argv[2]),pathlib.Path(sys.argv[3]))[0]; "
            "actual=shutil.which('sby',path=env['PATH']); "
            "assert actual and pathlib.Path(actual).resolve()==pathlib.Path(sys.argv[4]).resolve(), "
            "'Verifier must prioritize manifest proof_bin rather than an old proof wrapper'; "
            "print('CURRENT_PROOF_WRAPPER_VERIFIED',actual)"
        )
        run(["/usr/bin/python3", "-E", "-B", "-c", preflight, verifier,
             repository, manifest_path, wrapper], "proof-preflight.log", repository)
        proof_out = work / ("formal-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + str(os.getpid()))
        stage("running_current_nine_case_linux_formal", log=str(logs / "validation.log"))
        verification_command = ["/usr/bin/python3", "-E", "-B", "-u", str(verifier),
                                "--repo", str(repository), "--manifest", str(manifest_path),
                                "--output", str(proof_out), "--strategy-timeout", str(args.strategy_timeout),
                                "--synthesis-timeout", str(args.synthesis_timeout)]
        with (logs / "validation.log").open("a", encoding="utf-8") as stream:
            stream.write("\nCOMMAND " + repr(verification_command) + "\n")
            stream.flush()
            verification = subprocess.run(verification_command, cwd=repository, env=env,
                                          stdout=stream, stderr=subprocess.STDOUT)
        report = json.loads((proof_out / "report.json").read_text(encoding="utf-8"))
        for path, checksum in {**retained_hashes, **inputs}.items():
            checked_file(path, checksum)
        checked_file(baseline, frozen["baseline"])
        checked_file(abc, frozen["abc"])
        checked_file(manifest_path, digest(work / "built-manifest.json"))
        positive = report.get("positive_proof_counts", {})
        formal_ok = (verification.returncode == 0 and report.get("status") == "PASS" and
                     report.get("full_nine_case_run") is True and positive.get("PASS") == 2 * len(cases) and
                     sum(positive.values()) == 2 * len(cases) and
                     report.get("negative_control", {}).get("status") == "EXPECTED_COUNTEREXAMPLE")
        nonlogic = []
        for row in report.get("cases", []):
            counts = [row.get("roles", {}).get(role, {}).get("final", {}).get("by_type") for role in ("baseline", "candidate")]
            nonlogic.append(bool(all(isinstance(value, dict) for value in counts)) and all(
                counts[1].get(kind, 0) <= counts[0].get(kind, 0)
                for kind in set(counts[0]) | set(counts[1])
                if kind not in ("cycloneiv_lcell_comb", "$not", "$scopeinfo")))
        average = report.get("average_scored_logic_gain_percent_diagnostic")
        receipt.update(status="LINUX_FORMAL_PASS_WINDOWS_PERFORMANCE_PENDING" if formal_ok else "LINUX_FORMAL_REVIEW_REQUIRED",
                       repository_commit_context=head, manifest=str(manifest_path), manifest_sha256=digest(manifest_path),
                       source_input_sha256=inputs, retained_environment_sha256=retained_hashes,
                       external_objects_copied=0, original_environment_unchanged=True,
                       linux_formal=dict(status=report.get("status"), report=str(proof_out / "report.json"),
                                         report_sha256=digest(proof_out / "report.json"), positive_proof_counts=positive,
                                         expected_positive_proofs=2 * len(cases), negative_control=report.get("negative_control")),
                       linux_area_diagnostic=dict(average_scored_logic_gain_percent=average,
                                                  average_20pct_target_met=average is not None and average >= 20,
                                                  all_logic_cells_nonincrease=report.get("all_logic_cells_nonincrease_diagnostic"),
                                                  all_other_cell_types_nonincrease=len(nonlogic) == len(cases) and all(nonlogic)),
                       official_windows_performance=dict(status="NOT_RUN_BY_THIS_BUILDER", cpu_includes_abc=True,
                                                         memory_scope="yosys.exe peak working set",
                                                         note="Requires separate matched Windows binaries and measurements"),
                       completed_utc=datetime.now(timezone.utc).isoformat())
        write_json(receipt_file, receipt)
        write_json(work / "build-current-receipt.json", receipt)
        stage(receipt["status"], receipt=str(receipt_file))
        print(json.dumps(receipt, indent=2), flush=True)
        return 0 if formal_ok else 2
    except Exception as error:
        receipt.update(status="BUILD_OR_LINUX_VERIFICATION_ERROR", error=str(error),
                       completed_utc=datetime.now(timezone.utc).isoformat())
        write_json(receipt_file, receipt)
        write_json(work / "build-current-receipt.json", receipt)
        stage("ERROR", error=str(error), receipt=str(receipt_file))
        raise


if __name__ == "__main__":
    sys.exit(main())
