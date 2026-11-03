"""Copy a Windows package and diagnose its runtime and nine synthesis cases.

Only the copied embedded Python and copied Yosys/ABC are executed. This is not
formal performance acceptance, performs no meter controls, and runs no EQY.
Later acceptance must use another fresh extraction of the original package.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import time


ROLES = ("baseline", "candidate")
LAYOUT = "colocated_yosys_shared_runtime"
EXPECTED_SOURCE_SHA256 = "75ed360b73180441fccbe0f5f8ed3f10e1d07147842d38eb74baedc133ce47d2"
EXPECTED_PATCH_SHA256 = "9a52af4ea1ffec9b5f15ed509b014855089ce35487e94455589aa9d7e0b6a073"
EXPECTED_SCRIPT_SHA256 = "0ad315064a884d94676997ac6094cf7e679c7b0d3ff2d09431530b76d208c86e"
EXPECTED_ABC_RECIPE = "&dch -f; &if -K 4 -a -C 4 -F 3 -A 1"
PARENT_RUNNER_SHA256 = "0db05e1a8a3fde6edd9cc421e3449afa70caa4558178d2bd3e27b7739baaced6"
PARENT_MANIFEST_SHA256 = "8e9276621054adf00367875ad756bd5bc0d0741a421a35090d0c180bab5fcf57"
EXPECTED_REGISTRY_SHA256 = "6360cd97fb17315cc39ed6d6d8a21ce1d99dcc99b1541fe1a92d64dfeefc26da"
EXPECTED_METER_SHA256 = "2eb7ffc6564a40a09310e17be8e7b5746766ca148bbe1564d03cc533540496bf"
SHARED_NAMES = {"yosys-abc.exe", "libffi-8.dll", "libgcc_s_seh-1.dll",
                "libstdc++-6.dll", "libwinpthread-1.dll", "zlib1.dll"}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def digest(value):
    value = str(value).lower()
    require(re.fullmatch(r"[0-9a-f]{64}", value) is not None, "Invalid SHA-256")
    return value


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "Duplicate JSON key: " + key)
        result[key] = value
    return result


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"), object_pairs_hook=unique_object)


def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def relative(root, name):
    require(isinstance(name, str) and name and not PurePosixPath(name).is_absolute()
            and not any(c in name for c in ("\\", ":", '"', "\n", "\r", "\x00"))
            and not any(part in ("", ".", "..") for part in name.split("/")), "Unsafe package-relative path: " + repr(name))
    path = (root / name).resolve(strict=True)
    require(path.is_relative_to(root) and path.is_file(), "Missing/outside package file: " + name)
    return path


def tree_files(root, directory):
    base = root / directory
    require(base.is_dir() and base.resolve().is_relative_to(root), "Missing/outside package directory: " + directory)
    result = {}
    for path in sorted(base.rglob("*")):
        if path.is_file():
            name = path.relative_to(root).as_posix()
            result[name] = sha(relative(root, name))
    return result


def check_pins(root, pins):
    for name, expected in pins.items():
        require(sha(relative(root, name)) == digest(expected), "Input/tool changed: " + str(root / name))


def role_file(package, manifest, role, logical):
    return relative(package, manifest["roles"][role]["file_origins"][logical])


def collect_package(package):
    manifest = read_json(relative(package, "manifest.json"))
    require(str(manifest.get("yosys_release")) == "0.69", "Require Yosys 0.69")
    require(manifest.get("package_layout") == LAYOUT, "Require the explicit colocated shared-runtime layout")
    require(str(manifest.get("candidate_version", "")).startswith("v26"), "Require the new v26 package")
    require(digest(manifest.get("source_sha256")) == EXPECTED_SOURCE_SHA256,
            "Require the independently reviewed v26 packed-MUX source")
    require(digest(manifest.get("source_patch_sha256")) == EXPECTED_PATCH_SHA256 and
            digest(manifest.get("script_sha256")) == EXPECTED_SCRIPT_SHA256,
            "Require the frozen full v26 patch and uniform F3 recipe")
    pins = {}
    for folder in ("runtime", "share", "competition_case", "deployment-records"):
        pins.update(tree_files(package, folder))
    for name in ("manifest.json", "cases_current.json", "run_current_cases.py", "windows_metrics.py"):
        pins[name] = sha(relative(package, name))
    require(pins["run_current_cases.py"] == digest(manifest["runner_sha256"]),
            "Physical-layout runner differs from its declared identity")
    require(pins["windows_metrics.py"] == EXPECTED_METER_SHA256,
            "The frozen process measurement implementation must remain unchanged")
    require(pins["cases_current.json"] == EXPECTED_REGISTRY_SHA256 == digest(manifest["cases_current_sha256"]),
            "The frozen nine-case registry must remain unchanged")
    require(pins.get("deployment-records/runner-before.py") == PARENT_RUNNER_SHA256,
            "Missing frozen parent runner for the layout-only change audit")
    require(manifest.get("deployment_change") == "shared_runtime_same_binary_bytes",
            "Unexpected deployment change declaration")
    require(pins.get("deployment-records/parent-manifest.json") == digest(manifest["parent_deployment_manifest_sha256"]) == PARENT_MANIFEST_SHA256,
            "Parent package manifest identity differs from deployment declaration")
    records = manifest.get("deployment_records_sha256")
    require(isinstance(records, dict) and records and
            {name[len("deployment-records/"):]: value for name, value in pins.items() if name.startswith("deployment-records/")} ==
            {name: digest(value) for name, value in records.items()}, "Deployment records differ from their complete inventory")
    runner_audit = read_json(relative(package, "deployment-records/runner-change-audit.json"))
    require(runner_audit.get("status") == "PASS_EXACT_PATH_ONLY_REPLACEMENTS" and
            runner_audit.get("parent_runner_sha256") == PARENT_RUNNER_SHA256 and
            runner_audit.get("new_runner_sha256") == pins["run_current_cases.py"] and
            runner_audit.get("meter_sha256") == EXPECTED_METER_SHA256,
            "Runner audit is not bound to the actual parent/new runner and frozen meter")
    for flag in ("measurement_section_unchanged_after_two_exe_path_normalizations",
                 "warmups_reviews_thresholds_timing_memory_aggregation_unchanged",
                 "meter_self_test_and_measure_calls_unchanged"):
        require(runner_audit.get(flag) is True, "Runner audit did not preserve measurement semantics: " + flag)
    before = relative(package, "deployment-records/runner-before.py").read_text(encoding="utf-8")
    after = relative(package, "run_current_cases.py").read_text(encoding="utf-8")
    anchor = '    out = Path(tempfile.mkdtemp(prefix="validation-current-", dir=root))'
    require(before.count(anchor) == after.count(anchor) == 1, "Cannot identify the protected measurement section")
    protected_before = before[before.index(anchor):]
    protected_after = after[after.index(anchor):].replace('str(role_file(root, manifest, role, "yosys.exe"))',
                                                        'str(root / role / "yosys.exe")')
    require(protected_before == protected_after and
            hashlib.sha256(protected_before.encode("utf-8")).hexdigest() == runner_audit["protected_measurement_section_sha256"],
            "Measurement/report section changed beyond the two physical EXE paths")
    for name, expected in (("source/pmux_competition_v11.cc", EXPECTED_SOURCE_SHA256),
                           ("source/competition_abc_dch.abc", manifest["script_sha256"]),
                           ("source/synth-intel-competition.patch", manifest["source_patch_sha256"])):
        pins[name] = sha(relative(package, name))
        require(pins[name] == digest(expected), "Candidate source/recipe/patch differs from manifest: " + name)
    require(relative(package, "source/competition_abc_dch.abc").read_text(encoding="utf-8").strip() == EXPECTED_ABC_RECIPE,
            "Require the uniformly selected F3 recipe")
    require(sha(relative(package, "share/intel/competition_abc_v11.abc")) == digest(manifest["script_sha256"]),
            "Installed candidate recipe differs from the submitted source")
    runtime = manifest.get("runtime_sha256")
    require(isinstance(runtime, dict) and runtime, "Missing embedded runtime inventory")
    require({name[len("runtime/"):]: value for name, value in pins.items() if name.startswith("runtime/")} ==
            {name: digest(value) for name, value in runtime.items()}, "Runtime files differ from manifest")
    require("runtime/python.exe" in pins, "Missing embedded Python executable")
    shared = manifest.get("shared_files")
    require(isinstance(shared, dict) and set(shared) == SHARED_NAMES,
            "Require shared root ABC plus five DLLs")
    require(len({name.casefold() for name in shared}) == len(shared), "Case-aliased shared filenames")
    for name, expected in shared.items():
        require("/" not in name and (name == "yosys-abc.exe" or name.lower().endswith(".dll")), "Unexpected shared payload: " + name)
        pins[name] = sha(relative(package, name))
        require(pins[name] == digest(expected), "Shared payload changed: " + name)
    resources = manifest.get("shared_resources")
    require(isinstance(resources, dict) and resources and all(name.startswith("share/") for name in resources),
            "Missing complete shared resource inventory")
    require({name: value for name, value in pins.items() if name.startswith("share/")} ==
            {name: digest(value) for name, value in resources.items()}, "Shared resources differ from complete inventory")
    require(set(manifest["roles"]) == set(ROLES), "Unexpected package roles")
    logical_union = {}
    parent = read_json(relative(package, "deployment-records/parent-manifest.json"))
    for role in ROLES:
        record = manifest["roles"][role]
        files = record["files"]
        origins = record.get("file_origins")
        require(isinstance(origins, dict) and set(origins) == set(files), "Every logical role file needs an explicit origin: " + role)
        require(not (package / role).exists() and not (package / role).is_symlink(), "Legacy role directory may shadow shared runtime: " + role)
        require(files == parent["roles"][role]["files"], "Deployment changed the logical role bytes: " + role)
        require("yosys.exe" in files and SHARED_NAMES <= set(files), "Missing role executable/runtime pins")
        require(len({name.casefold() for name in files}) == len(files), "Case-aliased role filenames")
        require(digest(files["yosys-abc.exe"]) == digest(shared["yosys-abc.exe"]), "ABC identities differ: " + role)
        for logical, expected in files.items():
            physical = "yosys-" + role + ".exe" if logical == "yosys.exe" else logical
            require(logical == "yosys.exe" or logical in SHARED_NAMES or logical.startswith("share/"),
                    "Unexpected role payload: " + logical)
            require(origins[logical] == physical, "Unexpected role file origin: " + role + "/" + logical)
            actual = sha(role_file(package, manifest, role, logical))
            require(actual == digest(expected), "Physical role file identity mismatch: " + physical)
            require(logical_union.setdefault(physical, actual) == actual, "Different role bytes map to the same file: " + physical)
            pins[physical] = actual
            if logical in SHARED_NAMES:
                require(actual == digest(shared[logical]), "Role/shared runtime identities differ: " + logical)
    require({name: value for name, value in logical_union.items() if name.startswith("share/")} ==
            {name: digest(value) for name, value in resources.items()}, "Shared resource inventory is not the exact role union")
    actual_root_binaries = {p.name for p in package.iterdir() if p.is_file() and p.suffix.lower() in (".exe", ".dll")}
    require(actual_root_binaries == SHARED_NAMES | {"yosys-baseline.exe", "yosys-candidate.exe"},
            "Unexpected root executable/DLL could alter runtime lookup")
    return manifest, pins


def clean_environment(output):
    system_root = Path(os.environ["SystemRoot"]).resolve(strict=True)
    temp = output / "temporary"
    temp.mkdir(exist_ok=True)
    invalid_home, invalid_path = output / "INVALID_PYTHONHOME_DO_NOT_CREATE", output / "INVALID_PYTHONPATH_DO_NOT_CREATE"
    require(not invalid_home.exists() and not invalid_path.exists(), "Invalid Python paths unexpectedly exist")
    return dict(SystemRoot=str(system_root), WINDIR=str(system_root),
                COMSPEC=str(system_root / "System32/cmd.exe"),
                PATH=str(system_root / "System32") + ";" + str(system_root),
                PATHEXT=".COM;.EXE;.BAT;.CMD", TEMP=str(temp), TMP=str(temp), TMPDIR=str(temp),
                PYTHONHOME=str(invalid_home), PYTHONPATH=str(invalid_path), PYTHONDONTWRITEBYTECODE="1")


def run_copied(command, log_path, environment, package, timeout, neutral_cwd=None):
    executable = Path(command[0]).resolve(strict=True)
    require(executable.is_relative_to(package), "Refusing to execute an executable outside the diagnostic package copy")
    working_directory = package
    if neutral_cwd is not None:
        working_directory = Path(neutral_cwd).resolve(strict=True)
        require(working_directory == package.parent / "neutral-cwd" and working_directory.is_dir(),
                "Yosys diagnostics must use this output's dedicated neutral directory")
        require(not any(working_directory.iterdir()), "Neutral working directory must stay empty")
        require("YOSYS_DATDIR" not in environment and "ABC" not in environment and "YOSYS_ABC" not in environment,
                "Neutral-directory diagnostics must exercise automatic executable-directory lookup")
    started = time.perf_counter()
    with Path(log_path).open("xb") as log:
        process = subprocess.Popen([str(x) for x in command], cwd=working_directory, env=environment,
                                   stdout=log, stderr=subprocess.STDOUT)
        timed_out = False
        try:
            process.wait(timeout=timeout)
        except BaseException:
            # Cleanup only this launched process tree; never enumerate other jobs.
            timed_out = True
            killer = Path(environment["SystemRoot"]) / "System32/taskkill.exe"
            try:
                subprocess.run([str(killer), "/PID", str(process.pid), "/T", "/F"],
                               stdout=log, stderr=subprocess.STDOUT, env=environment, timeout=30, check=False)
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=30)
            raise
    return dict(command=[str(x) for x in command], cwd=str(working_directory), exit_code=process.returncode,
                diagnostic_elapsed_seconds=time.perf_counter() - started, timed_out=timed_out,
                log_sha256=sha(log_path))


def check_abc_log(text, package, role):
    pattern = r'Running ABC command:\s*(?:"([^"]+)"|\x27([^\x27]+)\x27|(\S+))'
    tokens = [next(group for group in match.groups() if group is not None) for match in re.finditer(pattern, text)]
    require(tokens, "No ABC launch command found in synthesis log")
    expected = (package / "yosys-abc.exe").resolve(strict=True)
    observed = []
    for token in tokens:
        normalized = token.replace("\\", "/")
        if normalized.lower() in ("<yosys-exe-dir>/yosys-abc", "<yosys-exe-dir>/yosys-abc.exe"):
            resolved = (package / "yosys-abc.exe").resolve(strict=True)
            interpretation = "Yosys abbreviated common executable directory"
        else:
            require(Path(normalized).is_absolute(), "Unexpected relative ABC command: " + token)
            if not normalized.lower().endswith(".exe"):
                normalized += ".exe"
            resolved = Path(normalized).resolve(strict=True)
            interpretation = "Absolute executable path from log"
        require(resolved == expected, "ABC command does not use this copy's shared root executable: " + token)
        observed.append(dict(log_token=token, resolved_path=str(resolved), interpretation=interpretation))
    return observed


def check_candidate_recipe_log(text, package, manifest):
    tokens = re.findall(r"(?m)^\s*ABC:\s+\+\s+source\s+(.+?)\s*$", text)
    require(len(tokens) == 1, "Candidate must source exactly one external F3 recipe")
    token = tokens[0].strip().strip('"').strip("'")
    normalized = token.replace("\\", "/")
    prefix = "<yosys-exe-dir>/"
    if normalized.startswith(prefix):
        resolved = (package / normalized[len(prefix):]).resolve(strict=True)
    else:
        require(Path(normalized).is_absolute(), "Unexpected relative candidate ABC recipe: " + token)
        resolved = Path(normalized).resolve(strict=True)
    expected = relative(package, "share/intel/competition_abc_v11.abc")
    require(resolved == expected, "ABC sourced a different candidate recipe: " + token)
    require(sha(resolved) == digest(manifest["script_sha256"]) and
            resolved.read_text(encoding="utf-8").strip() == EXPECTED_ABC_RECIPE,
            "Actual externally sourced recipe is not the pinned F3 file")
    return dict(log_token=token, resolved_path=str(resolved), sha256=sha(resolved),
                recipe=EXPECTED_ABC_RECIPE, delivery="external_source")


def worker(args):
    output, package = args.output.resolve(), args.package.resolve()
    require(package == output / "package", "Worker may only execute the dedicated output/package copy")
    require(Path(__file__).resolve() == output / "preflight_shared_runtime_package.py", "Worker must use its copied entry")
    require(Path(sys.executable).resolve() == package / "runtime/python.exe", "Worker must run the copied embedded Python")
    prepared = read_json(output / "prepared.json")
    require(prepared["copy_package"] == str(package) and prepared["original_package"] != str(package), "Missing dedicated-copy preparation")
    pins = prepared["copied_files"]
    check_pins(package, pins)
    manifest, current_pins = collect_package(package)
    require(current_pins == pins, "Diagnostic copy changed before worker launch")
    env = clean_environment(output)
    neutral_cwd = output / "neutral-cwd"
    neutral_cwd.mkdir(exist_ok=False)
    report = dict(status="RUNNING", scope="Copied-runtime and nine-case synthesis diagnostics only",
                  formal_status="NOT_RUN", performance_acceptance=False, overall_submission_acceptance=False,
                  source_resources_inherited=False, package=str(package), cases=[], versions={},
                  started_utc=datetime.now(timezone.utc).isoformat(), manifest_sha256=sha(package / "manifest.json"),
                  runner_sha256=sha(package / "run_current_cases.py"), case_registry_sha256=sha(package / "cases_current.json"),
                  yosys_working_directory=str(neutral_cwd),
                  yosys_lookup_policy="Absolute tool/input/output paths; fresh empty neutral cwd; no YOSYS_DATDIR/ABC/YOSYS_ABC override; clean system-only PATH")
    report_path = output / "diagnostic-report.json"
    save(report_path, report)
    try:
        require(sys.flags.isolated and sys.flags.no_site and sys.flags.ignore_environment and sys.dont_write_bytecode,
                "Embedded Python must run with -I -S -B")
        require(os.environ.get("PYTHONHOME") == env["PYTHONHOME"] and os.environ.get("PYTHONPATH") == env["PYTHONPATH"],
                "Deliberately invalid Python environment was not supplied")
        require(os.environ.get("PATH") == env["PATH"], "Python inherited an unexpected PATH")
        require(Path(sys.prefix).resolve().is_relative_to(package / "runtime"), "Python prefix escaped copied runtime")
        # The frozen python312._pth explicitly lists python312.zip, DLLs, '.',
        # and '..'. The final parent entry is needed for package-local helpers
        # such as windows_metrics.py. Permit exactly that copied package root,
        # not arbitrary directories outside runtime (nor arbitrary children).
        expected_python_path = [(package / name).resolve() for name in
                                ("runtime/python312.zip", "runtime/DLLs", "runtime", ".")]
        require([Path(value).resolve() for value in sys.path] == expected_python_path,
                "Python module search differs from the exact frozen runtime/package path list")
        report["embedded_python"] = dict(status="PASS", executable=sys.executable, version=sys.version,
                                         isolated=sys.flags.isolated, no_site=sys.flags.no_site,
                                         ignore_environment=sys.flags.ignore_environment, sys_path=sys.path,
                                         expected_sys_path=[str(path) for path in expected_python_path],
                                         path_policy="Exact frozen _pth order; parent entry restricted to this copied package root",
                                         prefix=sys.prefix, intentionally_invalid_pythonhome=os.environ["PYTHONHOME"],
                                         intentionally_invalid_pythonpath=os.environ["PYTHONPATH"], clean_path=os.environ["PATH"])
        save(output / "runtime-probe.json", report["embedded_python"])
        spec = importlib.util.spec_from_file_location("copied_package_counting", package / "run_current_cases.py")
        counter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(counter)
        cases = counter.load_cases(package, package / "cases_current.json")
        require(len(cases) == 9, "Nine immutable cases are required")
        # Version checks are diagnostic only and occur solely in this copy.
        for role in ROLES:
            path = output / (role + "-version.log")
            metadata = run_copied([role_file(package, manifest, role, "yosys.exe"), "--version"], path, env, package, args.timeout, neutral_cwd)
            text = path.read_text(encoding="utf-8", errors="replace").strip()
            require(metadata["exit_code"] == 0 and re.search(r"(?m)^Yosys 0\.69\s*\(", text), "Wrong/failed Yosys version: " + role)
            report["versions"][role] = dict(**metadata, text=text)
        save(report_path, report)
        for case in cases:
            row = dict(name=case["name"], top=case["top"], source_path=case["path"], source_sha256=case["sha256"], roles={})
            report["cases"].append(row)
            for role in ROLES:
                directory = output / "synthesis" / case["name"] / role
                directory.mkdir(parents=True, exist_ok=False)
                flow = directory / "flow.ys"
                read_option = " -sv" if case["source"].suffix.lower() == ".sv" else ""
                flow.write_text(f'read_verilog{read_option} "{case["source"].as_posix()}"\n'
                                f'synth_intel -family cycloneiv -top {case["top"]}\n'
                                f'write_verilog -norename -noattr "{directory.as_posix()}/netlist.v"\n'
                                f'write_json "{directory.as_posix()}/netlist.json"\n', encoding="utf-8")
                log = directory / "synthesis.log"
                metadata = run_copied([role_file(package, manifest, role, "yosys.exe"), "-Q", "-T", "-s", flow], log,
                                      env, package, args.timeout, neutral_cwd)
                item = dict(**metadata, flow_sha256=sha(flow), executable_sha256=manifest["roles"][role]["files"]["yosys.exe"],
                            directory=str(directory))
                row["roles"][role] = item
                save(report_path, report)
                require(metadata["exit_code"] == 0, "Synthesis failed: " + case["name"] + " " + role)
                text = log.read_text(encoding="utf-8", errors="replace")
                require("Executing ABC9 pass" in text, "ABC9 mapping was not observed")
                item["abc_log_commands"] = check_abc_log(text, package, role)
                versions = re.findall(r"Executing PMUX_COMPETITION_OPT\s+(v\d+)\.", text)
                if role == "candidate":
                    require(versions and all(version == "v26" for version in versions), "Candidate did not execute v26 PMUX pass")
                    item["candidate_recipe_in_log"] = check_candidate_recipe_log(text, package, manifest)
                else:
                    require(not versions and "PMUX_COMPETITION_OPT" not in text, "Baseline unexpectedly contains the competition pass")
                item["pmux_versions_in_log"] = versions
                require((directory / "netlist.v").is_file() and (directory / "netlist.v").stat().st_size > 0, "Missing Verilog output")
                item["counts"] = counter.counts(directory / "netlist.json", case["top"])
                item["netlist_json_sha256"] = sha(directory / "netlist.json")
                item["netlist_verilog_sha256"] = sha(directory / "netlist.v")
                item["status"] = "PASS"
                save(report_path, report)
            base, candidate = (row["roles"][role]["counts"] for role in ROLES)
            require(base["scored_logic_cells"] > 0, "Cannot calculate gain from zero baseline logic")
            row["logic_gain_percent"] = 100.0 * (base["scored_logic_cells"] - candidate["scored_logic_cells"]) / base["scored_logic_cells"]
            row["logic_nonincrease"] = candidate["scored_logic_cells"] <= base["scored_logic_cells"]
            row["dff_nonincrease"] = candidate["dff_cells"] <= base["dff_cells"]
            excluded = {"cycloneiv_lcell_comb", "$not", "$scopeinfo"}
            row["other_cell_types_nonincrease"] = all(count <= base["by_type"].get(kind, 0)
                                                       for kind, count in candidate["by_type"].items() if kind not in excluded)
            print(case["name"], base["scored_logic_cells"], candidate["scored_logic_cells"], row["logic_gain_percent"], flush=True)
            save(report_path, report)
        check_pins(package, pins)
        require(collect_package(package)[1] == pins, "Copied runtime/role/input file set changed during synthesis")
        require(not any(neutral_cwd.iterdir()), "Yosys left files in the neutral working directory")
        report.update(status="RUNTIME_SYNTHESIS_PREFLIGHT_PASS", completed_syntheses=18,
                      mean_per_case_logic_gain_percent=sum(row["logic_gain_percent"] for row in report["cases"]) / 9,
                      all_logic_nonincrease=all(row["logic_nonincrease"] for row in report["cases"]),
                      all_dff_nonincrease=all(row["dff_nonincrease"] for row in report["cases"]),
                      all_other_cell_types_nonincrease=all(row["other_cell_types_nonincrease"] for row in report["cases"]),
                      copied_inputs_and_tools_unchanged=True, neutral_working_directory_stayed_empty=True,
                      automatic_executable_directory_lookup_verified=True)
        # Current FAQ C130 makes DFF/other-cell observations diagnostic only.
        report["diagnostic_area_rule_satisfied"] = (report["mean_per_case_logic_gain_percent"] >= 20 and
                                                    report["all_logic_nonincrease"])
    except Exception as error:
        report.update(status="ERROR", error=str(error))
    finally:
        report["completed_utc"] = datetime.now(timezone.utc).isoformat()
        save(report_path, report)
    return 0 if report["status"] == "RUNTIME_SYNTHESIS_PREFLIGHT_PASS" else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path, help="New ASCII directory, never reused")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--internal-worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    require(os.name == "nt", "This diagnostic runs on Windows")
    require(math.isfinite(args.timeout) and args.timeout > 0, "Timeout must be finite and positive")
    if args.internal_worker:
        return worker(args)
    package = args.package.resolve(strict=True)
    output = args.output.resolve()
    require(output.as_posix().isascii(), "Diagnostic output must have an ASCII path")
    require(not output.exists() and not os.path.lexists(args.output), "Refusing an existing output directory")
    require(not output.is_relative_to(package) and not package.is_relative_to(output), "Output must be separate from original package")
    require(not Path(sys.executable).resolve().is_relative_to(package), "Launch this preparer with host Python, not the untouched package runtime")
    manifest, pins = collect_package(package)
    output.mkdir(parents=True, exist_ok=False)
    copied = output / "package"
    copied.mkdir()
    receipt = dict(status="COPYING", original_package=str(package), copy_package=str(copied),
                   performance_acceptance=False, formal_status="NOT_RUN", started_utc=datetime.now(timezone.utc).isoformat())
    save(output / "launch.json", receipt)
    try:
        for name, expected in pins.items():
            destination = copied / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(relative(package, name), destination)
            require(sha(destination) == expected, "Copy mismatch: " + name)
        check_pins(package, pins)
        check_pins(copied, pins)
        script = output / "preflight_shared_runtime_package.py"
        shutil.copyfile(Path(__file__).resolve(), script)
        entry_sha = sha(script)
        prepared = dict(original_package=str(package), copy_package=str(copied), copied_files=pins,
                        original_manifest_sha256=sha(package / "manifest.json"), launcher_sha256=entry_sha)
        save(output / "prepared.json", prepared)
        prepared_sha = sha(output / "prepared.json")
        command = [copied / "runtime/python.exe", "-I", "-S", "-B", "-X", "utf8", script,
                   "--internal-worker", "--package", copied, "--output", output, "--timeout", str(args.timeout)]
        receipt.update(status="RUNNING", command=[str(x) for x in command], copied_file_count=len(pins),
                       copied_manifest_sha256=sha(copied / "manifest.json"), launcher_sha256=entry_sha,
                       prepared_sha256=prepared_sha)
        save(output / "launch.json", receipt)
        result = run_copied(command, output / "worker-process.log", clean_environment(output), copied, args.timeout * 20 + 120)
        check_pins(package, pins)
        check_pins(copied, pins)
        require(collect_package(package)[1] == pins and collect_package(copied)[1] == pins,
                "Original/copied runtime/role/input file set changed during diagnostics")
        require(sha(script) == entry_sha and sha(output / "prepared.json") == prepared_sha, "Diagnostic harness/preparation changed")
        report = read_json(output / "diagnostic-report.json")
        require(result["exit_code"] == 0 and report.get("status") == "RUNTIME_SYNTHESIS_PREFLIGHT_PASS" and
                report.get("completed_syntheses") == 18, "Copied runtime/synthesis diagnostic did not pass")
        receipt.update(status="RUNTIME_SYNTHESIS_PREFLIGHT_PASS", worker=result,
                       report_sha256=sha(output / "diagnostic-report.json"), original_inputs_and_tools_unchanged=True,
                       copied_inputs_and_tools_unchanged=True, original_executables_run=False,
                       mean_per_case_logic_gain_percent=report["mean_per_case_logic_gain_percent"],
                       diagnostic_area_rule_satisfied=report["diagnostic_area_rule_satisfied"])
    except Exception as error:
        receipt.update(status="ERROR", error=str(error))
        try:
            check_pins(package, pins)
            receipt["original_inputs_and_tools_unchanged"] = True
        except Exception as changed:
            receipt.update(original_inputs_and_tools_unchanged=False, integrity_error=str(changed))
    finally:
        receipt["completed_utc"] = datetime.now(timezone.utc).isoformat()
        save(output / "launch.json", receipt)
    print(json.dumps(receipt, indent=2, ensure_ascii=False), flush=True)
    return 0 if receipt["status"] == "RUNTIME_SYNTHESIS_PREFLIGHT_PASS" else 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        print(json.dumps(dict(status="ERROR", error=str(error)), ensure_ascii=False), file=sys.stderr, flush=True)
        sys.exit(2)
