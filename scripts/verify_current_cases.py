"""Nine-case native post-ABC RTLIL EQY validation using pinned Linux tools.

Formal status is independent of resource savings and performance measurements.
No prior four-case report is trusted or required.  An optional --case selection
produces SUBSET_PASS, never the full eighteen-proof PASS status.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile


DEFAULT_MANIFEST = "clean-v11/toolchains/yosys-0.69/competition-current/manifest.json"
PINNED_COMMIT = "9f75ca1f9834a39a863915b5dae0c7b1e33533bc"
SAFE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")
CEX_PHRASES = ("model found: FAIL", "model found for base case: FAIL", "proof did fail")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def find_repo(explicit=None):
    if explicit:
        candidates = [Path(explicit).resolve()]
    else:
        candidates = [Path.cwd().resolve(), *Path(__file__).resolve().parents]
    for path in candidates:
        if (path / "cases_current.json").is_file() and (path / "clean-v11").is_dir():
            return path
    raise RuntimeError("Cannot locate repository containing cases_current.json and clean-v11; use --repo")


def resolve_path(repo, value):
    path = Path(value)
    return path.resolve() if path.is_absolute() else (repo / path).resolve()


def source_path(repo, value):
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("Case path must be repository-relative: " + str(value))
    path = (repo / path).resolve()
    path.relative_to(repo)
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def run(command, log, env, timeout, cwd):
    """Bound the whole subprocess group so timed-out proof children cannot leak."""
    with Path(log).open("w", encoding="utf-8") as handle:
        process = subprocess.Popen([str(x) for x in command], cwd=cwd, env=env,
                                   stdout=handle, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            return dict(exit_code=process.wait(timeout=timeout), timed_out=False)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            return dict(exit_code=process.returncode, timed_out=True)


def load_environment(repo, manifest_path):
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if str(manifest.get("yosys_release")) != "0.69":
        raise RuntimeError("Manifest does not identify Yosys 0.69")
    if manifest.get("yosys_commit", PINNED_COMMIT) != PINNED_COMMIT:
        raise RuntimeError("Manifest does not identify the pinned Yosys 0.69 source commit")
    for role in ("baseline", "candidate", "abc"):
        if role not in manifest or role + "_sha256" not in manifest:
            raise RuntimeError("Missing pinned tool identity " + role)
    fingerprints = {}
    for key in ("baseline", "candidate", "abc", "abc_script", "plugin_source", "patch", "integrated_source"):
        if key in manifest and isinstance(manifest[key], str):
            path = resolve_path(repo, manifest[key])
            expected = manifest.get(key + "_sha256")
            if expected is None:
                raise RuntimeError("Missing fingerprint for " + key)
            if not path.is_file() or sha(path).lower() != expected.lower():
                raise RuntimeError("Changed or missing manifest component " + key + ": " + str(path))
            manifest[key] = str(path)
            fingerprints[str(path)] = expected.lower()
    eqy = manifest.get("eqy")
    if not isinstance(eqy, dict):
        eqy_manifest = repo / "clean-v11/toolchains/eqy-0.69/manifest.json"
        if not eqy_manifest.is_file():
            raise RuntimeError("Current manifest has no EQY identity and the EQY 0.69 manifest is missing")
        eqy = json.loads(eqy_manifest.read_text(encoding="utf-8"))
    eqy = dict(eqy)
    eqy["executable"] = str(resolve_path(repo, eqy["executable"]))
    if not eqy.get("files"):
        digest = eqy.get("executable_sha256", eqy.get("sha256"))
        if not digest:
            raise RuntimeError("EQY manifest has no file fingerprints")
        eqy["files"] = {eqy["executable"]: digest}
    normalized = {}
    for name, digest in eqy["files"].items():
        path = resolve_path(repo, name)
        if not path.is_file() or sha(path).lower() != digest.lower():
            raise RuntimeError("EQY component changed: " + str(path))
        fingerprints[str(path)] = digest.lower()
        normalized[str(path)] = digest.lower()
    eqy["files"] = normalized
    manifest["eqy"] = eqy
    legacy_proof_paths = [repo / "clean-v11/proof-bin", repo / "clean-v11/toolchains/yosys-0.69/proof-bin"]
    wrapper_paths = {}
    proof_bin_value = manifest.get("proof_bin")
    if proof_bin_value:
        proof_bin = resolve_path(repo, proof_bin_value)
        if not proof_bin.is_dir():
            raise RuntimeError("The manifest proof_bin directory is missing: " + str(proof_bin))
        manifest["proof_bin"] = str(proof_bin)
        wrapper_hashes = manifest.get("proof_wrapper_hashes")
        if not isinstance(wrapper_hashes, dict) or not wrapper_hashes:
            raise RuntimeError("An independent proof_bin requires pinned proof_wrapper_hashes")
        normalized_hashes = {}
        for name, digest in wrapper_hashes.items():
            raw = Path(name)
            if raw.is_absolute():
                # Preserve the wrapper's lexical name even if it is a symlink;
                # sha() follows its target while PATH selection must select it.
                path = Path(os.path.abspath(str(raw)))
            elif len(raw.parts) == 1:
                path = proof_bin / raw
            elif (repo / raw).is_file():
                path = Path(os.path.abspath(str(repo / raw)))
            else:
                path = Path(os.path.abspath(str(proof_bin / raw)))
            if path.parent.resolve() != proof_bin:
                raise RuntimeError("Pinned proof wrapper is outside proof_bin: " + str(path))
            if not path.is_file() or sha(path).lower() != digest.lower():
                raise RuntimeError("Independent proof wrapper changed: " + str(path))
            if not os.access(path, os.X_OK):
                raise RuntimeError("Proof wrapper is not executable: " + str(path))
            if path.name in wrapper_paths:
                raise RuntimeError("Duplicate pinned proof wrapper name: " + path.name)
            wrapper_paths[path.name] = path
            normalized_hashes[str(path)] = digest.lower()
            fingerprints[str(path)] = digest.lower()
        if not {"sby", "yosys"}.issubset(wrapper_paths):
            raise RuntimeError("The independent proof_bin must pin both sby and yosys wrappers")
        manifest["proof_wrapper_hashes"] = normalized_hashes
        # Do not let missing names fall through into a previous candidate's
        # helper directory.  The fresh manifest's directory owns proof tools.
        proof_paths = [proof_bin]
        legacy_resolved = {str(path.resolve()) for path in legacy_proof_paths}
        inherited_path = [entry for entry in os.environ.get("PATH", "/usr/bin:/bin").split(os.pathsep)
                          if entry and str(Path(entry).resolve()) not in legacy_resolved]
    else:
        if manifest.get("proof_wrapper_hashes"):
            raise RuntimeError("proof_wrapper_hashes requires manifest.proof_bin")
        proof_paths = legacy_proof_paths
        inherited_path = os.environ.get("PATH", "/usr/bin:/bin").split(os.pathsep)
    env = dict(os.environ, PATH=os.pathsep.join([*(str(p) for p in proof_paths), *inherited_path]))
    env.pop("ABC", None)
    env.pop("YOSYS_DATDIR", None)
    for name, expected in wrapper_paths.items():
        selected = shutil.which(name, path=env["PATH"])
        if not selected or Path(os.path.abspath(selected)) != expected:
            raise RuntimeError("Independent proof wrapper is shadowed: " + name + " -> " + str(selected))
    versions = {}
    for role in ("baseline", "candidate"):
        version = subprocess.check_output([manifest[role], "-V"], env=env, cwd=repo, text=True, timeout=30).strip()
        if not version.startswith("Yosys 0.69 ("):
            raise RuntimeError("Wrong " + role + " Yosys version: " + version)
        versions[role] = version
    eqy_version = subprocess.check_output([sys.executable, "-E", "-B", eqy["executable"], "--version"],
                                          env=env, cwd=repo, text=True, timeout=30).strip()
    if eqy_version != "EQY v0.69":
        raise RuntimeError("Expected EQY v0.69, got " + eqy_version)
    versions["eqy"] = eqy_version
    sby = shutil.which("sby", path=env["PATH"])
    if not sby:
        raise RuntimeError("SBY is missing from the pinned proof environment")
    fingerprints[str(Path(sby).resolve())] = sha(sby)
    return env, manifest, fingerprints, versions


def extract_ff_model(canonical, output):
    text = canonical.read_text(encoding="utf-8")
    matches = re.findall(r"(?ms)^\s*module\s+dffeas\s*\(.*?^\s*endmodule\b", text)
    if len(matches) != 1:
        raise RuntimeError("Canonical file must contain exactly one dffeas module")
    model = matches[0].strip() + "\n"
    if not re.search(r"negedge\s+clrn", model) or not re.search(r"if\s*\(\s*!\s*clrn\s*\)", model):
        raise RuntimeError("The dffeas model must preserve dynamic active-low asynchronous clrn")
    output.write_text(model, encoding="utf-8")


def audit_postabc(path, top):
    module = json.loads(path.read_text(encoding="utf-8"))["modules"][top]
    cells = module.get("cells", {})
    by = Counter(cell["type"] for cell in cells.values())
    allowed = {"$lut", "dffeas", "$not", "$_NOT_", "$scopeinfo"}
    if set(by) - allowed:
        raise RuntimeError("Unsupported native post-ABC cells: " + repr(dict(by)))
    ff = []
    for name, cell in cells.items():
        if cell["type"] != "dffeas":
            continue
        conn = cell["connections"]
        for pin, expected in dict(prn="1", aload="0", asdata="0", sclr="0", sload="0").items():
            if conn.get(pin) != [expected]:
                raise RuntimeError("Unsupported dffeas control " + name + "." + pin + ": " + repr(conn.get(pin)))
        for pin in ("d", "clk", "clrn", "ena", "q"):
            if len(conn.get(pin, [])) != 1:
                raise RuntimeError("Missing or nonscalar dffeas pin " + name + "." + pin)
        for pin in ("clk", "clrn", "ena"):
            if not isinstance(conn[pin][0], int) and conn[pin][0] not in ("0", "1"):
                raise RuntimeError("Unknown-valued dffeas control " + name + "." + pin)
        parameters = cell.get("parameters", {})
        power_up = parameters.get("power_up", "dontcare")
        if power_up not in ("dontcare", "high", "low"):
            raise RuntimeError("Unsupported dffeas power_up " + repr(power_up))
        ff.append(dict(name=name, controls={pin:conn.get(pin) for pin in (
            "clk", "clrn", "prn", "ena", "asdata", "aload", "sclr", "sload")},
            parameters=parameters, dynamic_clrn=isinstance(conn["clrn"][0], int)))
    return dict(by_type=dict(by), dffeas_audit=ff, dynamic_clrn_cells=sum(f["dynamic_clrn"] for f in ff))


def final_counts(path, top):
    cells = json.loads(path.read_text(encoding="utf-8"))["modules"][top].get("cells", {})
    by = Counter(cell["type"] for cell in cells.values())
    if set(by) - {"cycloneiv_lcell_comb", "dffeas", "$not", "$scopeinfo"}:
        raise RuntimeError("Unsupported cells in final mapped netlist: " + repr(dict(by)))
    return dict(by_type=dict(by), lut_cells=by["cycloneiv_lcell_comb"], not_cells=by["$not"],
                scored_logic_cells=by["cycloneiv_lcell_comb"] + by["$not"], dff_cells=by["dffeas"],
                total_cells=sum(value for kind, value in by.items() if kind != "$scopeinfo"))


def prove(src, top, ilang, target, env, manifest, model, repo, strategy_timeout):
    config = target.with_suffix(".eqy")
    read_option = " -sv" if src.suffix.lower() == ".sv" else ""
    config.write_text(
        "[gold]\n" + f'read_verilog{read_option} "{src}"\nprep -top {top} -flatten\nmemory_map\nopt_clean\nrename -hide\n\n'
        + "[gate]\n" + f'read_rtlil "{ilang}"\nread_verilog -overwrite "{model}"\nlut2mux -word\nprep -top {top} -flatten\nmemory_map\nopt_clean\nrename -hide\n\n'
        + "[strategy simple]\nuse sat\ndepth 5\n\n[strategy pdr]\nuse sby\nengine abc pdr\n"
        + f"timeout {strategy_timeout}\n", encoding="utf-8")
    log = target.with_suffix(".log")
    execution = run([sys.executable, "-E", "-B", manifest["eqy"]["executable"],
                     "--yosys", manifest["baseline"], "--abc", manifest["abc"],
                     "-d", str(target), str(config)], log, env,
                    timeout=max(900, strategy_timeout * 3), cwd=repo)
    logs = list(target.rglob("*.log")) + [log]
    texts = [(p, p.read_text(encoding="utf-8", errors="replace")) for p in logs if p.is_file()]
    versions = sorted(set(version for _, text in texts
                          for version in re.findall(r"^Yosys .+$", text, re.M)))
    version_ok = bool(versions) and all(version.startswith("Yosys 0.69 (") for version in versions)
    evidence = []
    for evidence_path in list(target.rglob("logfile.txt")) + list(target.rglob("run.log")):
        text = evidence_path.read_text(encoding="utf-8", errors="replace")
        found = [phrase for phrase in CEX_PHRASES if phrase in text]
        if found:
            evidence.append(dict(path=str(evidence_path), sha256=sha(evidence_path), phrases=found))
    success = execution["exit_code"] == 0 and (target / "PASS").exists() and not (target / "FAIL").exists()
    definite_counterexample = (target / "FAIL").exists() and bool(evidence)
    if not version_ok:
        status = "ERROR"
    elif success:
        status = "PASS"
    elif definite_counterexample:
        status = "FAIL"
    else:
        status = "UNKNOWN"
    return dict(**execution, status=status, yosys_versions=versions, proof_engine_versions_valid=version_ok,
                config_sha256=sha(config), log_sha256=sha(log), path=str(target),
                definite_counterexample=definite_counterexample, counterexample_evidence=evidence,
                status_markers={name:(target / name).exists() for name in ("PASS", "FAIL", "UNKNOWN")})


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", type=Path)
    ap.add_argument("--manifest", default=DEFAULT_MANIFEST)
    ap.add_argument("--output", type=Path)
    ap.add_argument("--case", action="append", default=[], help="Case name/top; repeat or comma-separate for a diagnostic subset")
    ap.add_argument("--strategy-timeout", type=int, default=300)
    ap.add_argument("--synthesis-timeout", type=int, default=120)
    args = ap.parse_args()
    if os.name != "posix":
        ap.error("Execute this proof harness on the Linux proof toolchain")
    if args.strategy_timeout < 1 or args.synthesis_timeout < 1:
        ap.error("Timeouts must be positive")
    repo = find_repo(args.repo)
    manifest_path = resolve_path(repo, args.manifest)
    env, manifest, fingerprints, versions = load_environment(repo, manifest_path)
    registry_path = repo / "cases_current.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    cases = registry["cases"] if isinstance(registry, dict) else registry
    if len(cases) != 9:
        raise RuntimeError("The explicit current registry must contain exactly nine cases")
    names = set()
    for case in cases:
        case["name"] = str(case.get("name", case.get("id", "")))
        case["top"] = str(case.get("top", case["name"]))
        if not SAFE_NAME.fullmatch(case["name"]) or not SAFE_NAME.fullmatch(case["top"]) or case["name"] in names:
            raise RuntimeError("Invalid or duplicate case name/top")
        names.add(case["name"])
        src = source_path(repo, case["path"])
        if sha(src).lower() != case["sha256"].lower():
            raise RuntimeError("Source input fingerprint changed: " + case["name"])
        case["source"] = src
        fingerprints[str(src)] = case["sha256"].lower()
    requested = {name for item in args.case for name in item.split(",") if name}
    selected = [case for case in cases if not requested or case["name"] in requested or case["top"] in requested]
    matched = {name for name in requested if any(name in (case["name"], case["top"]) for case in selected)}
    if requested - matched:
        raise RuntimeError("Unknown case selection: " + repr(sorted(requested - matched)))
    full_run = len(selected) == len(cases)
    out = resolve_path(repo, args.output) if args.output else Path(tempfile.mkdtemp(prefix="current-formal-", dir=repo / "clean-v11"))
    if args.output:
        if out.exists() and any(out.iterdir()):
            raise RuntimeError("Refusing to reuse a nonempty proof evidence directory: " + str(out))
        out.mkdir(parents=True, exist_ok=True)
    canonical = repo / "clean-v11/formal_cycloneiv.v"
    model = out / "formal_dffeas.v"
    extract_ff_model(canonical, model)
    fingerprints[str(canonical)] = sha(canonical)
    fingerprints[str(registry_path)] = sha(registry_path)
    fingerprints[str(manifest_path)] = sha(manifest_path)
    report = dict(status="RUNNING", directory=str(out), report_dir=str(out), cases=[],
                  started_utc=datetime.now(timezone.utc).isoformat(), full_nine_case_run=full_run,
                  expected_positive_proofs=2 * len(selected), source_case_count=9,
                  selected_cases=[case["name"] for case in selected], manifest=manifest,
                  manifest_sha256=sha(manifest_path), registry_sha256=sha(registry_path),
                  harness_sha256=sha(Path(__file__)), tool_versions=versions,
                  formal_model_sha256=sha(model), canonical_model_sha256=sha(canonical),
                  proof_stage="Native $lut RTLIL after ABC9 and before final Cyclone IV LUT mapping",
                  proof_preparation="Standard lut2mux -word followed by SAT depth 5 and SBY ABC PDR",
                  ff_model="Canonical restricted dffeas module, dynamic clrn retained; all unsupported control pins checked",
                  performance_acceptance=False, area_acceptance=False,
                  input_and_tool_fingerprints=fingerprints)

    def save():
        (out / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    save()
    try:
        for case in selected:
            name, top, src = case["name"], case["top"], case["source"]
            row = dict(name=name, top=top, source_path=case["path"], source_sha256=sha(src), roles={})
            report["cases"].append(row)
            for role in ("baseline", "candidate"):
                directory = out / name / role
                directory.mkdir(parents=True)
                result = dict(status="RUNNING", executable_sha256=sha(manifest[role]))
                row["roles"][role] = result
                save()
                try:
                    read = f'read_verilog{" -sv" if src.suffix.lower() == ".sv" else ""} "{src}"\n'
                    full = directory / "full.ys"
                    full.write_text(read + f'synth_intel -family cycloneiv -top {top}\nwrite_json "{directory}/full-final.json"\n', encoding="utf-8")
                    full_execution = run([manifest[role], "-Q", "-T", "-s", full], directory / "full-synthesis.log", env, args.synthesis_timeout, repo)
                    if full_execution["timed_out"] or full_execution["exit_code"]:
                        raise RuntimeError("Complete synthesis failed: " + str(directory / "full-synthesis.log"))
                    final = final_counts(directory / "full-final.json", top)
                    split = directory / "split.ys"
                    split.write_text(read + f'synth_intel -family cycloneiv -top {top} -run begin:map_cells\n'
                                     + f'select {top}\nwrite_rtlil -selected "{directory}/postabc.il"\nselect *\n'
                                     + f'write_json "{directory}/postabc.json"\n'
                                     + f'synth_intel -family cycloneiv -top {top} -run map_cells:\nwrite_json "{directory}/split-final.json"\n', encoding="utf-8")
                    split_execution = run([manifest[role], "-Q", "-T", "-s", split], directory / "split-synthesis.log", env, args.synthesis_timeout, repo)
                    if split_execution["timed_out"] or split_execution["exit_code"]:
                        raise RuntimeError("Post-ABC export failed: " + str(directory / "split-synthesis.log"))
                    if "Executing ABC9 pass" not in (directory / "split-synthesis.log").read_text(encoding="utf-8", errors="replace"):
                        raise RuntimeError("ABC9 not observed in split synthesis")
                    if final_counts(directory / "split-final.json", top)["by_type"] != final["by_type"]:
                        raise RuntimeError("Split flow changed final cell counts compared with the independently run complete flow")
                    audit = audit_postabc(directory / "postabc.json", top)
                    result.update(postabc_by_type=audit["by_type"], ff_control_audit=audit["dffeas_audit"],
                                  dynamic_clrn_cells=audit["dynamic_clrn_cells"], final=final,
                                  ilang_sha256=sha(directory / "postabc.il"), postabc_json_sha256=sha(directory / "postabc.json"),
                                  full_flow_sha256=sha(full), split_flow_sha256=sha(split),
                                  full_final_sha256=sha(directory / "full-final.json"), split_final_sha256=sha(directory / "split-final.json"),
                                  full_synthesis_log_sha256=sha(directory / "full-synthesis.log"),
                                  split_synthesis_log_sha256=sha(directory / "split-synthesis.log"))
                    proof = prove(src, top, directory / "postabc.il", directory / "proof", env, manifest, model, repo, args.strategy_timeout)
                    result.update(status=proof["status"], proof=proof)
                except Exception as error:
                    result.update(status="ERROR", error=str(error))
                print(name, role, "CURRENT_POSTABC_EQY_" + result["status"], flush=True)
                save()
            if all("final" in row["roles"][role] for role in ("baseline", "candidate")):
                baseline, candidate = [row["roles"][role]["final"] for role in ("baseline", "candidate")]
                row["logic_cells_nonincrease"] = candidate["scored_logic_cells"] <= baseline["scored_logic_cells"]
                row["logic_gain_percent"] = 100 * (baseline["scored_logic_cells"] - candidate["scored_logic_cells"]) / baseline["scored_logic_cells"] if baseline["scored_logic_cells"] else None
            save()

        negative = out / "negative"
        negative.mkdir()
        test2 = [case for case in cases if case["top"] == "test2"]
        if len(test2) != 1:
            raise RuntimeError("Registry must retain exactly one immutable test2 for the mandatory negative control")
        wrong = negative / "bad.v"
        wrong.write_text("module test2(input clk,a,b,c,d,input [4:0] dataa,datab,datac,datad,output [4:0] out); assign out=0; endmodule\n", encoding="utf-8")
        flow = negative / "flow.ys"
        flow.write_text(f'read_verilog "{wrong}"\nsynth_intel -family cycloneiv -top test2 -run begin:map_cells\nselect test2\nwrite_rtlil -selected "{negative}/bad.il"\n', encoding="utf-8")
        execution = run([manifest["candidate"], "-Q", "-T", "-s", flow], negative / "synthesis.log", env, args.synthesis_timeout, repo)
        if execution["timed_out"] or execution["exit_code"]:
            raise RuntimeError("Negative-control synthesis failed")
        negative_proof = prove(test2[0]["source"], "test2", negative / "bad.il", negative / "proof", env, manifest, model, repo, args.strategy_timeout)
        negative_ok = negative_proof["status"] == "FAIL" and negative_proof["definite_counterexample"]
        report["negative_control"] = dict(status="EXPECTED_COUNTEREXAMPLE" if negative_ok else "INVALID_NEGATIVE_CONTROL",
                                           source_sha256=sha(test2[0]["source"]), wrong_source_sha256=sha(wrong),
                                           ilang_sha256=sha(negative / "bad.il"), flow_sha256=sha(flow), proof=negative_proof)
        for path, digest in fingerprints.items():
            if sha(path).lower() != digest:
                raise RuntimeError("Input/tool changed during validation: " + path)
        proof_states = [row["roles"][role]["status"] for row in report["cases"] for role in ("baseline", "candidate")]
        report["positive_proof_counts"] = dict(Counter(proof_states))
        gains = [row.get("logic_gain_percent") for row in report["cases"]]
        report["average_scored_logic_gain_percent_diagnostic"] = sum(gains) / len(gains) if all(g is not None for g in gains) else None
        report["all_logic_cells_nonincrease_diagnostic"] = all(row.get("logic_cells_nonincrease", False) for row in report["cases"])
        average = report["average_scored_logic_gain_percent_diagnostic"]
        if full_run and average is not None:
            report["area_acceptance"] = average >= 20 and report["all_logic_cells_nonincrease_diagnostic"]
            report["area_status"] = "PASS" if report["area_acceptance"] else "FAIL"
        else:
            report["area_status"] = "SUBSET_ONLY" if not full_run else "UNKNOWN"
        if not negative_ok or "ERROR" in proof_states:
            report["status"] = "ERROR"
        elif "FAIL" in proof_states:
            report["status"] = "FAIL"
        elif "UNKNOWN" in proof_states:
            report["status"] = "UNKNOWN"
        else:
            report["status"] = "PASS" if full_run else "SUBSET_PASS"
        report["completed_utc"] = datetime.now(timezone.utc).isoformat()
        save()
        print("CURRENT_NINE_CASE_AREA_" + report["area_status"], average, flush=True)
        print("CURRENT_NINE_CASE_FORMAL_" + report["status"], report["positive_proof_counts"], out, flush=True)
        return 0 if report["status"] in ("PASS", "SUBSET_PASS") else 2
    except Exception as error:
        report.update(status="ERROR", error=str(error), completed_utc=datetime.now(timezone.utc).isoformat())
        save()
        raise


if __name__ == "__main__":
    sys.exit(main())
