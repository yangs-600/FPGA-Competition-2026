"""Compact, read-only presentation of the existing nine-case report schemas."""

import math
import re
from urllib.parse import quote


def _get(value, *keys):
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _fmt(value, digits=3, signed=False, scale=1):
    if not _number(value):
        return "—"
    return format(value / scale, ("+" if signed else "") + f".{digits}f")


def _pct(value, digits=3, signed=False):
    return _fmt(value, digits, signed) + ("%" if _number(value) else "")


def _text(value, fallback="—"):
    return " ".join(str(value).split()) if value is not None and value != "" else fallback


def _cell(value):
    return _text(value).replace("|", "\\|")


def _table(headers, rows):
    return ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"] + [
        "| " + " | ".join(_cell(value) for value in row) + " |" for row in rows
    ]


def _pair(baseline, candidate, digits=None, scale=1):
    if digits is None:
        return f"{_text(baseline)} → {_text(candidate)}"
    return f"{_fmt(baseline, digits, scale=scale)} → {_fmt(candidate, digits, scale=scale)}"


def _flag(value):
    return "PASS" if value is True else "FAIL" if value is False else "未完成"


def _version(value, product):
    if isinstance(value, dict):
        if value.get("status") not in (None, "observed") or value.get("exit_code") not in (None, 0):
            return _text(value.get("status"), "未采集")
        value = value.get("stdout")
    value = _text(value, "")
    match = re.search(r"\b" + re.escape(product) + r"\s+(v?\d[\w.+-]*)", value, re.I)
    if not match:
        return "未采集"
    result = match.group(1)
    if product.lower() == "yosys" and "-dirty" in value and not result.endswith("-dirty"):
        result += "-dirty"
    return result


def _environment(metadata, formal):
    before = _get(metadata, "before") or {}
    cim = _get(before, "cim", "values") or {}
    processors = _get(cim, "cpu") or []
    processors = [cpu for cpu in processors if isinstance(cpu, dict)] if isinstance(processors, list) else []
    cpu_names = ", ".join(_text(cpu.get("name")) for cpu in processors) or "未采集"
    cpu_names = cpu_names.replace("(R)", "").replace("(TM)", "")
    cores = sum(cpu["cores"] for cpu in processors) if processors and all(_number(cpu.get("cores")) for cpu in processors) else None
    threads = sum(cpu["logical_processors"] for cpu in processors) if processors and all(_number(cpu.get("logical_processors")) for cpu in processors) else before.get("logical_processors_python")
    os_name = _text(cim.get("os_caption") or before.get("platform"), "未采集").replace("Microsoft ", "")
    if cim.get("os_build"):
        os_name += f" / {cim['os_build']}"
    hardware = f"{os_name}；{cpu_names}；{_text(cores)} 核 / {_text(threads)} 线程；内存 {_fmt(_get(before, 'memory', 'total_physical_bytes'), 2, scale=1073741824)} GiB"
    baseline = _version(_get(metadata, "versions", "baseline"), "Yosys")
    candidate = _version(_get(metadata, "versions", "candidate"), "Yosys")
    candidate_tag = _get(metadata, "declared", "candidate_version")
    synthesis = f"Yosys 原版 {baseline} → 优化版 {candidate}"
    if candidate_tag:
        short_tag = re.search(r"\bv\d+(?:\.\d+)*", str(candidate_tag), re.I)
        synthesis += f"（{short_tag.group(0) if short_tag else _text(candidate_tag).split('-')[0]}）"
    python = _text(_get(before, "python", "version"), "未采集").split()[0]
    runtime = f"综合 ABC {_version(_get(metadata, 'versions', 'abc'), 'ABC')}；测量 Python {python}"
    versions = _get(formal, "tool_metadata", "proof_engine_versions") or {}
    proof_yosys = _get(versions, "yosys") or _get(versions, "candidate") or _get(versions, "baseline")
    proof = (f"证明后端 {_text(_get(formal, 'backend'), '未运行')}；"
             f"EQY {_version(_get(versions, 'eqy'), 'EQY')}；"
             f"Yosys {_version(proof_yosys, 'Yosys')}；"
             f"SBY {_version(_get(versions, 'sby'), 'SBY')}；"
             f"Python {_version(_get(versions, 'python'), 'Python')}")
    return hardware, synthesis, runtime, proof


