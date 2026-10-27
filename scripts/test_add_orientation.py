#!/usr/bin/env python3
"""Defined-input SAT and admission-guard regressions for PMUX add orientation.

This is a pass-level regression, not official area/performance acceptance. It
uses explicit RTLIL arithmetic cells to control widths and producer guards.
One legal Verilog mixed signed/unsigned expression case additionally checks the
frontend normalization to matched unsigned parameters. The original invalid
(1,0)-signed internal add fixture remains preserved only in the v1 failure evidence.
Gold literal-X defaults are don't-cares. A mandatory wrong-output SAT control
must produce a counterexample. No synthesis mapping or timing is performed.
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
ARITH = re.compile(r"^PMUX_ARITH_FACTOR op=(\S+) width=(\d+) removed=(\d+) independent=(\d+) input_muxes=(\d+) estimate_gain=(-?\d+) default_x=(\d+)$", re.M)
ORIENT = re.compile(r"^PMUX_ADD_ORIENT values=(\d+) directions=(\d+) natural_nodes_before=(\d+) natural_nodes_after=(\d+) mask=(\d+) recursion_visits=(\d+)$", re.M)
WORDS = tuple("abcdefghijklmno")
BUDGET = 262144


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def quote(path):
    value = str(Path(path).resolve()).replace("\\", "/")
    if any(c in value for c in ('"', "\n", "\r")):
        raise RuntimeError("Unsupported quote/newline in a Yosys path")
    return '"' + value + '"'


def dag_cost(pairs, width, bits, codes, default_x):
    """Independent literal-word Shannon model, with one joint A/B memo table.

    Leaf identities include the word bit. Selector order is natural LSB-first;
    actual sparse codes and the default value are present in every column.
    This model checks the diagnostic score, not mapped LUT area.
    """
    memo = {}

    def build(column, code, depth):
        if depth == bits:
            return column[code]
        low = build(column, code, depth + 1)
        high = build(column, code | (1 << depth), depth + 1)
        if low == high:
            return low
        key = (depth, low, high)
        if key not in memo:
            memo[key] = ("node", len(memo))
        return memo[key]

    offset = 0 if default_x else 1
    for side in (0, 1):
        for bit in range(width):
            fallback = ("x",) if default_x else (pairs[0][side], bit)
            column = [fallback] * (1 << bits)
            for arm, code in enumerate(codes):
                column[code] = (pairs[offset + arm][side], bit)
            build(column, 0, 0)
    return len(memo)


def orientation_model(pairs, width, bits, codes, default_x):
    result = dict(values=len(pairs), directions=0, recursion_visits=0,
                  searched=False, natural_nodes_before=None,
                  natural_nodes_after=None, best_mask=0)
    if not 2 <= len(pairs) <= 8 or not 2 <= bits <= 6:
        return result
    directions = 1 << (len(pairs) - 1)
    visits = directions * 2 * width * ((2 << bits) - 1)
    result.update(directions=directions, recursion_visits=visits)
    if visits > BUDGET:
        return result
    before = best = dag_cost(pairs, width, bits, codes, default_x)
    best_mask = 0
    for trial in range(1, directions):
        mask = trial << 1
        swapped = [(b, a) if mask & (1 << i) else (a, b)
                   for i, (a, b) in enumerate(pairs)]
        cost = dag_cost(swapped, width, bits, codes, default_x)
        if cost < best:
            best, best_mask = cost, mask
    result.update(searched=True, natural_nodes_before=before,
                  natural_nodes_after=best, best_mask=best_mask)
    return result


def header(width, bits):
    return ("module dut(\n input [" + str(bits - 1) + ":0] s,\n input [" +
            str(width - 1) + ":0] " + ",".join(WORDS) + ",\n output wire [" +
            str(width - 1) + ":0] y,tap\n);\n")


def rtl_for(pairs, width=5, bits=2, codes=(0, 1, 2), default_x=False,
            operation="$add", signed=(0, 0), repeated=None, outside=False,
            keep_wire=False, mismatch_signed=False, mismatch_width=False,
            mixed_operation=False, partial_x=False):
    """pairs[0] is the real default, or arm zero for a literal-X default."""
    lines = [header(width, bits)]
    for i, (left, right) in enumerate(pairs):
        if repeated and i in repeated:
            lines.append(f"wire [{width-1}:0] p{i}=p{repeated[i]};\n")
            continue
        this_width = width + int(mismatch_width and i == 0)
        if this_width != width:
            left, right = "{s[0]," + left + "}", "{s[1]," + right + "}"
        sign_a, sign_b = (0, 0) if mismatch_signed and i == len(pairs) - 1 else signed
        op = "$sub" if mixed_operation and i == len(pairs) - 1 else operation
        attr = "(* keep=1 *) " if keep_wire and i == 1 else ""
        lines.append(f"{attr}wire [{this_width-1}:0] p{i};\n")
        lines.append(f"\\{op} #(.A_SIGNED({sign_a}),.B_SIGNED({sign_b}),.A_WIDTH({this_width}),.B_WIDTH({this_width}),.Y_WIDTH({this_width})) op{i} (.A({left}),.B({right}),.Y(p{i}));\n")
    offset = 0 if default_x else 1
    default = f"{width}'bx" if default_x else f"p0[{width-1}:0]"
    if partial_x:
        default = "{p0[" + str(width - 1) + ":1],1'bx}"
    data = ",".join(f"p{i+offset}[{width-1}:0]" for i in reversed(range(len(codes))))
    select = ",".join(f"(s=={bits}'d{code})" for code in reversed(codes))
    lines.append(f"\\$pmux #(.WIDTH({width}),.S_WIDTH({len(codes)})) select_word (.A({default}),.B({{{data}}}),.S({{{select}}}),.Y(y));\n")
    lines.append("assign tap=" + (f"p1[{width-1}:0]" if outside else f"{width}'b0") + ";\nendmodule\n")
    return "".join(lines)


def fixtures():
    cycle4 = [("d", "a"), ("a", "b"), ("b", "c"), ("c", "d")]
    result = []

    def add(name, pairs=cycle4, *, expected_factor=1, expected_orientation=None,
            setup="", width=5, bits=2, codes=(0, 1, 2), default_x=False, **kwargs):
        model = orientation_model(pairs, width, bits, codes, default_x)
        if expected_orientation is None:
            expected_orientation = int(expected_factor and model["searched"] and model["best_mask"] != 0)
        result.append(dict(name=name, rtl=rtl_for(pairs, width, bits, codes, default_x, **kwargs),
                           setup=setup, expected_factor=expected_factor,
                           expected_orientation=expected_orientation, expected_operation=kwargs.get("operation", "$add"),
                           width=width, bits=bits, codes=list(codes), default_x=default_x,
                           static_orientation=model))

    add("crossbar_unsigned_real_25_to_20")
    add("crossbar_signed_real_25_to_20", signed=(1, 1))
    add("crossbar_full_x_25_to_20", default_x=True, codes=(0, 1, 2, 3))
    add("sparse_real_default_actual_codes", width=8, bits=3, codes=(0, 2, 5))
    add("sparse_x_default_skip", width=8, bits=3, codes=(0, 2, 5), default_x=True,
        pairs=cycle4[:3], expected_factor=0, expected_orientation=0)
    add("partial_decode_x_default_skip", width=8, default_x=True, pairs=cycle4[:3],
        expected_factor=0, expected_orientation=0)
    add("partly_x_literal_default_skip", width=8, partial_x=True,
        expected_factor=0, expected_orientation=0)
    add("subtraction_never_commuted", operation="$sub", expected_orientation=0)
    add("mixed_signed_unsigned_expression_normalized", expected_orientation=1)
    normalized = result[-1]
    # Do not construct an illegal internal $add with A_SIGNED != B_SIGNED.
    # Legal Verilog mixed operands are normalized to matched unsigned signs.
    for i, (left, right) in enumerate(cycle4):
        internal = f"\\$add #(.A_SIGNED(0),.B_SIGNED(0),.A_WIDTH(5),.B_WIDTH(5),.Y_WIDTH(5)) op{i} (.A({left}),.B({right}),.Y(p{i}));\n"
        expression = f"assign p{i} = $signed({left}) + {right};\n"
        if normalized["rtl"].count(internal) != 1:
            raise RuntimeError("Mixed-expression fixture replacement did not match one producer")
        normalized["rtl"] = normalized["rtl"].replace(internal, expression)
    normalized["expected_frontend_add_signedness"] = [0, 0]
    add("inconsistent_producer_signedness_skip", signed=(1, 1), mismatch_signed=True,
        expected_factor=0, expected_orientation=0)
    add("repeated_default_producer", pairs=cycle4 + [cycle4[0]], width=8, bits=3,
        codes=(0, 1, 2, 4), repeated={4: 0})
    add("kept_producer_skip", setup="setattr -set keep 1 t:$add\n",
        expected_factor=0, expected_orientation=0)
    add("kept_wire_skip", keep_wire=True, expected_factor=0, expected_orientation=0)
    add("kept_pmux_skip", setup="setattr -set keep 1 t:$pmux\n",
        expected_factor=0, expected_orientation=0)
    add("kept_module_skip", setup="setattr -mod -set keep 1 dut\n",
        expected_factor=0, expected_orientation=0)
    add("outside_producer_user_skip", outside=True, expected_factor=0, expected_orientation=0)
    add("mixed_operator_skip", mixed_operation=True, expected_factor=0, expected_orientation=0)
    add("producer_width_mismatch_skip", mismatch_width=True,
        expected_factor=0, expected_orientation=0)
    add("narrow_word_original_guard_skip", width=3, expected_factor=0, expected_orientation=0)
    cycle9 = [(WORDS[i], WORDS[(i+1) % 9]) for i in range(9)]
    add("more_than_eight_values_orientation_skip", pairs=cycle9, width=8, bits=4,
        codes=tuple(range(8)), expected_orientation=0)
    cycle8 = [(WORDS[i], WORDS[(i+1) % 8]) for i in range(8)]
    sparse7 = (0, 4, 8, 16, 24, 40, 55)
    add("work_budget_292608_orientation_skip", pairs=cycle8, width=9, bits=6,
        codes=sparse7, expected_orientation=0)
    add("work_budget_260096_inside_search", pairs=cycle8, width=8, bits=6, codes=sparse7)
    common = [(word, "k") for word in "abcd"]
    add("already_common_operand_no_orientation", pairs=common, width=8, expected_orientation=0)
    model = orientation_model(cycle4, 5, 2, (0, 1, 2), False)
    best = [(b, a) if model["best_mask"] & (1 << i) else (a, b)
            for i, (a, b) in enumerate(cycle4)]
    add("already_minimal_direction_no_orientation", pairs=best, expected_orientation=0)
    for spec in result[:3]:
        if (spec["static_orientation"]["natural_nodes_before"], spec["static_orientation"]["natural_nodes_after"]) != (25, 20):
            raise RuntimeError("Independent crossbar model did not yield 25 to 20")
    inside = next(spec for spec in result if spec["name"] == "work_budget_260096_inside_search")
    if inside["static_orientation"]["recursion_visits"] != 260096 or inside["expected_orientation"] != 1:
        raise RuntimeError("Inside-budget fixture must exercise an improving search")
    return result


def sat_tail():
    return ("design -copy-from gold -as gold dut\n"
            "design -copy-from gate -as gate dut\n"
            "miter -equiv -ignore_gold_x -flatten gold gate miter\n"
            "hierarchy -top miter\n"
            "sat -enable_undef -set-def-inputs -verify -prove trigger 0 -show-inputs -show-outputs miter\n")


def flow_for(directory, setup):
    return (f"read_verilog -icells {quote(directory/'source.v')}\n"
            "hierarchy -check -top dut\nproc\nopt_expr\nopt_clean\n" + setup +
            f"write_json {quote(directory/'before.json')}\n"
            "design -stash gold\ndesign -copy-from gold -as dut dut\n"
            "pmux_competition_opt\nopt_clean\n" +
            f"write_json {quote(directory/'after.json')}\n"
            "design -stash gate\n" + sat_tail())


def cells(path):
    net = json.loads(Path(path).read_text(encoding="utf-8"))
    return dict(Counter(cell["type"] for cell in net["modules"]["dut"].get("cells", {}).values()))


def execute(candidate, flow, log, env, timeout):
    with log.open("w", encoding="utf-8") as stream:
        try:
            run = subprocess.run([str(candidate), "-Q", "-T", "-s", str(flow)], env=env,
                                 stdout=stream, stderr=subprocess.STDOUT, timeout=timeout)
            return run.returncode, False
        except subprocess.TimeoutExpired:
            return None, True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--emit-only", action="store_true", help="Write fixtures only; never claims validation")
    args = parser.parse_args()
    if not args.emit_only and not args.candidate:
        parser.error("--candidate is required unless --emit-only is selected")
    if args.timeout < 1:
        parser.error("--timeout must be positive")
    out = args.output.resolve()
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise RuntimeError("Refusing to reuse nonempty evidence: " + str(out))
    out.mkdir(parents=True, exist_ok=True)
    candidate = args.candidate.resolve() if args.candidate else None
    report = dict(status="FIXTURES_ONLY_NOT_VALIDATED" if args.emit_only else "RUNNING",
                  created_utc=datetime.now(timezone.utc).isoformat(), directory=str(out),
                  harness_sha256=sha(__file__), cases=[], inputs_defined=True,
                  gold_literal_x_defaults_are_dont_cares=True,
                  scope="PMUX add orientation SAT/guard regression; not official area or performance acceptance")
    env = dict(os.environ)
    env.pop("YOSYS_DATDIR", None)
    env.pop("ABC", None)
    if candidate:
        report.update(candidate=str(candidate), candidate_sha256=sha(candidate))
    if not args.emit_only:
        version = subprocess.check_output([str(candidate), "-V"], text=True, env=env, timeout=30).strip()
        if not version.startswith("Yosys 0.69 ("):
            raise RuntimeError("Expected Yosys 0.69 candidate")
        report["candidate_version"] = version

    def save():
        (out/"report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    save()
    selected = fixtures()
    report["fixture_count"] = len(selected)
    for spec in selected:
        directory = out/spec["name"]
        directory.mkdir()
        (directory/"source.v").write_text(spec["rtl"], encoding="utf-8")
        (directory/"flow.ys").write_text(flow_for(directory, spec["setup"]), encoding="utf-8")
        row = {key:value for key,value in spec.items() if key not in ("rtl", "setup")}
        row.update(status="NOT_RUN", source_sha256=sha(directory/"source.v"), flow_sha256=sha(directory/"flow.ys"))
        report["cases"].append(row)
        if not args.emit_only:
            exit_code, timed_out = execute(candidate, directory/"flow.ys", directory/"run.log", env, args.timeout)
            text = (directory/"run.log").read_text(encoding="utf-8", errors="replace")
            factors = [dict(operation=op.lstrip("\\"), width=int(width), removed=int(removed),
                            independent=int(independent), input_muxes=int(muxes), estimate_gain=int(gain), default_x=bool(int(x)))
                       for op,width,removed,independent,muxes,gain,x in ARITH.findall(text)]
            orientations = [dict(values=int(n), directions=int(d), natural_nodes_before=int(b),
                                 natural_nodes_after=int(a), mask=int(m), recursion_visits=int(v))
                            for n,d,b,a,m,v in ORIENT.findall(text)]
            before = cells(directory/"before.json") if (directory/"before.json").is_file() else None
            after = cells(directory/"after.json") if (directory/"after.json").is_file() else None
            shaped = bool(before and before.get("$pmux", 0) == 1)
            parameter_ok = True
            parameter_evidence = []
            if "expected_frontend_add_signedness" in spec:
                if (directory/"before.json").is_file():
                    front = json.loads((directory/"before.json").read_text(encoding="utf-8"))
                    for name, cell in sorted(front["modules"]["dut"].get("cells", {}).items()):
                        if cell["type"] != "$add":
                            continue
                        # Yosys JSON encodes integer parameters as binary strings.
                        params = {key: int(value, 2) if isinstance(value, str) else int(value)
                                  for key, value in cell["parameters"].items()
                                  if key in ("A_SIGNED", "B_SIGNED", "A_WIDTH", "B_WIDTH", "Y_WIDTH")}
                        parameter_evidence.append(dict(name=name, parameters=params))
                expected = spec["expected_frontend_add_signedness"]
                parameter_ok = len(parameter_evidence) == 4 and all(
                    [event["parameters"].get("A_SIGNED"), event["parameters"].get("B_SIGNED")] == expected
                    and all(event["parameters"].get(key) == spec["width"]
                            for key in ("A_WIDTH", "B_WIDTH", "Y_WIDTH"))
                    for event in parameter_evidence)
            factor_ok = len(factors) == spec["expected_factor"] and all(
                event["operation"] == spec["expected_operation"] and event["width"] == spec["width"] for event in factors)
            orient_ok = len(orientations) == spec["expected_orientation"]
            model = spec["static_orientation"]
            for event in orientations:
                orient_ok = orient_ok and all(event[key] == model[key] for key in
                    ("values", "directions", "natural_nodes_before", "natural_nodes_after", "recursion_visits"))
                orient_ok = orient_ok and event["mask"] != 0 and not event["mask"] & 1 and \
                    event["natural_nodes_after"] < event["natural_nodes_before"] and event["recursion_visits"] <= BUDGET
            sat = exit_code == 0 and not timed_out and SUCCESS in text
            row.update(exit_code=exit_code, timed_out=timed_out, log_sha256=sha(directory/"run.log"), before=before, after=after,
                       factoring_events=factors, orientation_events=orientations,
                       frontend_pmux_shape_present=shaped, expected_factoring_guard_met=factor_ok,
                       expected_orientation_guard_met=orient_ok, frontend_parameter_guard_met=parameter_ok,
                       frontend_add_parameters=parameter_evidence, sat_status="PASS" if sat else "FAIL",
                       status="PASS" if shaped and parameter_ok and factor_ok and orient_ok and sat else "FAIL")
            print(spec["name"], row["status"], "factor", len(factors), "orientation", len(orientations), flush=True)
        save()
    negative = out/"negative"
    negative.mkdir()
    (negative/"gold.v").write_text(selected[0]["rtl"], encoding="utf-8")
    (negative/"bad.v").write_text(header(5, 2) + "assign y=5'b0; assign tap=5'b0; endmodule\n", encoding="utf-8")
    flow = (f"read_verilog -icells {quote(negative/'gold.v')}\nhierarchy -top dut\nproc\nopt_expr\nopt_clean\ndesign -stash gold\n" +
            f"read_verilog -icells {quote(negative/'bad.v')}\nhierarchy -top dut\nproc\nopt_expr\nopt_clean\ndesign -stash gate\n" + sat_tail())
    (negative/"flow.ys").write_text(flow, encoding="utf-8")
    report["negative_control"] = dict(status="NOT_RUN", gold_source_sha256=sha(negative/"gold.v"),
                                      wrong_source_sha256=sha(negative/"bad.v"), flow_sha256=sha(negative/"flow.ys"))
    if not args.emit_only:
        exit_code, timed_out = execute(candidate, negative/"flow.ys", negative/"run.log", env, args.timeout)
        text = (negative/"run.log").read_text(encoding="utf-8", errors="replace")
        negative_ok = bool(exit_code) and not timed_out and COUNTEREXAMPLE in text
        report["negative_control"].update(status="EXPECTED_COUNTEREXAMPLE" if negative_ok else "INVALID_NEGATIVE_CONTROL",
                                          exit_code=exit_code, timed_out=timed_out, log_sha256=sha(negative/"run.log"))
        if sha(candidate) != report["candidate_sha256"]:
            raise RuntimeError("Candidate changed during boundary run")
        report["status"] = "PASS" if negative_ok and all(row["status"] == "PASS" for row in report["cases"]) else "FAIL"
    save()
    print("PMUX_ADD_ORIENTATION_" + report["status"], out, flush=True)
    return 0 if report["status"] in ("PASS", "FIXTURES_ONLY_NOT_VALIDATED") else 2


if __name__ == "__main__":
    sys.exit(main())
