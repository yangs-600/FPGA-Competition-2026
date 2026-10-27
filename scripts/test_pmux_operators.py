#!/usr/bin/env python3
"""Focused combinational SAT and guard checks for generic PMUX operator sharing.

This is a pass-level engineering regression, not official area/performance scoring.
Inputs are constrained to defined binary values; literal gold X defaults are
explicit don't-cares. A mandatory wrong-output counterexample tests the SAT path.
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


HEADER = """module dut(
 input [3:0] s,
 input [7:0] a,b,c,d,e,f,g,q,r,t,u,
 output reg [7:0] y,
 output wire [7:0] tap
);
"""
FACTOR = re.compile(r"^PMUX_BITWISE_FACTOR op=(\S+) width=(\d+) removed=(\d+) default_x=(\d+)$", re.M)
ARITH_FACTOR = re.compile(r"^PMUX_ARITH_FACTOR op=(\S+) width=(\d+) removed=(\d+) independent=(\d+) input_muxes=(\d+) estimate_gain=(-?\d+) default_x=(\d+)$", re.M)
SUCCESS = "SAT proof finished - no model found: SUCCESS!"
COUNTEREXAMPLE = "SAT proof finished - model found: FAIL!"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source(operation="^", default_x=False, swapped=False, outside=False,
           keep_wire=False, mixed=False, mismatch_width=False, no_common=False):
    lines = [HEADER]
    for n, data in enumerate(("a", "b", "c", "d")):
        if n == 3 and mismatch_width:
            # The unused high bit is genuinely variable. No wreduce is run
            # before checking that this 9-bit producer is rejected.
            lines.append("wire [8:0] p3 = {s[3],d} ^ {s[2],q};\n")
            continue
        common = ("q", "r", "t", "u")[n] if no_common else "q"
        left, right = (common, data) if swapped and n % 2 else (data, common)
        op = "|" if mixed and n == 3 else operation
        attribute = "(* keep = 1 *) " if keep_wire and n == 0 else ""
        lines.append(f"{attribute}wire [7:0] p{n} = {left} {op} {right};\n")
    lines.append("assign tap = " + ("p0" if outside else "8'b0") + ";\n")
    last = "8'bx" if default_x else "p3[7:0]"
    lines.append("always @* begin\n case (s[1:0])\n 2'd0: y=p0;\n 2'd1: y=p1;\n 2'd2: y=p2;\n default: y=" + last + ";\n endcase\nend\nendmodule\n")
    return "".join(lines)


NESTED = HEADER + """
wire [7:0] p0=a^q,p1=b^q,p2=c^q,p3=d^q;
wire [7:0] p4=e^q,p5=f^q,p6=g^q;
reg [7:0] inner;
always @* begin
 case (s[1:0])
  2'd0: inner=p0;
  2'd1: inner=p1;
  2'd2: inner=p2;
  default: inner=p3;
 endcase
end
always @* begin
 case (s[3:2])
  2'd0: y=inner;
  2'd1: y=p4;
  2'd2: y=p5;
  default: y=p6;
 endcase
