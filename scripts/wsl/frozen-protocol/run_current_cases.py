"""Independent Linux/WSL measurement runner for the nine current topic-two cases.

This runner measures complete Yosys runs, not C++ compilation or EQY.  It never
marks formal verification PASS.  See README_PROTOCOL.md for the interpretation
of the October 2026 FAQ warm-up and small-case review rules.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import platform
import re
import statistics
import subprocess
import sys
import tempfile


ROLES = ("baseline", "candidate")
EXPECTED_CASES = 9
WARMUP_RUNS = 10
REVIEW_PAIRS = 5
TOP_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def relative_file(root, name):
    """Resolve a package-relative input without accepting a baked host path."""
    rel = Path(name)
    if rel.is_absolute() or rel.drive or ".." in rel.parts:
        raise ValueError("Expected a package-relative path: " + str(name))
    result = (root / rel).resolve()
    result.relative_to(root)
    if not result.is_file():
        raise FileNotFoundError(result)
    return result


def counts(path, top):
    """Count final mapped logic.  FF control semantics belong in formal checks."""
    modules = json.loads(Path(path).read_text(encoding="utf-8"))["modules"]
    if top not in modules:
        raise RuntimeError("Missing top module " + top)
    by = Counter()
    leaves = {"cycloneiv_lcell_comb", "dffeas", "$not", "$scopeinfo"}

    def visit(name, stack):
        if name in stack:
            raise RuntimeError("Recursive netlist hierarchy " + name)
        for cell in modules[name].get("cells", {}).values():
            kind = cell["type"]
            if kind not in leaves and kind in modules:
                attrs = modules[kind].get("attributes", {})
                blackbox = any(str(attrs.get(a, "0")).strip("0")
                               for a in ("blackbox", "whitebox"))
                if not blackbox:
                    visit(kind, stack + (name,))
                    continue
            by[kind] += 1

    visit(top, ())
    unmapped = sorted(k for k in by if k.startswith("$")
                      and k not in {"$not", "$scopeinfo"})
    if unmapped:
        raise RuntimeError("Unexpected unmapped cells in final netlist: " + repr(unmapped))
    return {
        "by_type": dict(sorted(by.items())),
        "lut_cells": by["cycloneiv_lcell_comb"],
        "not_cells": by["$not"],
        "scored_logic_cells": by["cycloneiv_lcell_comb"] + by["$not"],
        "dff_cells": by["dffeas"],
        "total_cells": sum(v for k, v in by.items() if k != "$scopeinfo"),
    }


def overhead(candidate, baseline):
    if baseline <= 0:
        raise RuntimeError("Nonpositive baseline measurement")
    return 100.0 * (candidate / baseline - 1.0)


def pair_overheads(pair):
    return {
        "wall_overhead_percent": overhead(pair["candidate"]["wall_seconds"],
                                          pair["baseline"]["wall_seconds"]),
        "memory_overhead_percent": overhead(pair["candidate"]["peak_working_set_bytes"],
                                            pair["baseline"]["peak_working_set_bytes"]),
    }


def summarize_samples(samples):
    return {
        "sample_count": len(samples),
        "mean_wall_seconds": statistics.mean(s["wall_seconds"] for s in samples),
        "mean_peak_working_set_bytes": statistics.mean(s["peak_working_set_bytes"] for s in samples),
        "mean_cpu_seconds": statistics.mean(s["cpu_seconds"] for s in samples),
        "mean_root_cpu_seconds": statistics.mean(s["root_cpu_seconds"] for s in samples),
        "max_wall_seconds": max(s["wall_seconds"] for s in samples),
        "max_peak_working_set_bytes": max(s["peak_working_set_bytes"] for s in samples),
    }


def load_cases(root, path):
    source = json.loads(path.read_text(encoding="utf-8-sig"))
    entries = source["cases"] if isinstance(source, dict) else source
    if len(entries) != EXPECTED_CASES:
        raise RuntimeError("Exactly nine explicit cases are required, received " + str(len(entries)))
    result = []
    names = set()
    for entry in entries:
        name = str(entry.get("name", entry.get("id", "")))
        top = str(entry.get("top", name))
        if not TOP_RE.fullmatch(name) or not TOP_RE.fullmatch(top) or name in names:
            raise ValueError("Invalid or duplicate case name/top: " + repr((name, top)))
        names.add(name)
        src = relative_file(root, entry["path"])
        if not src.as_posix().isascii():
            raise RuntimeError("This Yosys build needs ASCII input paths: " + str(src))
        digest = sha(src)
        if digest.lower() != entry["sha256"].lower():
            raise RuntimeError("Case input changed: " + name)
        if any(k in entry for k in ("abc_script", "abc_options", "synth_options")):
            raise RuntimeError("Per-case mapping options are not supported")
        result.append(dict(name=name, top=top, path=src.relative_to(root).as_posix(),
                           sha256=digest, source=src))
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--package", type=Path, default=Path(__file__).resolve().parent,
                    help="Extracted package root; all package paths resolve from here")
    ap.add_argument("--cases", default="cases_current.json", help="Package-relative nine-case manifest")
    ap.add_argument("--timeout", type=float, default=120.0, help="Whole-process safety timeout, seconds")
    args = ap.parse_args()
    if sys.platform != "linux":
        ap.error("Run this independent protocol inside Linux/WSL")
    if not math.isfinite(args.timeout) or not 60 <= args.timeout <= 3600:
        ap.error("--timeout must be a finite value between 60 and 3600 seconds")
    root = args.package.resolve()
    if not root.as_posix().isascii():
        ap.error("Use an ASCII extraction path inside the WSL Linux filesystem")
    manifest_path = relative_file(root, "manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if str(manifest.get("yosys_release")) != "0.69":
        raise RuntimeError("Expected the Yosys 0.69 package")
    for role in ROLES:
        files = manifest["roles"][role]["files"]
        for name, digest in files.items():
            file = relative_file(root, role + "/" + name)
            if sha(file).lower() != digest.lower():
                raise RuntimeError("Package fingerprint mismatch: " + role + "/" + name)
        if "yosys" not in files or "yosys-abc" not in files:
            raise RuntimeError("Missing pinned Yosys/ABC executable for " + role)
    if manifest["roles"]["baseline"]["files"]["yosys-abc"] != manifest["roles"]["candidate"]["files"]["yosys-abc"]:
        raise RuntimeError("Baseline and candidate must use the same bundled ABC binary")
    case_manifest = relative_file(root, args.cases)
    cases = load_cases(root, case_manifest)
    meter_path = relative_file(root, "linux_metrics.py")
    for name, digest in manifest["measurement_files"].items():
        if sha(relative_file(root, name)) != digest:
            raise RuntimeError("Measurement component changed: " + name)
    if "linux_metrics.py" not in manifest["measurement_files"]:
        raise RuntimeError("The imported meter must be fingerprinted")
    spec = importlib.util.spec_from_file_location("linux_metrics_current", meter_path)
    meter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(meter)
    temp = root / "tmp"
    temp.mkdir(exist_ok=True)
    env = dict(os.environ, PATH="/usr/bin:/bin", LC_ALL="C", LANG="C")
    for key in ("ABC", "YOSYS_ABC", "YOSYS_DATDIR", "PYTHONHOME", "PYTHONPATH", "LD_PRELOAD", "LD_LIBRARY_PATH"):
        env.pop(key, None)
    env["TMP"] = env["TEMP"] = env["TMPDIR"] = str(temp)
    role_env = {role: dict(env, YOSYS_DATDIR=str(root / role / "share")) for role in ROLES}
    out = root / "validation-once"
    out.mkdir()  # Never reuse or overwrite a measured run, including a failed run.
    report = dict(
        status="RUNNING", formal_status="PENDING", case_count=EXPECTED_CASES, cases=[],
        directory=out.relative_to(root).as_posix(), platform=platform.platform(),
        started_utc=datetime.now(timezone.utc).isoformat(),
        manifest_sha256=sha(manifest_path), case_manifest_sha256=sha(case_manifest),
        harness_sha256=sha(Path(__file__)), meter_sha256=sha(meter_path),
        area_metric="Arithmetic mean across all nine per-case LUT plus standalone NOT reductions",
        primary_timing="Independent WSL run: fork-before to root reap, including ptrace event handling and ABC wait",
        supplementary_timing="Linux wait4 user+system CPU including children reaped by Yosys; root CPU diagnostic only",
        memory="Same-run Linux kernel root VmHWM at PTRACE_EVENT_EXIT, KiB converted to bytes; excludes ABC; kernel accounting accuracy limits apply; compatibility key peak_working_set_bytes",
        platform_scope="WSL Linux ELF; not a native Windows exe efficiency result",
        overall_submission_acceptance=False,
        official_review_interpretation_confirmed=False,
        protocol=dict(
            faq_cells=["Sheet1!C115", "Sheet1!C130", "Sheet1!C131", "Sheet1!C132", "Sheet1!C133"],
            warmup="Ten baseline-only full runs per case immediately before the first measured pair",
            pair_order=["baseline", "candidate"],
            review_trigger="First baseline wall time <1s and candidate wall time or peak memory overhead >5%",
            review="Five additional baseline-then-candidate pairs; retain first pair separately",
            aggregation="If reviewed, ratio of the two role arithmetic means from five additional pairs; first pair excluded",
            large_case="Baseline >10s: first pair only, no review",
            middle_case="Baseline 1..10s: first pair only; FAQ does not specify a review rule",
            security_settings="Runner never changes security software or OS security settings",
        ),
        abc_script_policy="Same pinned candidate executable and installed resources for all nine cases; no per-case ABC script/options",
    )

    def save():
        text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
        (out / "report.json").write_text(text, encoding="utf-8")
        (root / "latest-current.json").write_text(text, encoding="utf-8")

    save()
    try:
        meter.self_test(out / "meter")
        report["meter_self_test"] = "PASS"
        save()
        for case in cases:
            name, top, src = case["name"], case["top"], case["source"]
            row = dict(name=name, top=top, source_path=case["path"],
                       source_sha256=case["sha256"], roles={}, warmup_samples=[], first_pair={}, review_pairs=[])
            report["cases"].append(row)
            commands = {}
            for role in ROLES:
                directory = out / name / role
                directory.mkdir(parents=True)
                flow = directory / "flow.ys"
                read_option = " -sv" if src.suffix.lower() == ".sv" else ""
                flow.write_text(
                    f'read_verilog{read_option} "{src.as_posix()}"\n'
                    f'synth_intel -family cycloneiv -top {top}\n'
                    f'write_verilog -norename -noattr "{directory.as_posix()}/netlist.v"\n'
                    f'write_json "{directory.as_posix()}/netlist.json"\n', encoding="utf-8")
                commands[role] = [str(root / role / "yosys"), "-Q", "-T", "-s", str(flow)]
                row["roles"][role] = dict(
                    path=directory.relative_to(root).as_posix(), samples=[],
                    executable_sha256=manifest["roles"][role]["files"]["yosys"], flow_sha256=sha(flow))

            def run(role, label):
                directory = out / name / role
                logfile = directory / (label + ".log")
                sample = meter.measure(commands[role], logfile, env=role_env[role], cwd=root, timeout=args.timeout)
                for key in ("wall_seconds", "cpu_seconds", "root_cpu_seconds", "peak_working_set_bytes"):
                    if not math.isfinite(sample[key]) or sample[key] < 0:
                        raise RuntimeError("Invalid meter result " + key)
                if sample["wall_seconds"] <= 0 or sample["peak_working_set_bytes"] <= 0:
                    raise RuntimeError("Unavailable complete-run measurement")
                if sample.get("exit_code") != 0:
                    raise RuntimeError("Synthesis exited nonzero: " + str(logfile))
                logtext = logfile.read_text(encoding="utf-8", errors="replace")
                if "Executing ABC9 pass" not in logtext:
                    raise RuntimeError("ABC9 was not observed in " + str(logfile))
                current_counts = counts(directory / "netlist.json", top)
                reference = row["roles"][role].get("by_type")
                if reference is not None and current_counts["by_type"] != reference:
                    raise RuntimeError("Nondeterministic final cell counts: " + name + " " + role)
                row["roles"][role].update(current_counts)
                preserved = directory / "samples" / label
                preserved.mkdir(parents=True)
                outputs = {}
                for filename in ("netlist.json", "netlist.v"):
                    payload = (directory / filename).read_bytes()
                    (preserved / filename).write_bytes(payload)
                    outputs[filename] = hashlib.sha256(payload).hexdigest()
                return dict(sample, label=label, log=logfile.relative_to(root).as_posix(),
                            log_sha256=sha(logfile), output_sha256=outputs)

            for i in range(WARMUP_RUNS):
                row["warmup_samples"].append(run("baseline", f"warmup-{i+1:02d}"))
            save()
            for role in ROLES:
                sample = run(role, "first")
                row["first_pair"][role] = sample
                row["roles"][role]["samples"].append(sample)
            row["first_pair_overheads"] = pair_overheads(row["first_pair"])
            baseline_seconds = row["first_pair"]["baseline"]["wall_seconds"]
            needs_review = baseline_seconds < 1.0 and any(
                row["first_pair_overheads"][key] > 5 for key in ("wall_overhead_percent", "memory_overhead_percent"))
            row["review_triggered"] = needs_review
            row["runtime_band"] = "under_1s" if baseline_seconds < 1 else ("over_10s" if baseline_seconds > 10 else "1_to_10s_unspecified_review")
            if needs_review:
                for i in range(REVIEW_PAIRS):
                    pair = {}
                    for role in ROLES:
                        sample = run(role, f"review-{i+1:02d}")
                        pair[role] = sample
                        row["roles"][role]["samples"].append(sample)
                    row["review_pairs"].append(pair)
                    save()
            row["selected_measurements"] = "five_additional_review_pairs_mean" if needs_review else "first_pair"
            for role in ROLES:
                selected = [pair[role] for pair in row["review_pairs"]] if needs_review else [row["first_pair"][role]]
                row["roles"][role]["selected_summary"] = summarize_samples(selected)
                row["roles"][role]["all_measured_summary"] = summarize_samples(row["roles"][role]["samples"])
            baseline, candidate = row["roles"]["baseline"], row["roles"]["candidate"]
            b, c = baseline["selected_summary"], candidate["selected_summary"]
            if baseline["scored_logic_cells"] <= 0:
                raise RuntimeError("Area percentage is undefined for zero baseline logic cells: " + name)
            row["logic_gain_percent"] = 100 * (baseline["scored_logic_cells"] - candidate["scored_logic_cells"]) / baseline["scored_logic_cells"]
            row["logic_cells_nonincrease"] = candidate["scored_logic_cells"] <= baseline["scored_logic_cells"]
            row["dff_cells_nonincrease_diagnostic"] = candidate["dff_cells"] <= baseline["dff_cells"]
            row["wall_overhead_percent"] = overhead(c["mean_wall_seconds"], b["mean_wall_seconds"])
            row["memory_overhead_percent"] = overhead(c["mean_peak_working_set_bytes"], b["mean_peak_working_set_bytes"])
            row["cpu_overhead_percent_supplementary"] = overhead(c["mean_cpu_seconds"], b["mean_cpu_seconds"]) if b["mean_cpu_seconds"] > 0 else None
            row["efficiency_5pct_pass"] = row["wall_overhead_percent"] <= 5 and row["memory_overhead_percent"] <= 5
            row["efficiency_over_15pct"] = row["wall_overhead_percent"] > 15 or row["memory_overhead_percent"] > 15
            row["efficiency_band"] = "FULL_MARKS" if row["efficiency_5pct_pass"] else ("NO_EFFICIENCY_MARKS" if row["efficiency_over_15pct"] else "PARTIAL_MARKS_REVIEW")
            all_candidate = candidate["all_measured_summary"]
            row["absolute_limits_pass"] = all_candidate["max_wall_seconds"] <= 60 and all_candidate["max_peak_working_set_bytes"] <= 2_000_000_000
            save()

            # Export proof objects only after measured runs, avoiding candidate pre-warming.
            for role in ROLES:
                directory = out / name / role
                split = directory / "postabc.ys"
                read_option = " -sv" if src.suffix.lower() == ".sv" else ""
                split.write_text(
                    f'read_verilog{read_option} "{src.as_posix()}"\n'
                    f'synth_intel -family cycloneiv -top {top} -run begin:map_cells\n'
                    f'select {top}\nwrite_rtlil -selected "{directory.as_posix()}/postabc.il"\nselect *\n'
                    f'synth_intel -family cycloneiv -top {top} -run map_cells:\n'
                    f'write_json "{directory.as_posix()}/split-final.json"\n', encoding="utf-8")
                with (directory / "postabc-synthesis.log").open("w", encoding="utf-8") as log:
                    subprocess.run([str(root / role / "yosys"), "-Q", "-T", "-s", str(split)],
                                   env=role_env[role], cwd=root, stdout=log, stderr=subprocess.STDOUT,
                                   timeout=args.timeout, check=True)
                if counts(directory / "split-final.json", top)["by_type"] != row["roles"][role]["by_type"]:
                    raise RuntimeError("Split proof-export flow changed final cells")
                ilang = (directory / "postabc.il").read_text(encoding="utf-8")
                if "cell \\cycloneiv_lcell_comb " in ilang:
                    raise RuntimeError("Formal object was exported after final LUT mapping")
                row["roles"][role]["ilang_sha256"] = sha(directory / "postabc.il")
                row["roles"][role]["postabc_flow_sha256"] = sha(split)
                row["roles"][role]["formal_object_status"] = "EXPORTED_NOT_PROVED"
            print(name, "logic", baseline["scored_logic_cells"], candidate["scored_logic_cells"],
                  "wall%", round(row["wall_overhead_percent"], 3),
                  "peak%", round(row["memory_overhead_percent"], 3),
                  "review", needs_review, flush=True)
            save()
        report["average_gain_percent"] = statistics.mean(row["logic_gain_percent"] for row in report["cases"])
        report["all_logic_cells_nonincrease"] = all(row["logic_cells_nonincrease"] for row in report["cases"])
        report["all_efficiency_5pct_pass"] = all(row["efficiency_5pct_pass"] for row in report["cases"])
        report["any_efficiency_over_15pct"] = any(row["efficiency_over_15pct"] for row in report["cases"])
        report["all_absolute_limits_pass"] = all(row["absolute_limits_pass"] for row in report["cases"])
        passed = report["average_gain_percent"] >= 20 and all(report[key] for key in (
            "all_logic_cells_nonincrease", "all_efficiency_5pct_pass", "all_absolute_limits_pass"))
        report["conditional_selected_rule_pass"] = passed
        report["status"] = "RAW_MEASUREMENTS_COMPLETE_REVIEW_AND_FORMAL_REQUIRED"
        report["overall_submission_acceptance"] = False
        report["completed_utc"] = datetime.now(timezone.utc).isoformat()
        save()
        print(report["status"], report["average_gain_percent"], out, flush=True)
        return 0 if passed else 2
    except Exception as error:
        report.update(status="FAIL", error=str(error), completed_utc=datetime.now(timezone.utc).isoformat())
        save()
        raise


if __name__ == "__main__":
    sys.exit(main())