def _case_complete(row):
    if not isinstance(row, dict) or not row.get("name") or not isinstance(row.get("absolute_limits_pass"), bool):
        return False
    if not all(_number(row.get(key)) for key in ("logic_gain_percent", "wall_overhead_percent", "memory_overhead_percent")):
        return False
    for role in ("baseline", "candidate"):
        data = _get(row, "roles", role) or {}
        if not all(_number(data.get(key)) for key in ("lut_cells", "not_cells", "scored_logic_cells", "dff_cells")):
            return False
        if not all(_number(_get(data, "selected_summary", key)) for key in ("mean_wall_seconds", "mean_peak_working_set_bytes")):
            return False
    return True


def _validate_success(report, rows, formal, proof_rows, overall_status):
    """Reject contradictory success rather than silently changing the caller's exit code."""
    complete = len(rows) == 9 and len({row.get("name") for row in rows}) == 9 and all(_case_complete(row) for row in rows)
    status = _text(overall_status)
    if status == "PASS" or status.startswith(("MEASUREMENTS_PASS", "MEASUREMENTS_AND_FORMAL_PASS", "MEASUREMENTS_REVIEW_FORMAL_PASS")):
        if not complete or not _number(_get(report, "average_gain_percent")):
            raise ValueError("Success status contradicts incomplete measurement data")
    if status == "PASS" or status.endswith("_FORMAL_PASS"):
        if (_get(formal, "status") != "PASS" or len(proof_rows) != 9
                or len({_get(row, "name") for row in proof_rows}) != 9
                or {_get(row, "name") for row in proof_rows} != {row.get("name") for row in rows}
                or any(_get(row, role) != "PASS" for row in proof_rows for role in ("baseline", "candidate"))
                or _get(formal, "negative_control", "status") != "EXPECTED_COUNTEREXAMPLE"):
            raise ValueError("Success status contradicts incomplete or unsuccessful EQY evidence")
    return complete


def _links(report, metadata, formal, audit_status, report_prefix, evidence_prefix):
    # Prefixes are relative to the output Markdown; all run sidecars use this basename.
    directory = _text(_get(report, "directory"), "").replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    if not directory or directory in (".", "..") or ":" in directory:
        return []
    def link(label, path):
        return f"[{label}]({quote(path.replace(chr(92), '/'), safe='/._-')})"
    result = [link("测量 JSON", report_prefix + directory + "/report.json")]
    if metadata:
        result.append(link("环境与版本", evidence_prefix + directory + "-environment.json"))
    if formal:
        result.append(link("EQY 记录", evidence_prefix + directory + "-formal.json"))
    if audit_status and not any(word in str(audit_status) for word in ("未执行", "NOT_RUN", "NOT_REQUESTED", "PENDING")):
        result.append(link("独立审计", evidence_prefix + directory + "-audit.json"))
    proof_path = _get(formal, "paths", "formal_report")
    if isinstance(proof_path, str):
        proof_path = proof_path.replace("\\", "/")
        if not proof_path.startswith("/") and ":" not in proof_path and ".." not in proof_path.split("/"):
            result.append(link("证明明细", report_prefix + proof_path))
    result.append(link("综合日志", evidence_prefix + directory + "-console.log"))
    return result


