"""Verify frozen tools and prove 18 actual Windows netlists using Linux EQY.

Run inside WSL/Linux. No Windows executable is run and no performance result is
replaced. --preflight-only is read-only; --run-proofs requires a new output root.
The extracted evidence bundle keeps its original Windows report and raw RTLIL.
A derived proof manifest changes only the current Windows ABC recipe identity.
Archived Linux tools, helper code, strategies and models remain frozen.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys


FROZEN_INDEX_SHA256 = "ac50f798b70f4a105f8ad42e12ed16b03bb9ed87ce2ff2ad0194cdf66c4c6cd9"
FROZEN_HELPER_SHA256 = "7f8a8484e9886065a508aba1a2244ee74cabcc134dd06d230423e0d7e1b8731d"
FROZEN_CORE_SHA256 = "9ae28d47bd5c911777336cfdb195676c345a3cd871755056fca6d0309fc8f843"
MEASUREMENT_STATUSES = {"MEASUREMENTS_PASS_FORMAL_PENDING", "MEASUREMENTS_REVIEW_FORMAL_PENDING"}
DIGEST = re.compile(r"^[0-9a-f]{64}$")


def require(condition, message):
    # Deliberately not assert: checks remain active under python -O.
    if not condition:
        raise RuntimeError(message)


def digest(value):
    value = str(value).lower()
    require(DIGEST.fullmatch(value), "Expected a SHA-256 digest: " + value)
    return value


def sha(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "Duplicate JSON key: " + key)
        result[key] = value
    return result


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"), object_pairs_hook=unique_object)


def safe_path(value, must_exist=True):
    value = os.fspath(value)
    require(not any(c in value for c in ('"', "\n", "\r", "\x00")), "Unsafe path for proof script: " + repr(value))
    return Path(value).expanduser().resolve(strict=must_exist)


def inside(root, relative):
    require(isinstance(relative, str), "Inventory path must be a string")
    p = PurePosixPath(relative)
    require(relative and not p.is_absolute() and not any(c in relative for c in ("\\", ":", '"', "\n", "\r", "\x00"))
            and not any(c in ("", ".", "..") for c in relative.split("/")), "Unsafe relative path: " + repr(relative))
    path = (root / relative).resolve(strict=True)
    require(path.is_relative_to(root) and path.is_file(), "File escapes root or is missing: " + relative)
    return path


def check_hash(path, expected):
    expected = digest(expected)
    require(sha(path) == expected, "SHA-256 mismatch: " + str(path))
    return expected


def entries(registry):
    values = registry["cases"] if isinstance(registry, dict) else registry
    require(isinstance(values, list) and len(values) == 9, "Exactly nine registry entries required")
    result = {}
    for value in values:
        name = str(value.get("name", value.get("id", "")))
        require(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", name) is not None and name not in result,
                "Unsafe or duplicate case name: " + name)
        result[name] = (name, str(value.get("top", name)), str(value["path"]), digest(value["sha256"]))
    return result


def check_windows_layout(bundle, windows_manifest, evidence):
    """Verify every physical runtime file and the three explicitly copied proof aliases."""
    layout = windows_manifest.get("package_layout")
    require(layout == "colocated_yosys_shared_runtime", "Unsupported shared runtime layout")
    shared = windows_manifest["shared_files"]
    require(len(shared) == 6 and "yosys-abc.exe" in shared, "Expected ABC plus five common DLLs")
    for name, expected in shared.items():
        require("/" not in name and (name == "yosys-abc.exe" or name.endswith(".dll")), "Invalid shared binary path")
        check_hash(evidence(name), expected)
    exe_identities, abc_locations, resources, expected_aliases = {}, {}, {}, {}
    for role in ("baseline", "candidate"):
        record = windows_manifest["roles"][role]
        files, origins = record["files"], record["file_origins"]
        require(set(files) == set(origins), "Every logical role file needs an explicit physical origin")
        for name, expected in files.items():
            actual = "yosys-"+role+".exe" if name == "yosys.exe" else name
            require(origins[name] == actual, "Unexpected physical role mapping: "+role+"/"+name)
            require(name == "yosys.exe" or name in shared or name.startswith("share/"), "Unsupported logical runtime file")
            check_hash(evidence(actual), expected)
            if name in shared:
                require(digest(expected) == digest(shared[name]), "Common binary identities differ")
            if name.startswith("share/"):
                require(name not in resources or resources[name] == expected, "Common resource differs between roles")
                resources[name] = expected
        exe_identities[role] = digest(files["yosys.exe"])
        abc_locations[role] = origins["yosys-abc.exe"]
        expected_aliases[role+"/yosys.exe"] = dict(physical=origins["yosys.exe"], sha256=files["yosys.exe"])
    require(resources == windows_manifest["shared_resources"], "Shared resource inventory differs")
    recipe_names = [n for n in windows_manifest["roles"]["candidate"]["files"] if n.endswith((".abc",".script"))]
    require(len(recipe_names) == 1, "Require one fixed candidate recipe")
    recipe = recipe_names[0]
    expected_aliases["candidate/"+recipe] = dict(physical=recipe, sha256=windows_manifest["script_sha256"])
    alias_record = read_json(evidence("proof-aliases.json"))
    require(alias_record.get("schema") == "windows-logical-proof-aliases-v1" and alias_record.get("aliases") == expected_aliases,
            "Proof aliases do not match the three required logical copies")
    for logical, item in expected_aliases.items():
        check_hash(evidence(logical), item["sha256"])
        check_hash(evidence(item["physical"]), item["sha256"])
    return exe_identities, abc_locations, layout


def preflight(args):
    require(os.name == "posix", "Run inside WSL/Linux; this is not a Windows measurement command")
    require(args.strategy_timeout > 0, "--strategy-timeout must be positive")
    kit, bundle, manifest_path = (safe_path(p) for p in (args.kit, args.bundle, args.manifest))
    require(kit.is_dir() and bundle.is_dir(), "--kit and --bundle must be existing directories")
    require(not kit.is_relative_to(bundle) and not bundle.is_relative_to(kit), "Kit and evidence must be separate")
    require(manifest_path.is_file() and manifest_path.is_relative_to(kit), "Proof manifest must be inside the frozen kit")
    require(not os.path.lexists(os.path.expanduser(args.output)), "Output already exists; refusing to reuse it")
    output = safe_path(args.output, must_exist=False)
    require(not output.exists(), "Output already exists")
    for root in (kit, bundle):
        require(not output.is_relative_to(root) and not root.is_relative_to(output), "Output must be separate from kit and inputs")

    index_path = inside(kit, "portable-index.json")
    require(digest(args.kit_index_sha256) == FROZEN_INDEX_SHA256, "This entry supports the existing frozen EQY kit only")
    check_hash(index_path, args.kit_index_sha256)
    check_hash(manifest_path, args.manifest_sha256)
    index = read_json(index_path)
    require(isinstance(index.get("files"), dict) and index["files"], "Empty kit index")
    kit_pins = {str(index_path): digest(args.kit_index_sha256), str(manifest_path): digest(args.manifest_sha256)}
    for name, expected in index["files"].items():
        path = inside(kit, name)
        kit_pins[str(path)] = check_hash(path, expected)
    helper = inside(kit, "scripts/verify_windows_current.py")
    core = inside(kit, "scripts/verify_current_cases.py")
    check_hash(helper, FROZEN_HELPER_SHA256)
    check_hash(core, FROZEN_CORE_SHA256)
    python = inside(kit, "runtime/bin/python3")
    require(os.access(python, os.X_OK), "Kit Python wrapper is not executable")
    manifest = read_json(manifest_path)
    require(manifest.get("yosys_release") == "0.69" and manifest.get("portable_index_sha256") == args.kit_index_sha256.lower(),
            "Proof manifest version/index mismatch")
    require(manifest.get("candidate_role") == "baseline_parser_alias_for_actual_windows_netlists_only",
            "Require parser-only frozen proof manifest, not a Linux candidate synthesis manifest")
    require(manifest.get("baseline") == manifest.get("candidate"), "Frozen parser aliases must identify the same Linux tool")
    # Check all direct proof manifest identities without executing even -V.
    def manifest_file(value, expected):
        raw = Path(value)
        path = safe_path(raw if raw.is_absolute() else kit / raw)
        require(path.is_relative_to(kit) and str(path) in kit_pins, "Proof tool is outside frozen indexed kit: " + str(path))
        check_hash(path, expected)
    for role in ("baseline", "candidate", "abc", "abc_script"):
        manifest_file(manifest[role], manifest[role + "_sha256"])
    for name, expected in manifest["eqy"]["files"].items():
        manifest_file(name, expected)
    proof_bin = safe_path(manifest["proof_bin"])
    require(proof_bin == kit / "runtime/bin", "Unexpected proof wrapper directory")
    for name, expected in manifest["proof_wrapper_hashes"].items():
        manifest_file(proof_bin / name, expected)

    inventory_path = inside(bundle, "evidence-inventory.json")
    check_hash(inventory_path, args.inventory_sha256)
    inventory = read_json(inventory_path)
    payload = inventory.get("payload_files")
    require(isinstance(payload, dict) and payload, "Missing evidence payload inventory")
    bundle_pins = {str(inventory_path): digest(args.inventory_sha256)}
    for name, item in payload.items():
        path = inside(bundle, name)
        require(type(item.get("bytes")) is int and path.stat().st_size == item["bytes"], "Payload size mismatch: " + name)
        bundle_pins[str(path)] = check_hash(path, item["sha256"])

    def evidence(name):
        require(name in payload, "Required input missing from evidence inventory: " + name)
        return inside(bundle, name)
    report_path = evidence("report.json")
    check_hash(report_path, args.windows_report_sha256)
    windows_manifest_path = evidence("manifest.json")
    cases_path = evidence("cases_current.json")
    win, windows_manifest = read_json(report_path), read_json(windows_manifest_path)
    require(win.get("status") in MEASUREMENT_STATUSES and win.get("formal_status") == "PENDING", "Incomplete or already-modified Windows report")
    require(win.get("case_count") == 9 and len(win.get("cases", [])) == 9, "Exactly nine completed Windows measurement cases required")
    require(str(windows_manifest.get("yosys_release")) == "0.69", "Windows Yosys release must be 0.69")
    for key, name in (("manifest_sha256", "manifest.json"), ("case_manifest_sha256", "cases_current.json"),
                      ("harness_sha256", "run_current_cases.py"), ("meter_sha256", "windows_metrics.py")):
        check_hash(evidence(name), win[key])
    expected_cases = entries(read_json(inside(kit, "cases_current.json")))
    supplied_cases = entries(read_json(cases_path))
    require(supplied_cases == expected_cases, "Windows/kit registries must identify the same nine immutable RTL inputs")
    rows, netlists = {}, []
    # Unlike the core helper, require included PE/ABC bytes and verify layout.
    exe_identities, abc_locations, package_layout = check_windows_layout(bundle, windows_manifest, evidence)
    for row in win["cases"]:
        name = str(row["name"])
        require(name in supplied_cases and name not in rows, "Unexpected/duplicate measured case: " + name)
        identity = (name, str(row.get("top", name)), str(row["source_path"]), digest(row["source_sha256"]))
        require(identity == supplied_cases[name], "Measured input identity mismatch: " + name)
        check_hash(evidence(identity[2]), identity[3])
        check_hash(inside(kit, identity[2]), identity[3])
        rows[name] = row
        for role in ("baseline", "candidate"):
            item = row["roles"][role]
            require(digest(item["executable_sha256"]) == exe_identities[role], "Measured EXE identity mismatch")
            require(item.get("samples") and item.get("formal_object_status") == "EXPORTED_NOT_PROVED", "Missing measurements/proof object")
            relative = item["path"] + "/postabc.il"
            path = evidence(relative)
            check_hash(path, item["ilang_sha256"])
            netlists.append(dict(name=name, role=role, path=relative, sha256=digest(item["ilang_sha256"])))
    require(set(rows) == set(expected_cases) and len(netlists) == 18, "Incomplete proof input set")
    require(len({item["path"] for item in netlists}) == 18, "Proof objects must use 18 distinct evidence paths")
    script_files = [name for name in windows_manifest["roles"]["candidate"]["files"] if name.endswith((".abc", ".script"))]
    require(len(script_files) == 1, "Require one unified candidate ABC recipe")
    abc_script = evidence(windows_manifest["roles"]["candidate"]["file_origins"][script_files[0]])
    check_hash(abc_script, windows_manifest["roles"]["candidate"]["files"][script_files[0]])
    check_hash(abc_script, windows_manifest["script_sha256"])
    for field, relative in (
        ("source_sha256", "source/pmux_competition_v11.cc"),
        ("source_patch_sha256", "source/synth-intel-competition.patch"),
        ("script_sha256", "source/competition_abc_dch.abc")):
        check_hash(evidence(relative), windows_manifest[field])
    require(windows_manifest["source_sha256"] == "75ed360b73180441fccbe0f5f8ed3f10e1d07147842d38eb74baedc133ce47d2",
            "This entry requires the reviewed v26 packed-MUX source")
    require(abc_script.read_bytes().replace(b"\r\n", b"\n").strip() == b"&dch -f; &if -K 4 -a -C 4 -F 3 -A 1",
            "This entry requires the declared single v26 F3 recipe")
    # Linux is only the parser/prover of actual Windows netlists. Its archived
    # synthesis recipe is not executed during proof. Derive a new manifest that
    # truthfully binds the current Windows recipe; do not change any proof tool,
    # core helper, proof strategy, model, source RTL or netlist normalization.
    return dict(kit=kit, bundle=bundle, manifest=manifest_path, output=output, helper=helper, python=python,
                kit_pins=kit_pins, bundle_pins=bundle_pins, netlists=netlists, rows=rows,
                windows_exe_sha256=exe_identities, windows_abc_locations=abc_locations, windows_package_layout=package_layout,
                windows_recipe_path=abc_script, windows_recipe_sha256=sha(abc_script),
                index_files=len(index["files"]), inventory_files=len(payload))


def recheck(state):
    for path, expected in {**state["kit_pins"], **state["bundle_pins"], **state.get("copy_pins", {})}.items():
        check_hash(path, expected)


def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("bundle", "output", "kit", "manifest", "manifest-sha256", "windows-report-sha256", "inventory-sha256"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--kit-index-sha256", default=FROZEN_INDEX_SHA256)
    parser.add_argument("--strategy-timeout", type=int, default=300)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight-only", action="store_true")
    mode.add_argument("--run-proofs", action="store_true")
    args = parser.parse_args()
    state = preflight(args)
    summary = dict(status="PREFLIGHT_PASS", proof_started=False, scope="18 actual Windows netlists plus mandatory negative control",
                   kit=str(state["kit"]), manifest=str(state["manifest"]), bundle=str(state["bundle"]),
                   output=str(state["output"]), kit_index_sha256=digest(args.kit_index_sha256),
                   linux_proof_manifest_sha256=digest(args.manifest_sha256), windows_report_sha256=digest(args.windows_report_sha256),
                   inventory_sha256=digest(args.inventory_sha256), frozen_kit_payload_count=state["index_files"],
                   windows_inventory_payload_count=state["inventory_files"], windows_exe_sha256=state["windows_exe_sha256"],
                   windows_package_layout=state["windows_package_layout"], windows_abc_locations=state["windows_abc_locations"],
                   performance_retested=False, overall_submission_acceptance=False,
                   frozen_linux_proof_manifest_sha256=digest(args.manifest_sha256),
                   windows_recipe_sha256=state["windows_recipe_sha256"],
                   proof_manifest_derivation="Only current Windows recipe binding; frozen tools/strategies unchanged")
    if args.preflight_only:
        print(json.dumps(summary, indent=2, ensure_ascii=False), flush=True)
        return 0
    output = state["output"]
    output.mkdir(parents=True, exist_ok=False)
    inputs = output / "inputs"
    inputs.mkdir()
    copied = []
    for name in ("report.json", "manifest.json", "cases_current.json", "run_current_cases.py", "windows_metrics.py", "evidence-inventory.json"):
        shutil.copyfile(state["bundle"] / name, inputs / name)
        copied.append((state["bundle"] / name, inputs / name))
    shutil.copyfile(state["manifest"], inputs / "frozen-linux-proof-tool-manifest.json")
    frozen_manifest = read_json(state["manifest"])
    derived_manifest = dict(frozen_manifest)
    derived_manifest["abc_script"] = str(state["windows_recipe_path"])
    derived_manifest["abc_script_sha256"] = state["windows_recipe_sha256"]
    derived_manifest["windows_recipe_binding"] = dict(
        parent_manifest_sha256=digest(args.manifest_sha256),
        windows_report_sha256=digest(args.windows_report_sha256),
        scope="Recipe identity only; Linux parses/proves Windows objects and does not re-synthesize them")
    changed = {k for k in derived_manifest if derived_manifest.get(k) != frozen_manifest.get(k)}
    require(changed == {"abc_script", "abc_script_sha256", "windows_recipe_binding"}, "Unexpected proof manifest derivation")
    actual_manifest_path = inputs / "linux-proof-tool-manifest.json"
    save(actual_manifest_path, derived_manifest)
    actual_manifest_sha256 = sha(actual_manifest_path)
    summary.update(manifest=str(actual_manifest_path), frozen_manifest=str(state["manifest"]),
                   linux_proof_manifest_sha256=actual_manifest_sha256,
                   derived_manifest_changed_fields=sorted(changed))
    shutil.copyfile(state["kit"] / "portable-index.json", inputs / "linux-portable-index.json")
    shutil.copyfile(Path(__file__).resolve(), output / "prove_windows_native_once.py")
    copied += [(state["manifest"], inputs / "frozen-linux-proof-tool-manifest.json"),
               (state["kit"] / "portable-index.json", inputs / "linux-portable-index.json"),
               (Path(__file__).resolve(), output / "prove_windows_native_once.py")]
    state["copy_pins"] = {str(target): check_hash(target, sha(source)) for source, target in copied}
    state["copy_pins"][str(Path(__file__).resolve())] = sha(Path(__file__).resolve())
    state["copy_pins"][str(actual_manifest_path)] = actual_manifest_sha256
    save(output / "verified-inputs.json", dict(kit_files=state["kit_pins"], evidence_files=state["bundle_pins"],
         derived_files={str(actual_manifest_path): actual_manifest_sha256}, actual_windows_netlists=state["netlists"]))
    formal = output / "formal"
    command = [str(state["python"]), "-I", "-S", "-B", str(state["helper"]), "--repo", str(state["kit"]),
               "--manifest", str(actual_manifest_path), "--bundle", str(state["bundle"]), "--output", str(formal),
               "--strategy-timeout", str(args.strategy_timeout)]
    env = dict(os.environ, PATH=str(state["kit"] / "runtime/bin") + ":/usr/bin:/bin", PYTHONDONTWRITEBYTECODE="1")
    for key in ("ABC", "YOSYS_ABC", "YOSYS_DATDIR", "PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP", "LD_PRELOAD", "LD_LIBRARY_PATH"):
        env.pop(key, None)
    summary.update(status="RUNNING", proof_started=True, command=command, started_utc=datetime.now(timezone.utc).isoformat(),
                   launcher_sha256=sha(Path(__file__).resolve()), helper_sha256=sha(state["helper"]))
    receipt = output / "launch.json"
    save(receipt, summary)
    try:
        recheck(state)
        with (output / "process.log").open("xb") as log:
            code = subprocess.run(command, cwd=state["kit"], env=env, stdout=log, stderr=subprocess.STDOUT, check=False).returncode
        recheck(state)
        proof_path = formal / "report.json"
        require(proof_path.is_file(), "Proof helper produced no report")
        proof = read_json(proof_path)
        require(code == 0 and proof.get("status") == "PASS" and proof.get("formal_status") == "PASS", "Formal helper did not pass")
        require(proof.get("positive_proof_counts") == {"PASS": 18}, "Expected eighteen positive PASS proofs")
        require(proof.get("negative_control", {}).get("status") == "EXPECTED_COUNTEREXAMPLE", "Negative control did not find the expected counterexample")
        require(proof.get("windows_report_sha256") == digest(args.windows_report_sha256), "Proof is bound to a different Windows report")
        require(proof.get("linux_proof_manifest_sha256") == actual_manifest_sha256, "Derived proof manifest binding changed")
        require(proof.get("windows_unified_abc_script", {}).get("sha256") == state["windows_recipe_sha256"],
                "Proof did not bind the actual Windows F3 recipe")
        proof_rows = proof.get("cases", [])
        require(len(proof_rows) == 9 and {r["name"] for r in proof_rows} == set(state["rows"]), "Proof case identities differ")
        proof_lookup = {r["name"]: r for r in proof_rows}
        for item in state["netlists"]:
            actual = proof_lookup[item["name"]]["roles"][item["role"]]
            require(actual.get("status") == "PASS" and actual.get("ilang_sha256") == item["sha256"]
                    and actual.get("windows_executable_sha256") == state["windows_exe_sha256"][item["role"]], "Proof object binding differs")
        summary.update(status="PASS", exit_code=code, report_sha256=sha(proof_path), positive_proof_counts={"PASS": 18},
                       negative_control="EXPECTED_COUNTEREXAMPLE", source_kit_and_evidence_unchanged=True)
    except Exception as error:
        summary.update(status="ERROR", error=str(error))
        try:
            recheck(state)
            summary["source_kit_and_evidence_unchanged"] = True
        except Exception as changed:
            summary.update(source_kit_and_evidence_unchanged=False, integrity_error=str(changed))
    finally:
        summary["completed_utc"] = datetime.now(timezone.utc).isoformat()
        save(receipt, summary)
    print(json.dumps(summary, indent=2, ensure_ascii=False), flush=True)
    return 0 if summary["status"] == "PASS" else 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        print(json.dumps(dict(status="ERROR", error=str(error)), ensure_ascii=False), file=sys.stderr, flush=True)
        sys.exit(2)
