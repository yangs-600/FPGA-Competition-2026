#!/usr/bin/env python3
"""Focused v20 fast-guard semantics regression, not performance acceptance.

The early returns must preserve all existing conditional substitutions. Fixtures
use generic internal cells so frontend simplification cannot erase the precise
mux/pmux/decoder shapes being tested. Inputs are defined binary values; literal
gold X values are don't-cares (including multi-hot raw PMUX behavior).
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys


SUCCESS = "SAT proof finished - no model found: SUCCESS!"
COUNTEREXAMPLE = "SAT proof finished - model found: FAIL!"
SUBSTITUTIONS = re.compile(r"^PMUX_COMPETITION_OPT substituted_bits=(\d+)$", re.M)
HEAVY_EVENTS = re.compile(
    r"^PMUX_(?:OPERATOR_FACTOR|TREE_ESTIMATE|SHARED_TREE|BITWISE_FACTOR|ARITH_FACTOR)\b[^\r\n]*", re.M)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def quote(path):
    value = str(Path(path).resolve()).replace("\\", "/")
    if any(c in value for c in ('"', "\r", "\n")):
        raise ValueError("Unsupported quote/newline in a Yosys path")
    return '"' + value + '"'


def eq(width, value, name="eq", a="s", y="match"):
    return (f"\\$eq #(.A_SIGNED(0),.B_SIGNED(0),.A_WIDTH({width}),"
            f".B_WIDTH({width}),.Y_WIDTH(1)) {name} "
            f"(.A({a}),.B({width}'d{value}),.Y({y}));\n")


def mux(width=8, b="s", select="match"):
    return (f"\\$mux #(.WIDTH({width})) mx "
            f"(.A(fallback),.B({b}),.S({select}),.Y(y));\n")


def bits(value, width):
    return [str((value >> bit) & 1) for bit in range(width)]


def fixtures():
    no_mux = ("module dut(input [2:0] s,input [7:0] a,output [7:0] y,output match);\n"
              "assign y=a^{5'b0,s};\n" + eq(3, 5) + "endmodule\n")
    raw_pmux = ("module dut(input [1:0] s,input [7:0] a,b,c,output [7:0] y);\n"
                "\\$pmux #(.WIDTH(8),.S_WIDTH(2)) pm "
                "(.A(a),.B({c,b}),.S(s),.Y(y));\nendmodule\n")
    wide_pmux = ("module dut(input [7:0] s,fallback,output [7:0] y);\n"
                 "wire [1:0] match;\n"
                 "wire [7:0] reversed_s={s[0],s[1],s[2],s[3],s[4],s[5],s[6],s[7]};\n"
                 + eq(8, 0xA6, "eq0", y="match[0]")
                 + eq(8, 0x39, "eq1", y="match[1]")
                 + "\\$pmux #(.WIDTH(8),.S_WIDTH(2)) pm "
                   "(.A(fallback),.B({reversed_s,s}),.S(match),.Y(y));\nendmodule\n")
    result = [
        dict(name="no_mux_even_with_decoder", rtl=no_mux, mux=0, pmux=0,
             eq_widths=[3], substituted_bits=0),
        dict(name="raw_select_pmux_without_facts", rtl=raw_pmux, mux=0, pmux=1,
             eq_widths=[], substituted_bits=0),
        dict(name="wide8_pmux_substitution_before_empty_decode_return", rtl=wide_pmux,
             mux=0, pmux=1, eq_widths=[8, 8], substituted_bits=16,
             expected_b=bits(0xA6, 8) + bits(0x9C, 8)),
    ]
    for width, value, data, constant in (
        (1, 1, "{8{s}}", 0xFF),
        (8, 0x96, "s", 0x96),
        (3, 5, "{s,s,s[1:0]}", 0xB5),
    ):
        declaration = "input s" if width == 1 else f"input [{width-1}:0] s"
        rtl = (f"module dut({declaration},input [7:0] fallback,output [7:0] y);\n"
               "wire match;\n" + eq(width, value) + mux(b=data) + "endmodule\n")
        result.append(dict(name=f"only_mux_fact_width{width}_still_substitutes", rtl=rtl,
                           mux=1, pmux=0, eq_widths=[width], substituted_bits=8,
                           expected_b=bits(constant, 8)))
    return result


def sat_tail():
    return ("design -copy-from gold -as gold dut\n"
            "design -copy-from gate -as gate dut\n"
            "miter -equiv -ignore_gold_x -flatten gold gate miter\n"
            "hierarchy -top miter\n"
            "sat -enable_undef -set-def-inputs -verify -prove trigger 0 -show-inputs -show-outputs miter\n")


def prepare(path):
    # Do not run proc/opt_expr here: all fixtures already have internal cells,
    # and width-1 equality must survive long enough to test the facts guard.
    return f"read_verilog -icells {quote(path)}\nhierarchy -check -top dut\nopt_clean\n"


def flow_for(directory):
    return (prepare(directory / "source.v")
            + f"write_json {quote(directory/'before.json')}\n"
            + "design -stash gold\ndesign -copy-from gold -as dut dut\n"
              "pmux_competition_opt\nopt_clean\n"
            + f"write_json {quote(directory/'after.json')}\n"
            + "design -stash gate\n" + sat_tail())


def inspect(path):
    if not path.is_file():
        return None
    module = json.loads(path.read_text(encoding="utf-8"))["modules"]["dut"]
    cells = list(module.get("cells", {}).values())
    widths = []
    for cell in cells:
        if cell["type"] == "$eq":
            width = cell["parameters"]["A_WIDTH"]
            widths.append(int(width, 2) if isinstance(width, str) else width)
    return dict(by_type=dict(Counter(c["type"] for c in cells)), eq_widths=sorted(widths),
                mux_b=[c["connections"]["B"] for c in cells if c["type"] in ("$mux", "$pmux")])


def execute(candidate, flow, logfile, env, timeout):
    with logfile.open("w", encoding="utf-8") as stream:
        try:
            run = subprocess.run([str(candidate), "-Q", "-T", "-s", str(flow)],
                                 stdout=stream, stderr=subprocess.STDOUT, env=env, timeout=timeout)
            return run.returncode, False
        except subprocess.TimeoutExpired:
            return None, True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--emit-only", action="store_true", help="Write fixtures only; do not claim a test result")
    args = parser.parse_args()
    if not args.emit_only and not args.candidate:
        parser.error("--candidate is required unless --emit-only is used")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    prefix = Path.cwd() / "clean-v11" if (Path.cwd() / "clean-v11").is_dir() else Path.cwd()
    out = (args.output or prefix / ("pmux-fastpaths-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + str(os.getpid()))).resolve()
    if out.exists() and any(out.iterdir()):
        raise RuntimeError("Refusing to reuse nonempty regression evidence: " + str(out))
    out.mkdir(parents=True, exist_ok=True)
    report = dict(status="FIXTURES_ONLY_NOT_VALIDATED" if args.emit_only else "RUNNING",
                  scope="Generic v20 early-return and substitution semantics only; not area, timing, memory, official nine-case or full EQY acceptance",
                  inputs_defined=True, gold_literal_x_values_are_dont_cares=True,
                  no_frontend_proc_or_opt_expr=True, directory=str(out),
                  harness_sha256=sha(__file__), cases=[])

    def save():
        (out / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    candidate = args.candidate.resolve() if args.candidate else None
    env = dict(os.environ)
    for key in ("YOSYS_DATDIR", "ABC", "YOSYS_ABC"):
        env.pop(key, None)
    if candidate:
        report.update(candidate=str(candidate), candidate_sha256=sha(candidate))
    if not args.emit_only:
        version = subprocess.check_output([str(candidate), "-V"], text=True, env=env, timeout=30).strip()
        if not version.startswith("Yosys 0.69 ("):
            raise RuntimeError("Expected the pinned Yosys 0.69 candidate")
        report["candidate_version"] = version
    save()
    for spec in fixtures():
        directory = out / spec["name"]
        directory.mkdir()
        (directory / "source.v").write_text(spec["rtl"], encoding="utf-8")
        (directory / "flow.ys").write_text(flow_for(directory), encoding="utf-8")
        row = {k: v for k, v in spec.items() if k != "rtl"}
        row.update(status="NOT_RUN", source_sha256=sha(directory / "source.v"), flow_sha256=sha(directory / "flow.ys"))
        report["cases"].append(row)
        if not args.emit_only:
            code, timeout = execute(candidate, directory / "flow.ys", directory / "run.log", env, args.timeout)
            text = (directory / "run.log").read_text(encoding="utf-8", errors="replace")
            before, after = inspect(directory / "before.json"), inspect(directory / "after.json")
            shaped = bool(before is not None and before["by_type"].get("$mux", 0) == spec["mux"]
                          and before["by_type"].get("$pmux", 0) == spec["pmux"]
                          and before["eq_widths"] == spec["eq_widths"])
            count_ok = SUBSTITUTIONS.findall(text) == [str(spec["substituted_bits"])]
            no_heavy = not HEAVY_EVENTS.findall(text)
            data_ok = "expected_b" not in spec or bool(after and after["mux_b"] == [spec["expected_b"]])
            sat_ok = code == 0 and not timeout and SUCCESS in text
            row.update(exit_code=code, timed_out=timeout, before=before, after=after,
                       frontend_shape_pass=shaped, substitution_count_pass=count_ok,
                       no_factor_or_tree_preparation_logged=no_heavy,
                       expected_constant_data_pass=data_ok,
                       sat_status="PASS" if sat_ok else "FAIL", log_sha256=sha(directory / "run.log"),
                       status="PASS" if shaped and count_ok and no_heavy and data_ok and sat_ok else "FAIL")
            print(spec["name"], row["status"], "substitutions", SUBSTITUTIONS.findall(text), flush=True)
        save()
    negative = out / "negative"
    negative.mkdir()
    header = "module dut(input s,input [7:0] a,output [7:0] y);\n"
    (negative / "gold.v").write_text(header + "assign y=a^{8{s}};\nendmodule\n", encoding="utf-8")
    (negative / "bad.v").write_text(header + "assign y=8'b0;\nendmodule\n", encoding="utf-8")
    negative_flow = (prepare(negative / "gold.v") + "design -stash gold\n"
                     + prepare(negative / "bad.v") + "design -stash gate\n" + sat_tail())
    (negative / "flow.ys").write_text(negative_flow, encoding="utf-8")
    report["negative_control"] = dict(status="NOT_RUN", source_sha256=sha(negative / "gold.v"),
                                      wrong_source_sha256=sha(negative / "bad.v"), flow_sha256=sha(negative / "flow.ys"))
    if not args.emit_only:
        code, timeout = execute(candidate, negative / "flow.ys", negative / "run.log", env, args.timeout)
        text = (negative / "run.log").read_text(encoding="utf-8", errors="replace")
        negative_ok = code not in (None, 0) and not timeout and COUNTEREXAMPLE in text
        report["negative_control"].update(status="EXPECTED_COUNTEREXAMPLE" if negative_ok else "INVALID_NEGATIVE_CONTROL",
                                          exit_code=code, timed_out=timeout, log_sha256=sha(negative / "run.log"))
        if sha(candidate) != report["candidate_sha256"]:
            raise RuntimeError("Candidate changed during the regression")
        report["status"] = "PASS" if negative_ok and all(c["status"] == "PASS" for c in report["cases"]) else "FAIL"
    save()
    print("PMUX_FASTPATHS_" + report["status"], out, flush=True)
    return 0 if report["status"] in ("PASS", "FIXTURES_ONLY_NOT_VALIDATED") else 2


if __name__ == "__main__":
    sys.exit(main())