def render(report, metadata, formal, overall_status, exit_code, audit_status, stamp,
           report_prefix="../../", evidence_prefix=""):
    """Return (markdown, terminal_text), without reading files or running tools.

    Inputs are the unchanged run_current_cases report, demo_metadata environment,
    and formal_dispatch result dictionaries. Missing values display as unavailable.
    overall_status/exit_code are the caller's final verdict; a claimed success with
    incomplete measurements/proofs raises ValueError. Relative prefixes locate the
    package root and per-run sidecars from the Markdown output directory.
    """
    report = report if isinstance(report, dict) else {}
    metadata = metadata if isinstance(metadata, dict) else {}
    formal = formal if isinstance(formal, dict) else {}
    rows = [row for row in (report.get("cases") or []) if isinstance(row, dict)]
    proof_rows = [row for row in (formal.get("case_rows") or []) if isinstance(row, dict)]
    complete = _validate_success(report, rows, formal, proof_rows, overall_status)
    proofs = {row.get("name"): row for row in proof_rows}
    formal_status = _text(formal.get("status"), "PENDING")
    fallback_proof = formal_status if formal_status != "PASS" else "MISSING"
    negative_status = _text(_get(formal, "negative_control", "status"), "未运行")
    hardware, synthesis, runtime, proof_version = _environment(metadata, formal)
    headline = f"状态：{_text(overall_status, 'INCOMPLETE')}；退出码：{_text(exit_code)}；完整用例：{sum(_case_complete(row) for row in rows)}/9"
    gain = _pct(report.get("average_gain_percent"), 6) if complete else "未完成"
    summary = (f"平均资源降幅：{gain}（逐例算术平均）；资源不增加：{_flag(report.get('all_logic_cells_nonincrease'))}；"
               f"时间/内存增幅 ≤5%：{_flag(report.get('all_efficiency_5pct_pass'))}；"
               f"60 秒 / 2 GB：{_flag(report.get('all_absolute_limits_pass'))}。")
    proof_count = sum(row.get(role) == "PASS" for row in proofs.values() for role in ("baseline", "candidate"))
    proof_display = f"{proof_count}/18 PASS" if formal_status == "PASS" else formal_status
    negative_display = "PASS（检出反例）" if negative_status == "EXPECTED_COUNTEREXAMPLE" else negative_status
    audit_display = "PASS" if audit_status == "INDEPENDENT_AUDIT_PASS" else _text(audit_status, "未运行")
    verification = f"EQY：{proof_display}；负对照：{negative_display}；独立审计：{audit_display}。"
    area, performance, reviewed, terminal_rows = [], [], [], []
    for row in rows:
        name = _text(row.get("name"))
        baseline, candidate = (_get(row, "roles", role) or {} for role in ("baseline", "candidate"))
        bs, cs = (_get(data, "selected_summary") or {} for data in (baseline, candidate))
        eqy = proofs.get(row.get("name"), {})
        eqy_pair = f"{_text(eqy.get('baseline'), fallback_proof)}/{_text(eqy.get('candidate'), fallback_proof)}"
        if row.get("review_triggered") is True:
            count_b, count_c = bs.get("sample_count"), cs.get("sample_count")
            adopted = f"复核 {_text(count_b if count_b == count_c else None)} 对均值"
        elif row.get("review_triggered") is False:
            adopted = "首轮"
        else:
            adopted = "未完成"
        area.append([name, _pair(baseline.get("lut_cells"), candidate.get("lut_cells")),
                     _pair(baseline.get("not_cells"), candidate.get("not_cells")),
                     _pair(baseline.get("scored_logic_cells"), candidate.get("scored_logic_cells")),
                     _pct(row.get("logic_gain_percent")), _pair(baseline.get("dff_cells"), candidate.get("dff_cells")), eqy_pair])
        performance.append([name, _pair(bs.get("mean_wall_seconds"), cs.get("mean_wall_seconds"), 6),
                            _pct(row.get("wall_overhead_percent"), signed=True),
                            _pair(bs.get("mean_peak_working_set_bytes"), cs.get("mean_peak_working_set_bytes"), 3, 1048576),
                            _pct(row.get("memory_overhead_percent"), signed=True), adopted])
        if row.get("review_triggered") is True:
            first = row.get("first_pair_overheads") or {}
            reviewed.append([name, _pct(first.get("wall_overhead_percent"), signed=True),
                             _pct(row.get("wall_overhead_percent"), signed=True),
                             _pct(first.get("memory_overhead_percent"), signed=True),
                             _pct(row.get("memory_overhead_percent"), signed=True)])
        terminal_rows.append([name, _pair(baseline.get("scored_logic_cells"), candidate.get("scored_logic_cells")).replace(" → ", "->"),
                              _pct(row.get("logic_gain_percent")), _pct(row.get("wall_overhead_percent"), signed=True),
                              _pct(row.get("memory_overhead_percent"), signed=True), adopted, eqy_pair])
    maxima = []
    for key, unit, scale in (("max_wall_seconds", "秒", 1), ("max_peak_working_set_bytes", "MiB", 1048576)):
        values = [_get(row, "roles", "candidate", "all_measured_summary", key) for row in rows]
        value = max(values) if values and all(_number(value) for value in values) else None
        maxima.append(f"{_fmt(value, 6 if scale == 1 else 3, scale=scale)} {unit}")
    absolute = "优化版全部正式样本最大值（含首轮与复核）：" + "；".join(maxima) + "。"
    scope = "耗时含 ABC 等待、不含 EQY；内存为 Yosys 根进程峰值，不含 ABC 子进程。"
    md = ["# Windows 九例测试结果", "", f"时间：{_text(stamp)}", "", headline, "", hardware, "", synthesis,
          "", runtime + "；" + proof_version, "", summary, "", verification]
    if not complete:
        md += ["", "测量未完成：仅显示已有数据。"]
    if report.get("error") or formal.get("error"):
        md += ["", "错误：" + _text(report.get("error") or formal.get("error"))]
    md += ["", "## 资源与等价验证", "", "数值均为原版 → 优化版；资源计分 = LUT + 独立 NOT；EQY 为原版/优化版分别对 RTL。", "",
           *_table(["用例", "LUT", "NOT", "计分资源", "降幅", "DFF", "EQY 原/优"], area),
           "", "## 耗时与内存", "", scope, "",
           *_table(["用例", "耗时（秒）原 → 优", "耗时增幅", "内存（MiB）原 → 优", "内存增幅", "采用数据"], performance),
           "", absolute]
    if reviewed:
        md += ["", "复核采用追加样本均值，首轮单列保留：", "",
               *_table(["用例", "首轮耗时增幅", "复核耗时增幅", "首轮内存增幅", "复核内存增幅"], reviewed)]
    links = _links(report, metadata, formal, audit_status, report_prefix, evidence_prefix)
    if links:
        md += ["", "证据：" + " · ".join(links)]
    terminal = [f"Windows 九例测试 | {_text(stamp)}", headline, hardware, synthesis, runtime, proof_version, "",
                "用例                   资源 原->优    降幅       耗时增幅    内存增幅    采用数据       EQY 原/优"]
    for name, logic, reduction, wall, memory, adopted, eqy in terminal_rows:
        terminal.append(f"{name:<23} {logic:>10} {reduction:>9} {wall:>11} {memory:>11}  {adopted:<11} {eqy}")
    terminal += ["", summary, absolute, scope, verification]
    if reviewed:
        terminal.append("复核耗时增幅（首轮 -> 复核）：" + "；".join(f"{row[0]} {row[1]} -> {row[2]}" for row in reviewed))
    if not complete:
        terminal.append("测量未完成：仅显示已有数据。")
    if report.get("error") or formal.get("error"):
        terminal.append("错误：" + _text(report.get("error") or formal.get("error")))
    return "\n".join(md) + "\n", "\n".join(terminal) + "\n"
