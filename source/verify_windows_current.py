"""Prove all eighteen actual Windows post-ABC RTLIL objects on pinned Linux EQY.

The evidence bundle retains the original Windows report and ILANG bytes.  Only
reversible newline normalization is allowed for the Linux parser.  No Windows
program is executed, and a formal PASS does not override performance evidence.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path, PureWindowsPath
import sys


DEFAULT_MANIFEST = "clean-v11/toolchains/yosys-0.69/competition-current/manifest.json"
MEASUREMENT_STATUSES = {"MEASUREMENTS_PASS_FORMAL_PENDING", "MEASUREMENTS_REVIEW_FORMAL_PENDING"}


def load_core(repo=None):
    candidates = []
    if repo is not None:
        candidates.append(Path(repo).resolve() / "scripts/verify_current_cases.py")
    candidates += [Path(__file__).resolve().with_name("verify_current_cases.py")]
    candidates += [p / "scripts/verify_current_cases.py" for p in (Path.cwd(), *Path(__file__).resolve().parents)]
    for path in candidates:
        if path.is_file():
            spec = importlib.util.spec_from_file_location("current_formal_core", path)
            core = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(core)
            return core, path
    raise RuntimeError("verify_current_cases.py is required beside this script or in repository scripts/")


def bundle_path(bundle, relative):
    path = Path(relative)
    windows = PureWindowsPath(relative)
    if path.is_absolute() or windows.is_absolute() or windows.drive or ".." in path.parts:
        raise RuntimeError("Evidence path must be bundle-relative: " + str(relative))
    resolved = (bundle / path).resolve()
    resolved.relative_to(bundle)
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    return resolved


def normalize_ilang(original, destination, sha):
    """Preserve raw bytes and check an exact inverse for the only conversion."""
    raw = original.read_bytes()
    normalized = raw.replace(b"\r\n", b"\n")
    if b"\r" in normalized:
        raise RuntimeError("Lone CR in original RTLIL; refusing additional text normalization")
    if b"\r\n" in raw:
        style = "CRLF"
        inverse = normalized.replace(b"\n", b"\r\n")
    else:
        style = "LF"
        inverse = normalized
    if inverse != raw:
        raise RuntimeError("Mixed or non-reversible RTLIL line endings")
    destination.write_bytes(normalized)
    return dict(original_sha256=sha(original), normalized_sha256=sha(destination),
                original_line_endings=style, normalization="CRLF to LF only" if style == "CRLF" else "none (already LF)",
                roundtrip_byte_equality=True, original_bytes=len(raw), normalized_bytes=len(normalized))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bundle", required=True, type=Path, help="Extracted Windows evidence directory")
    ap.add_argument("--repo", type=Path)
    ap.add_argument("--manifest", default=DEFAULT_MANIFEST, help="Pinned Linux proof-tool manifest")
    ap.add_argument("--output", type=Path)
    ap.add_argument("--strategy-timeout", type=int, default=300)
    args = ap.parse_args()
    core, core_path = load_core(args.repo)
    if core.os.name != "posix":
        ap.error("Run the proof toolchain on Linux")
    if args.strategy_timeout < 1:
        ap.error("--strategy-timeout must be positive")
    repo = core.find_repo(args.repo)
    bundle = args.bundle.resolve()
    if not bundle.is_dir():
        raise RuntimeError("--bundle must be an extracted evidence directory")
    manifest_path = core.resolve_path(repo, args.manifest)
    env, manifest, fingerprints, versions = core.load_environment(repo, manifest_path)
    raw_report_path = bundle_path(bundle, "report.json")
    windows_manifest_path = bundle_path(bundle, "manifest.json")
    cases_path = bundle_path(bundle, "cases_current.json")
    harness_path = bundle_path(bundle, "run_current_cases.py")
    meter_path = bundle_path(bundle, "windows_metrics.py")
    win = json.loads(raw_report_path.read_text(encoding="utf-8-sig"))
    windows_manifest = json.loads(windows_manifest_path.read_text(encoding="utf-8-sig"))
    registry = json.loads(cases_path.read_text(encoding="utf-8-sig"))
    registry_cases = registry["cases"] if isinstance(registry, dict) else registry
    if win.get("status") not in MEASUREMENT_STATUSES or win.get("formal_status") != "PENDING":
        raise RuntimeError("Windows measurement report is incomplete or has an unsupported prior formal status")
    if win.get("case_count") != 9 or len(win.get("cases", [])) != 9 or len(registry_cases) != 9:
        raise RuntimeError("Exactly nine completed Windows cases and eighteen proof objects are required")
    if str(windows_manifest.get("yosys_release")) != "0.69":
        raise RuntimeError("Windows manifest does not identify Yosys 0.69")
    bindings = {
        "manifest_sha256": windows_manifest_path,
        "case_manifest_sha256": cases_path,
        "harness_sha256": harness_path,
        "meter_sha256": meter_path,
    }
    for key, path in bindings.items():
        if core.sha(path).lower() != str(win.get(key, "")).lower():
            raise RuntimeError("Windows evidence fingerprint mismatch: " + key)
        fingerprints[str(path)] = core.sha(path)
    fingerprints[str(raw_report_path)] = core.sha(raw_report_path)
    fingerprints[str(core_path)] = core.sha(core_path)
    fingerprints[str(Path(__file__).resolve())] = core.sha(Path(__file__).resolve())
    fingerprints[str(manifest_path)] = core.sha(manifest_path)

    current_registry = json.loads((repo / "cases_current.json").read_text(encoding="utf-8"))
    current_entries = current_registry["cases"] if isinstance(current_registry, dict) else current_registry

    def identity(entry):
        name = str(entry.get("name", entry.get("id", "")))
        return name, str(entry.get("top", name)), str(entry["path"]), str(entry["sha256"]).lower()

    expected = {identity(entry)[0]:identity(entry) for entry in current_entries}
    supplied = {identity(entry)[0]:identity(entry) for entry in registry_cases}
    if len(expected) != 9 or len(supplied) != 9 or expected != supplied:
        raise RuntimeError("Windows and current Linux case registries do not identify the same nine immutable inputs")
    rows = {}
    for row in win["cases"]:
        name = str(row["name"])
        if name in rows or name not in supplied:
            raise RuntimeError("Duplicate or unexpected case in Windows report: " + name)
        case = supplied[name]
        if (name, str(row.get("top", name)), str(row["source_path"]), str(row["source_sha256"]).lower()) != case:
            raise RuntimeError("Windows measurement case identity mismatch: " + name)
        src = bundle_path(bundle, row["source_path"])
        if core.sha(src).lower() != case[3] or core.sha(core.source_path(repo, case[2])).lower() != case[3]:
            raise RuntimeError("Immutable source bytes changed: " + name)
        fingerprints[str(src)] = case[3]
        rows[name] = row
        for role in ("baseline", "candidate"):
            data = row["roles"][role]
            pinned_exe = windows_manifest["roles"][role]["files"]["yosys.exe"]
            if data["executable_sha256"].lower() != pinned_exe.lower():
                raise RuntimeError("Windows report executable does not match its manifest: " + name + " " + role)
            if not data.get("samples") or data.get("formal_object_status") != "EXPORTED_NOT_PROVED":
                raise RuntimeError("Missing measurements or incomplete Windows proof export: " + name + " " + role)
            ilang = bundle_path(bundle, data["path"] + "/postabc.il")
            if core.sha(ilang).lower() != data["ilang_sha256"].lower():
                raise RuntimeError("Actual Windows ILANG bytes changed: " + name + " " + role)
            fingerprints[str(ilang)] = core.sha(ilang)
    if set(rows) != set(supplied):
        raise RuntimeError("Missing Windows case report")

    # The small evidence bundle need not contain the executable payload.  State
    # exactly whether its SHA was recomputed or bound through report+manifest.
    pe_bindings = {}
    for role in ("baseline", "candidate"):
        digest = windows_manifest["roles"][role]["files"]["yosys.exe"].lower()
        payload = bundle / role / "yosys.exe"
        present = payload.is_file()
        if present:
            if core.sha(payload) != digest:
                raise RuntimeError("Included Windows executable payload changed: " + role)
            fingerprints[str(payload.resolve())] = digest
        pe_bindings[role] = dict(sha256=digest, payload_included=present,
                                verification="payload SHA recomputed" if present else "measurement report plus bound Windows manifest; payload not included")
    baseline_abc = windows_manifest["roles"]["baseline"]["files"]["yosys-abc.exe"]
    candidate_abc = windows_manifest["roles"]["candidate"]["files"]["yosys-abc.exe"]
    if baseline_abc.lower() != candidate_abc.lower():
        raise RuntimeError("Windows original/candidate bundled ABC identities differ")
    scripts = [name for name in windows_manifest["roles"]["candidate"]["files"]
               if name.endswith((".abc", ".script"))]
    if len(scripts) != 1:
        raise RuntimeError("Expected one fixed candidate ABC script resource for all cases")
    script = bundle_path(bundle, "candidate/" + scripts[0])
    script_digest = core.sha(script)
    if script_digest.lower() != windows_manifest["roles"]["candidate"]["files"][scripts[0]].lower():
        raise RuntimeError("Windows unified ABC script changed")
    fingerprints[str(script)] = script_digest
    if "abc_script" in manifest:
        if script.read_bytes().replace(b"\r\n", b"\n") != Path(manifest["abc_script"]).read_bytes().replace(b"\r\n", b"\n"):
            raise RuntimeError("Windows and pinned Linux tools use different fixed ABC script contents")

    if args.output:
        out = core.resolve_path(repo, args.output)
        if out.exists() and any(out.iterdir()):
            raise RuntimeError("Refusing to reuse nonempty proof output " + str(out))
        out.mkdir(parents=True, exist_ok=True)
    else:
        out = Path(core.tempfile.mkdtemp(prefix="windows-current-formal-", dir=repo / "clean-v11"))
    canonical = repo / "clean-v11/formal_cycloneiv.v"
    model = out / "formal_dffeas.v"
    core.extract_ff_model(canonical, model)
    fingerprints[str(canonical)] = core.sha(canonical)
    fingerprints[str(repo / "cases_current.json")] = core.sha(repo / "cases_current.json")
    report = dict(
        status="RUNNING", formal_status="RUNNING", directory=str(out), cases=[],
        started_utc=datetime.now(timezone.utc).isoformat(), expected_positive_proofs=18,
        windows_measurement_status=win["status"], performance_retested=False,
        overall_submission_acceptance=False,
        windows_report_sha256=core.sha(raw_report_path), windows_manifest_sha256=core.sha(windows_manifest_path),
        windows_case_manifest_sha256=core.sha(cases_path), windows_harness_sha256=core.sha(harness_path),
        windows_meter_sha256=core.sha(meter_path), windows_pe_executables=pe_bindings,
        windows_abc_sha256=baseline_abc, windows_unified_abc_script=dict(path="candidate/" + scripts[0], sha256=script_digest),
        linux_proof_manifest_sha256=core.sha(manifest_path), proof_engine_manifest=manifest,
        proof_engine_versions=versions, harness_sha256=core.sha(Path(__file__)), core_harness_sha256=core.sha(core_path),
        formal_model_sha256=core.sha(model), canonical_model_sha256=core.sha(canonical),
        proof_stage="Actual Windows-generated native post-ABC LUT RTLIL; original bytes SHA-bound to Windows measurements",
        proof_preparation="Only reversible CRLF-to-LF normalization; canonical dynamic-clrn dffeas plus standard lut2mux -word; SAT and ABC PDR",
        input_and_tool_fingerprints=fingerprints,
    )

    def save():
        (out / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    save()
    try:
        for case_entry in registry_cases:
            name, top, path, source_digest = identity(case_entry)
            src = bundle_path(bundle, path)
            windows_row = rows[name]
            row = dict(name=name, top=top, source_path=path, source_sha256=source_digest, roles={})
            report["cases"].append(row)
            for role in ("baseline", "candidate"):
                directory = out / name / role
                directory.mkdir(parents=True)
                item = dict(status="RUNNING", windows_executable_sha256=pe_bindings[role]["sha256"])
                row["roles"][role] = item
                save()
                try:
                    metadata = windows_row["roles"][role]
                    original = bundle_path(bundle, metadata["path"] + "/postabc.il")
                    normalized = directory / "postabc-lf.il"
                    normalization = normalize_ilang(original, normalized, core.sha)
                    if normalization["original_sha256"].lower() != metadata["ilang_sha256"].lower():
                        raise RuntimeError("Windows report ILANG fingerprint mismatch")
                    item.update(ilang_sha256=core.sha(original), normalized_ilang_sha256=core.sha(normalized), normalization=normalization)
                    audit_path = directory / "audit.json"
                    audit_flow = directory / "audit.ys"
                    audit_flow.write_text(f'read_verilog -lib "{model}"\nread_rtlil "{normalized}"\nwrite_json "{audit_path}"\n', encoding="utf-8")
                    execution = core.run([manifest["baseline"], "-Q", "-T", "-s", audit_flow], directory / "audit.log", env, 120, repo)
                    if execution["timed_out"] or execution["exit_code"]:
                        raise RuntimeError("Windows native RTLIL audit failed")
                    audit = core.audit_postabc(audit_path, top)
                    item.update(postabc_by_type=audit["by_type"], ff_control_audit=audit["dffeas_audit"],
                                dynamic_clrn_cells=audit["dynamic_clrn_cells"], audit_json_sha256=core.sha(audit_path),
                                audit_flow_sha256=core.sha(audit_flow), audit_log_sha256=core.sha(directory / "audit.log"),
                                windows_final_counts={key:metadata[key] for key in ("by_type", "lut_cells", "not_cells", "scored_logic_cells", "dff_cells", "total_cells") if key in metadata})
                    proof = core.prove(src, top, normalized, directory / "proof", env, manifest, model, repo, args.strategy_timeout)
                    item.update(status=proof["status"], proof=proof)
                except Exception as error:
                    item.update(status="ERROR", error=str(error))
                print(name, role, "ACTUAL_WINDOWS_EQY_" + item["status"], flush=True)
                save()

        negative = out / "negative"
        negative.mkdir()
        test2 = [entry for entry in registry_cases if identity(entry)[1] == "test2"]
        if len(test2) != 1:
            raise RuntimeError("The immutable test2 is required for the mandatory negative control")
        test2_src = bundle_path(bundle, identity(test2[0])[2])
        wrong = negative / "bad.v"
        wrong.write_text("module test2(input clk,a,b,c,d,input [4:0] dataa,datab,datac,datad,output [4:0] out); assign out=0; endmodule\n", encoding="utf-8")
        flow = negative / "flow.ys"
        flow.write_text(f'read_verilog "{wrong}"\nsynth_intel -family cycloneiv -top test2 -run begin:map_cells\nselect test2\nwrite_rtlil -selected "{negative}/bad.il"\n', encoding="utf-8")
        execution = core.run([manifest["baseline"], "-Q", "-T", "-s", flow], negative / "synthesis.log", env, 120, repo)
        if execution["timed_out"] or execution["exit_code"]:
            raise RuntimeError("Negative-control generation failed")
        negative_proof = core.prove(test2_src, "test2", negative / "bad.il", negative / "proof", env, manifest, model, repo, args.strategy_timeout)
        negative_ok = negative_proof["status"] == "FAIL" and negative_proof["definite_counterexample"]
        report["negative_control"] = dict(
            status="EXPECTED_COUNTEREXAMPLE" if negative_ok else "INVALID_NEGATIVE_CONTROL",
            method="Intentional constant-zero test2 output, generated by pinned Linux proof Yosys; same EQY proof chain",
            source_sha256=core.sha(test2_src), wrong_source_sha256=core.sha(wrong), ilang_sha256=core.sha(negative / "bad.il"),
            flow_sha256=core.sha(flow), proof=negative_proof)
        for path, digest in fingerprints.items():
            if core.sha(path).lower() != digest.lower():
                raise RuntimeError("Input/tool/evidence changed during proofs: " + path)
        states = [row["roles"][role]["status"] for row in report["cases"] for role in ("baseline", "candidate")]
        report["positive_proof_counts"] = dict(Counter(states))
        if not negative_ok or "ERROR" in states:
            status = "ERROR"
        elif "FAIL" in states:
            status = "FAIL"
        elif "UNKNOWN" in states:
            status = "UNKNOWN"
        elif len(states) == 18 and all(state == "PASS" for state in states):
            status = "PASS"
        else:
            status = "ERROR"
        report.update(status=status, formal_status=status, completed_utc=datetime.now(timezone.utc).isoformat())
        save()
        print("ACTUAL_WINDOWS_NINE_CASE_FORMAL_" + status, report["positive_proof_counts"], out, flush=True)
        return 0 if status == "PASS" else 2
    except Exception as error:
        report.update(status="ERROR", formal_status="ERROR", error=str(error), completed_utc=datetime.now(timezone.utc).isoformat())
        save()
        raise


if __name__ == "__main__":
    sys.exit(main())