end
assign tap=8'b0;
endmodule
"""


def bitwise_fixtures():
    return [
        dict(name="xor_real_default", rtl=source(), minimum=1, maximum=1, operation="$xor"),
        dict(name="xor_swapped_operands", rtl=source(swapped=True), minimum=1, maximum=1, operation="$xor"),
        dict(name="and_real_default", rtl=source(operation="&"), minimum=1, maximum=1, operation="$and"),
        dict(name="or_real_default", rtl=source(operation="|"), minimum=1, maximum=1, operation="$or"),
        dict(name="xor_x_default", rtl=source(default_x=True), minimum=1, maximum=1, operation="$xor"),
        dict(name="and_x_default_skip", rtl=source(operation="&", default_x=True), minimum=0, maximum=0),
        dict(name="or_x_default_skip", rtl=source(operation="|", default_x=True), minimum=0, maximum=0),
        dict(name="external_user_skip", rtl=source(outside=True), minimum=0, maximum=0),
        dict(name="kept_wire_skip", rtl=source(keep_wire=True), minimum=0, maximum=0),
        dict(name="kept_operator_skip", rtl=source(), setup="setattr -set keep 1 t:$xor\n", minimum=0, maximum=0),
        dict(name="kept_pmux_skip", rtl=source(), setup="setattr -set keep 1 t:$pmux\n", minimum=0, maximum=0),
        dict(name="mixed_operations_skip", rtl=source(mixed=True), minimum=0, maximum=0),
        dict(name="producer_width_skip", rtl=source(mismatch_width=True), minimum=0, maximum=0),
        dict(name="no_common_operand_skip", rtl=source(no_common=True), minimum=0, maximum=0),
        dict(name="nested_bottom_up_xor", rtl=NESTED, minimum=2, maximum=2, operation="$xor"),
    ]


def arithmetic_source(operation="+", common="B", width=8, signed=False,
                      signed_mismatch=False, default="real", outside=False,
                      keep_wire=False, width_mismatch=False, repeated_pairs=False,
                      constant_operand=False, repeated_bits=False, equal_operands=False,
                      mixed_positions=False, direct_guard=None):
    """Create whole-word producers; no wreduce/opt_merge precedes the pass.

    Real-default four-way tests contain three equality arms and four producers.
    Full-X tests contain all four equality arms. Partial-X tests contain only
    three equality arms and must skip even when the static gain would be high.
    """
    header = HEADER.replace("[7:0]", f"[{width-1}:0]")
    if direct_guard:
        header = header.replace("output reg", "output wire")
    lines = [header]
    for n, data in enumerate(("a", "b", "c", "d")):
        a, b = ("q", data) if common == "A" else (data, "q")
        if common is None:
            a, b = ("a", "b", "c", "d")[n], ("e", "f", "g", "q")[n]
        if repeated_pairs:
            a, b = (("a", "e"), ("b", "f"))[n % 2]
        if mixed_positions and n % 2:
            a, b = b, a
        if equal_operands:
            b = a
        if constant_operand:
            b = f"{width}'d1"
        if repeated_bits:
            a = "{" + str(width) + "{a[0]}}"
        this_width = width
        if width_mismatch and n == 3:
            a, b = "{s[3]," + a + "}", "{s[2]," + b + "}"
            this_width += 1
        if signed and not (signed_mismatch and n == 3):
            a, b = "$signed(" + a + ")", "$signed(" + b + ")"
        attr = "(* keep=1 *) " if keep_wire and n == 0 else ""
        lines.append(f"{attr}wire [{this_width-1}:0] p{n} = {a} {operation} {b};\n")
    lines.append("assign tap=" + ("p0" if outside else f"{width}'b0") + ";\n")
    if direct_guard:
        # Internal-cell input deliberately tests guards ordinary Verilog case
        # statements cannot express. No assumption of one-hot selection is
        # added; the proof masks only bits undefined in the reference PMUX.
        selectors = {
            "mixed_ctrl": "{(s[1:0]==2'd2),(s[3:2]==2'd1),(s[1:0]==2'd0)}",
            "raw_select": "{(s[1:0]==2'd2),s[3],(s[1:0]==2'd0)}",
            "duplicate_code": "{(s[1:0]==2'd2),(s[1:0]==2'd0),(s[1:0]==2'd0)}",
        }
        lines.append(f"\\$pmux #(.WIDTH({width}),.S_WIDTH(3)) pm (.A(p3),.B({{p2,p1,p0}}),.S({selectors[direct_guard]}),.Y(y));\n")
    else:
        fallback = f"p3[{width-1}:0]"
        count = 3
        if default in ("full_x", "partial_x"):
            fallback = f"{width}'bx"
            count = 4 if default == "full_x" else 3
        elif default == "mixed_x":
            fallback = "{" + str(width//2) + "'bx,p3[" + str(width-width//2-1) + ":0]}"
        elif default == "nonoperator":
            fallback = "d"
        lines.append("always @* begin\n case (s[1:0])\n")
        for n in range(count):
            lines.append(f" 2'd{n}: y=p{n}[{width-1}:0];\n")
        lines.append(" default: y=" + fallback + ";\n endcase\nend\n")
    lines.append("endmodule\n")
    return "".join(lines)


def estimate_gain(width, arms, independent, input_muxes):
    # These equations intentionally match pass_arithmetic.cc's conservative
    # static guard exactly; this estimate is not an official LUT guarantee.
    arithmetic_luts = width + (width - 1)//2
    pmux_luts = width*((arms + 1)//2 + (arms//2 + 2)//3)
    return (independent-1)*arithmetic_luts - (input_muxes-1)*pmux_luts


def arithmetic_fixtures():
    result = []
    for operation, symbol in (("add", "+"), ("sub", "-")):
        for common in ("A", "B", None):
            name = operation + ("_general_pairs" if common is None else "_common_" + common)
            result.append(dict(name=name, rtl=arithmetic_source(symbol, common),
                               minimum=1, maximum=1, operation="$"+operation,
                               input_muxes=2 if common is None else 1, independent=4,
                               estimate_gain=estimate_gain(8, 3, 4, 2 if common is None else 1)))
        result.extend([
            dict(name=operation+"_signed", rtl=arithmetic_source(symbol, None, signed=True),
                 minimum=1, maximum=1, operation="$"+operation, input_muxes=2,
                 independent=4, estimate_gain=estimate_gain(8, 3, 4, 2)),
            dict(name=operation+"_full_x", rtl=arithmetic_source(symbol, None, default="full_x"),
                 minimum=1, maximum=1, operation="$"+operation, input_muxes=2,
                 independent=4, estimate_gain=estimate_gain(8, 4, 4, 2)),
            dict(name=operation+"_partial_x_skip", rtl=arithmetic_source(symbol, None, default="partial_x"),
                 minimum=0, maximum=0),
            dict(name=operation+"_mixed_x_skip", rtl=arithmetic_source(symbol, None, default="mixed_x"),
                 minimum=0, maximum=0),
            dict(name=operation+"_signed_mismatch_skip", rtl=arithmetic_source(symbol, None, signed=True, signed_mismatch=True),
                 minimum=0, maximum=0),
            dict(name=operation+"_width_mismatch_skip", rtl=arithmetic_source(symbol, None, width_mismatch=True),
                 minimum=0, maximum=0),
            dict(name=operation+"_external_user_skip", rtl=arithmetic_source(symbol, None, outside=True),
                 minimum=0, maximum=0),
            dict(name=operation+"_kept_wire_skip", rtl=arithmetic_source(symbol, None, keep_wire=True),
                 minimum=0, maximum=0),
            dict(name=operation+"_constant_operand_skip", rtl=arithmetic_source(symbol, None, constant_operand=True),
                 minimum=0, maximum=0),
            dict(name=operation+"_repeated_operand_bits_skip", rtl=arithmetic_source(symbol, None, repeated_bits=True),
                 minimum=0, maximum=0),
            dict(name=operation+"_unprofitable_pairs_skip", rtl=arithmetic_source(symbol, None, repeated_pairs=True),
                 minimum=0, maximum=0, static_guard=dict(width=8, arms=3, independent=2, input_muxes=2,
                    estimate_gain=estimate_gain(8, 3, 2, 2), threshold=4)),
        ])
    result.extend([
        dict(name="sub_mixed_operand_positions", rtl=arithmetic_source("-", "B", mixed_positions=True),
             minimum=1, maximum=1, operation="$sub", input_muxes=2, independent=4,
             estimate_gain=estimate_gain(8, 3, 4, 2)),
        dict(name="add_width4_cost_boundary", rtl=arithmetic_source("+", None, width=4),
             minimum=1, maximum=1, operation="$add", input_muxes=2, independent=4,
             estimate_gain=estimate_gain(4, 3, 4, 2)),
        dict(name="add_width3_skip", rtl=arithmetic_source("+", None, width=3), minimum=0, maximum=0),
        dict(name="add_nonoperator_default_skip", rtl=arithmetic_source("+", None, default="nonoperator"), minimum=0, maximum=0),
        dict(name="add_kept_operator_skip", rtl=arithmetic_source("+", None), setup="setattr -set keep 1 t:$add\n", minimum=0, maximum=0),
        dict(name="add_kept_pmux_skip", rtl=arithmetic_source("+", None), setup="setattr -set keep 1 t:$pmux\n", minimum=0, maximum=0),
    ])
    for guard in ("mixed_ctrl", "raw_select", "duplicate_code"):
        result.append(dict(name="add_"+guard+"_skip", rtl=arithmetic_source("+", None, direct_guard=guard),
                           minimum=0, maximum=0))
    for spec in result:
        spec["kind"] = "arithmetic"
        if "estimate_gain" in spec:
            assert spec["estimate_gain"] >= 2
        if "static_guard" in spec:
            assert spec["static_guard"]["estimate_gain"] < spec["static_guard"]["threshold"]
    return result


def quote(path):
    value = str(Path(path).resolve()).replace("\\", "/")
    if any(c in value for c in ('"', "\n", "\r")):
        raise RuntimeError("Unsupported quote/newline in a Yosys path")
    return '"' + value + '"'


def sat_tail():
    return ("design -copy-from gold -as gold dut\n"
            "design -copy-from gate -as gate dut\n"
            "miter -equiv -ignore_gold_x -flatten gold gate miter\n"
            "hierarchy -top miter\n"
            "sat -enable_undef -set-def-inputs -verify -prove trigger 0 -show-inputs -show-outputs miter\n")


def flow_for(directory, setup=""):
    return (f"read_verilog -icells {quote(directory/'source.v')}\n"
            "hierarchy -check -top dut\nproc\nopt_expr\nopt_clean\n" + setup +
            f"write_json {quote(directory/'before.json')}\n"
            "design -stash gold\n"
            "design -copy-from gold -as dut dut\n"
            "pmux_competition_opt\nopt_clean\n" +
            f"write_json {quote(directory/'after.json')}\n"
            "design -stash gate\n" + sat_tail())


def cells(path):
    net = json.loads(Path(path).read_text(encoding="utf-8"))
    return dict(Counter(cell["type"] for cell in net["modules"]["dut"].get("cells", {}).values()))


def execute(candidate, flow, logfile, env, timeout):
    with logfile.open("w", encoding="utf-8") as stream:
        try:
            run = subprocess.run([str(candidate), "-Q", "-T", "-s", str(flow)],
                                 env=env, stdout=stream, stderr=subprocess.STDOUT, timeout=timeout)
            return run.returncode, False
        except subprocess.TimeoutExpired:
            return None, True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--emit-only", action="store_true", help="Only write inspectable fixtures and flows; do not claim validation")
    parser.add_argument("--arithmetic", action="store_true", help="Include add/sub sharing and guard regressions (requires v19)")
    args = parser.parse_args()
    if not args.emit_only and not args.candidate:
        parser.error("--candidate is required unless --emit-only is used")
    if args.timeout < 1:
        parser.error("Timeout must be positive")
    prefix = Path.cwd()/"clean-v11" if (Path.cwd()/"clean-v11").is_dir() else Path.cwd()
    out = (args.output or prefix/("factor-boundaries-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + str(os.getpid()))).resolve()
    if out.exists() and any(out.iterdir()):
        raise RuntimeError("Refusing to reuse nonempty boundary evidence: " + str(out))
    out.mkdir(parents=True, exist_ok=True)
    report = dict(status="FIXTURES_ONLY_NOT_VALIDATED" if args.emit_only else "RUNNING",
                  directory=str(out), harness_sha256=sha(__file__), cases=[],
                  scope="Focused PMUX pass SAT/guard regression; no official performance or area acceptance",
                  inputs_defined=True, gold_literal_x_defaults_are_dont_cares=True)

    def save():
        (out/"report.json").write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")

    env = dict(os.environ)
    env.pop("YOSYS_DATDIR", None)
    env.pop("ABC", None)
    candidate = args.candidate.resolve() if args.candidate else None
    if candidate:
        report["candidate"] = str(candidate)
        report["candidate_sha256"] = sha(candidate)
    if not args.emit_only:
        version = subprocess.check_output([str(candidate), "-V"], env=env, text=True, timeout=30).strip()
        if not version.startswith("Yosys 0.69 ("):
            raise RuntimeError("Expected the pinned Yosys 0.69 candidate")
        report["candidate_version"] = version
    save()
    selected_fixtures = bitwise_fixtures() + (arithmetic_fixtures() if args.arithmetic else [])
    for spec in selected_fixtures:
        directory = out/spec["name"]
        directory.mkdir()
        (directory/"source.v").write_text(spec["rtl"], encoding="utf-8")
        (directory/"flow.ys").write_text(flow_for(directory, spec.get("setup", "")), encoding="utf-8")
        row = {key:value for key,value in spec.items() if key not in ("rtl", "setup")}
        row.update(source_sha256=sha(directory/"source.v"), flow_sha256=sha(directory/"flow.ys"), status="NOT_RUN")
        report["cases"].append(row)
        if not args.emit_only:
            exit_code, timed_out = execute(candidate, directory/"flow.ys", directory/"run.log", env, args.timeout)
            text = (directory/"run.log").read_text(encoding="utf-8", errors="replace")
            hits = [dict(operation=op.lstrip("\\"), width=int(width), removed=int(removed), default_x=bool(int(default_x)))
                    for op,width,removed,default_x in FACTOR.findall(text)]
            hits.extend(dict(operation=op.lstrip("\\"), width=int(width), removed=int(removed),
                             independent=int(independent), input_muxes=int(muxes), estimate_gain=int(gain),
                             default_x=bool(int(default_x)))
                        for op,width,removed,independent,muxes,gain,default_x in ARITH_FACTOR.findall(text))
            row.update(exit_code=exit_code, timed_out=timed_out, factoring_events=hits,
                       log_sha256=sha(directory/"run.log"), before=cells(directory/"before.json") if (directory/"before.json").is_file() else None,
                       after=cells(directory/"after.json") if (directory/"after.json").is_file() else None)
            shaped = bool(row["before"] and row["before"].get("$pmux", 0))
            guard = spec["minimum"] <= len(hits) <= spec["maximum"] and all(
                event["operation"] == spec.get("operation", event["operation"]) for event in hits)
            guard = guard and all(all(event.get(key) == spec[key] for key in
                ("input_muxes", "independent", "estimate_gain") if key in spec) for event in hits)
            sat = exit_code == 0 and not timed_out and SUCCESS in text
            row.update(frontend_pmux_shape_present=shaped, expected_factoring_guard_met=guard,
                       sat_status="PASS" if sat else "FAIL", status="PASS" if shaped and guard and sat else "FAIL")
            print(spec["name"], row["status"], "factors", len(hits), flush=True)
        save()

    negative = out/"negative"
    negative.mkdir()
    (negative/"gold.v").write_text(source(), encoding="utf-8")
    (negative/"bad.v").write_text(HEADER.replace("output reg", "output wire") + "assign y=8'b0; assign tap=8'b0; endmodule\n", encoding="utf-8")
    bad_flow = (f"read_verilog {quote(negative/'gold.v')}\nhierarchy -top dut\nproc\nopt_expr\nopt_clean\ndesign -stash gold\n"
                + f"read_verilog {quote(negative/'bad.v')}\nhierarchy -top dut\nproc\nopt_expr\nopt_clean\ndesign -stash gate\n"
                + sat_tail())
    (negative/"flow.ys").write_text(bad_flow, encoding="utf-8")
    report["negative_control"] = dict(status="NOT_RUN", wrong_source_sha256=sha(negative/"bad.v"), flow_sha256=sha(negative/"flow.ys"))
    if not args.emit_only:
        exit_code, timed_out = execute(candidate, negative/"flow.ys", negative/"run.log", env, args.timeout)
        text = (negative/"run.log").read_text(encoding="utf-8", errors="replace")
        negative_ok = bool(exit_code) and not timed_out and COUNTEREXAMPLE in text
        report["negative_control"].update(status="EXPECTED_COUNTEREXAMPLE" if negative_ok else "INVALID_NEGATIVE_CONTROL",
                                          exit_code=exit_code, timed_out=timed_out, log_sha256=sha(negative/"run.log"))
        if sha(candidate) != report["candidate_sha256"]:
            raise RuntimeError("Candidate changed during the boundary run")
        report["status"] = "PASS" if negative_ok and all(row["status"] == "PASS" for row in report["cases"]) else "FAIL"
    save()
    print("PMUX_FACTOR_BOUNDARIES_" + report["status"], out, flush=True)
    return 0 if report["status"] in ("PASS", "FIXTURES_ONLY_NOT_VALIDATED") else 2


if __name__ == "__main__":
    sys.exit(main())
