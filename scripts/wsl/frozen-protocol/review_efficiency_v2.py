#!/usr/bin/env python3
"""Read one frozen nine-case report and write a separate efficiency view.

No Yosys process or other program is launched. Windows and Linux/WSL reports
use the same raw sample keys, but their platform and meter scopes are retained
and never merged. This tool cannot grant official acceptance, verify EQY, or
authenticate measurements merely from self-reported hashes.
"""
import argparse
from datetime import datetime, timezone
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import sys

STATUS = 'RAW_MEASUREMENT_INTERPRETATION_REQUIRES_CONFIRMATION'
ROLES = ('baseline', 'candidate')
METRICS = ('wall_seconds', 'peak_working_set_bytes', 'cpu_seconds', 'root_cpu_seconds')
COHORTS = ('first_pair', 'five_additional_pairs', 'first_plus_first_four', 'all_measured_pairs')
CASES = (
    ('test1', 'competition_case/test1/test1.v', '2d2dba011b0e8799d0de3790b69b7f01c6eb6ac665c4321b57b0378a4972fd13'),
    ('test2', 'competition_case/test2/test2.v', 'e43c9b437071488551caf3121e227e86f4fe3190751f245beac3b7ecc3fdb146'),
    ('test3', 'competition_case/test3/test3.v', '1551b9212622ccef6019d6e77de2c43dc8c80d267957b55a42121f34a08780e9'),
    ('test4', 'competition_case/test4/test4.v', 'c0c5042928bd6bf568e2b7fb2193f2b6db9c4193ba3a5378fc50a331d43422d7'),
    ('pmux_case01_balanced', 'competition_case/pmux_cases/pmux_case01_balanced.v', '463263f4b265cbad3b634d69d316cd29e7ea0a62f91ee396dbeeecf7df5c7343'),
    ('pmux_case02_pipeline', 'competition_case/pmux_cases/pmux_case02_pipeline.v', '8639081b2fb7c446edef52a514d63b49333e444ce21638f03bdee97dc954e0ea'),
    ('pmux_case03_crossbar', 'competition_case/pmux_cases/pmux_case03_crossbar.v', 'bf1fc3bf6383beb007a69587d77a29ea74fb1fbdf7429fb401c0855a31c05932'),
    ('pmux_case04_feedback', 'competition_case/pmux_cases/pmux_case04_feedback.v', 'd668d258d804674dd1412538e7bce04d4630d02928ffe113413b536e6b9ed70f'),
    ('pmux_case05_nested', 'competition_case/pmux_cases/pmux_case05_nested.v', '57d64edd3704d9d74407145080a63d06390e4a598c419a948fdea22fb1147f1d'),
)
COMPLETE_STATUSES = {'MEASUREMENTS_PASS_FORMAL_PENDING', 'MEASUREMENTS_REVIEW_FORMAL_PENDING',
                     'RAW_MEASUREMENTS_COMPLETE_REVIEW_AND_FORMAL_REQUIRED'}
HASH = re.compile(r'^[0-9a-fA-F]{64}$')
WSL_LINUX_SCOPE = 'WSL Linux ELF; not a native Windows exe efficiency result'


class InvalidReport(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise InvalidReport(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'Duplicate JSON object key: '+key)
        result[key] = value
    return result


def load_bytes(data):
    def invalid_constant(value):
        raise InvalidReport('Non-finite JSON constant: '+value)
    try:
        result = json.loads(data.decode('utf-8-sig'), object_pairs_hook=unique_object,
                            parse_constant=invalid_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise InvalidReport('Invalid UTF-8 JSON: '+str(error)) from error
    def walk(value, location):
        if isinstance(value, float):
            require(math.isfinite(value), 'Non-finite value at '+location)
        elif isinstance(value, dict):
            for key, child in value.items():
                walk(child, location+'.'+key)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f'{location}[{index}]')
    walk(result, 'report')
    require(isinstance(result, dict), 'Report must be a JSON object')
    return result


def path_token(value, location):
    require(isinstance(value, str) and value and '\\' not in value and ':' not in value,
            'Expected relative POSIX path at '+location)
    path = PurePosixPath(value)
    require(not path.is_absolute() and '..' not in path.parts and str(path) == value,
            'Noncanonical or escaping relative path at '+location)
    return value


def hash_token(value, location):
    require(isinstance(value, str) and HASH.fullmatch(value) is not None, 'Invalid SHA-256 at '+location)
    return value.lower()


def metric_number(value, key, location):
    require(type(value) in (int, float), 'Expected numeric '+location+'.'+key)
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    require(finite and value >= 0, 'Invalid finite nonnegative '+location+'.'+key)
    if key in ('wall_seconds', 'peak_working_set_bytes'):
        require(value > 0, 'Unavailable/zero '+location+'.'+key)
    if key == 'peak_working_set_bytes':
        require(type(value) is int, 'Peak memory must be an integer byte count at '+location)


def ratio(candidate, baseline):
    if baseline == 0:
        return None
    result = float(100 * (candidate / baseline - 1))
    require(math.isfinite(result), 'Computed overhead is non-finite')
    return result


def cohort(pairs, required=None):
    if not pairs or (required is not None and len(pairs) != required):
        return dict(available=False, pair_count=len(pairs), required_pair_count=required,
                    reason='Not measured at the required sample count; no extrapolation', metrics=None,
                    wall_root_memory_within_5pct=None, wall_root_memory_above_15pct=None)
    values, exact_changes = {}, {}
    for key in METRICS:
        # Use the decimal sample values represented in JSON, with no added
        # measurement tolerance. This avoids turning exactly 5% into a fail
        # merely because a floating division prints 5.000000000000004.
        means = {role: sum((Fraction(str(pair[role][key])) for pair in pairs), Fraction()) / len(pairs)
                 for role in ROLES}
        change = ratio(means['candidate'], means['baseline'])
        exact_changes[key] = None if means['baseline'] == 0 else 100*(means['candidate']/means['baseline']-1)
        values[key] = dict(baseline_mean=float(means['baseline']), candidate_mean=float(means['candidate']),
                           overhead_percent=change,
                           ratio_status='DEFINED' if change is not None else 'UNDEFINED_ZERO_BASELINE')
    changes = [exact_changes[key] for key in ('wall_seconds', 'peak_working_set_bytes')]
    return dict(available=True, pair_count=len(pairs), required_pair_count=required, metrics=values,
                wall_root_memory_within_5pct=all(value <= 5 for value in changes),
                wall_root_memory_above_15pct=any(value > 15 for value in changes))


def validate(raw):
    require(raw.get('status') in COMPLETE_STATUSES, 'Not a supported completed raw measurement report')
    require(type(raw.get('case_count')) is int and raw['case_count'] == 9, 'Expected case_count=9')
    require(isinstance(raw.get('cases'), list) and len(raw['cases']) == 9, 'Expected exactly nine case entries')
    require([case.get('name') for case in raw['cases'] if isinstance(case, dict)] == [item[0] for item in CASES],
            'Nine case names/order must match the frozen registry')
    require(raw.get('meter_self_test') == 'PASS', 'Missing successful meter self-test record')
    for key in ('platform', 'primary_timing', 'supplementary_timing', 'memory', 'completed_utc'):
        require(isinstance(raw.get(key), str) and raw[key].strip(), 'Missing scope/completion metadata: '+key)
    linux_meter = raw.get('platform_scope') == WSL_LINUX_SCOPE
    if linux_meter:
        require(raw['platform'].startswith('Linux-') and 'VmHWM' in raw['memory']
                and 'PTRACE_EVENT_EXIT' in raw['memory'],
                'Linux process validation requires explicit Linux/ptrace/VmHWM scope')
    for key in ('manifest_sha256', 'case_manifest_sha256', 'harness_sha256', 'meter_sha256'):
        hash_token(raw.get(key), key)
    directory = path_token(raw.get('directory'), 'directory')
    protocol = raw.get('protocol')
    require(isinstance(protocol, dict) and protocol.get('pair_order') == list(ROLES),
            'Expected declared baseline-then-candidate pair order')
    seen_logs, executables = set(), {role: set() for role in ROLES}
    samples_checked = 0
    validated = []

    def sample(value, label, role_path, location):
        nonlocal samples_checked
        require(isinstance(value, dict), 'Missing sample object at '+location)
        require(value.get('label') == label, 'Unexpected/duplicate sample label at '+location)
        log = path_token(value.get('log'), location+'.log')
        require(log == role_path+'/'+label+'.log', 'Sample log does not bind its case/role/label at '+location)
        require(log not in seen_logs, 'Duplicate canonical sample identity: '+log)
        seen_logs.add(log)
        require(type(value.get('exit_code')) is int and value['exit_code'] == 0, 'Failed/incomplete process at '+location)
        for key in METRICS:
            metric_number(value.get(key), key, location)
        for key in ('active_job_processes', 'limit_terminated_processes'):
            if key in value:
                require(type(value[key]) is int and value[key] == 0, 'Unfinished/terminated process set at '+location)
        if 'final_memory_counter_read' in value:
            require(value['final_memory_counter_read'] is True, 'Missing final memory counter at '+location)
        if linux_meter:
            # Linux has no Windows Job process count. Validate the actual
            # exec/exit stops, root reap and owned-group completion instead.
            require(value.get('meter_status') == 'PASS', 'Linux meter did not pass at '+location)
            for key in ('exec_stop_seen', 'exit_stop_seen', 'final_reaped',
                        'process_group_empty', 'final_memory_counter_read'):
                require(value.get(key) is True, 'Incomplete Linux lifecycle '+key+' at '+location)
            for key in ('meter_exit_code', 'active_job_processes', 'limit_terminated_processes'):
                require(type(value.get(key)) is int and value[key] == 0,
                        'Failed/incomplete Linux meter '+key+' at '+location)
            require('total_job_processes' in value and value['total_job_processes'] is None,
                    'Linux Windows-Job compatibility count must be explicitly unavailable at '+location)
            require(type(value.get('memory_counter_reads')) is int and value['memory_counter_reads'] > 0,
                    'Missing Linux root-memory read at '+location)
        for key in ('memory_counter_reads', 'total_job_processes'):
            if key in value:
                if linux_meter and key == 'total_job_processes' and value[key] is None:
                    continue
                require(type(value[key]) is int and value[key] > 0, 'Invalid process/memory count at '+location)
        if 'log_sha256' in value:
            hash_token(value['log_sha256'], location+'.log_sha256')
        if 'output_sha256' in value:
            require(isinstance(value['output_sha256'], dict) and set(value['output_sha256']) == {'netlist.json', 'netlist.v'},
                    'Invalid preserved-output hash binding at '+location)
            for key, digest in value['output_sha256'].items():
                hash_token(digest, location+'.output_sha256.'+key)
        samples_checked += 1

    for case, (name, source, digest) in zip(raw['cases'], CASES):
        require(case.get('top') == name and case.get('source_path') == source and case.get('source_sha256') == digest,
                'Frozen case identity mismatch: '+name)
        roles = case.get('roles')
        require(isinstance(roles, dict) and set(roles) == set(ROLES), 'Missing/unexpected roles: '+name)
        for role in ROLES:
            info = roles[role]
            require(isinstance(info, dict), 'Invalid role information: '+name+'/'+role)
            expected_path = directory+'/'+name+'/'+role
            require(info.get('path') == expected_path, 'Role path mismatch: '+name+'/'+role)
            executables[role].add(hash_token(info.get('executable_sha256'), name+'/'+role+'/executable_sha256'))
            hash_token(info.get('flow_sha256'), name+'/'+role+'/flow_sha256')
        warmup = case.get('warmup_samples')
        require(isinstance(warmup, list) and len(warmup) == 10, 'Expected ten baseline warmups: '+name)
        for index, value in enumerate(warmup, 1):
            sample(value, f'warmup-{index:02d}', roles['baseline']['path'], name+'/warmup')
        first = case.get('first_pair')
        require(isinstance(first, dict) and set(first) == set(ROLES), 'Incomplete first pair: '+name)
        for role in ROLES:
            sample(first[role], 'first', roles[role]['path'], name+'/'+role+'/first')
        first_view = cohort([first])
        trigger = first['baseline']['wall_seconds'] < 1 and not first_view['wall_root_memory_within_5pct']
        require(type(case.get('review_triggered')) is bool and case['review_triggered'] == trigger,
                'Review trigger does not match declared baseline-under-1s implementation: '+name)
        reviews = case.get('review_pairs')
        require(isinstance(reviews, list) and len(reviews) == (5 if trigger else 0),
                'Missing/extra review pairs under implemented rule: '+name)
        for index, pair in enumerate(reviews, 1):
            require(isinstance(pair, dict) and set(pair) == set(ROLES), 'Incomplete review pair: '+name)
            for role in ROLES:
                sample(pair[role], f'review-{index:02d}', roles[role]['path'], name+'/'+role+'/review')
        for role in ROLES:
            expected = [first[role]]+[pair[role] for pair in reviews]
            require(roles[role].get('samples') == expected,
                    'Role sample mirror missing, repeated, reordered, or altered: '+name+'/'+role)
        selected_name = 'five_additional_review_pairs_mean' if trigger else 'first_pair'
        require(case.get('selected_measurements') == selected_name, 'Selected cohort label mismatch: '+name)
        validated.append((case, first, reviews))
    for role in ROLES:
        require(len(executables[role]) == 1, 'Executable identity changed between cases for '+role)
    return validated, samples_checked, {role: next(iter(values)) for role, values in executables.items()}


def build_view(raw, source_hash, source_path=None):
    validated, sample_count, executables = validate(raw)
    views = []
    for case, first, reviews in validated:
        cohorts = dict(first_pair=cohort([first], 1),
                       five_additional_pairs=cohort(reviews, 5),
                       first_plus_first_four=cohort([first]+reviews[:4], 5),
                       all_measured_pairs=cohort([first]+reviews))
        selected = 'five_additional_pairs' if reviews else 'first_pair'
        views.append(dict(name=case['name'], top=case['top'], source_sha256=case['source_sha256'],
            cohorts=cohorts, conditional_selected_cohort=selected,
            conditional_selected_wall_root_memory_within_5pct=cohorts[selected]['wall_root_memory_within_5pct'],
            short_case_qualification=dict(baseline_first_seconds=first['baseline']['wall_seconds'],
                candidate_first_seconds=first['candidate']['wall_seconds'],
                sum_first_seconds=first['baseline']['wall_seconds']+first['candidate']['wall_seconds'],
                implemented_baseline_under_1s=first['baseline']['wall_seconds'] < 1,
                both_roles_under_1s=all(first[role]['wall_seconds'] < 1 for role in ROLES),
                review_performed=bool(reviews))))
    summaries = {}
    for cohort_name in COHORTS:
        available = [(c['name'], c['cohorts'][cohort_name]) for c in views if c['cohorts'][cohort_name]['available']]
        summaries[cohort_name] = dict(available_case_count=len(available),
            unavailable_cases=[c['name'] for c in views if not c['cohorts'][cohort_name]['available']],
            above_5pct_wall_or_root_memory=[name for name, c in available if not c['wall_root_memory_within_5pct']],
            above_15pct_wall_or_root_memory=[name for name, c in available if c['wall_root_memory_above_15pct']])
    candidate_samples = [pair['candidate'] for _, first, reviews in validated for pair in [first]+reviews]
    return dict(schema=1, tool_revision=2, status=STATUS, created_utc=datetime.now(timezone.utc).isoformat(),
        raw_report_path=source_path, raw_report_sha256=source_hash, raw_report_status=raw['status'],
        raw_formal_status=raw.get('formal_status'), tool_sha256=sha(Path(__file__).read_bytes()),
        integrity=dict(status='STRUCTURALLY_VALID', fixed_case_identities=9, canonical_samples_checked=sample_count,
            role_sample_mirrors_identical=True, duplicate_log_identities=False, executable_sha256=executables,
            process_completion_validation=('Linux exec/exit stops, root reaped and owned process group empty; Windows Job count unavailable'
                if raw.get('platform_scope') == WSL_LINUX_SCOPE else 'Original Windows-compatible process counter checks'),
            limitation='Checks embedded identities and internal consistency only; no external logs, binaries, netlists or signatures are authenticated.'),
        source_scope={key: raw.get(key) for key in ('platform', 'platform_scope', 'primary_timing', 'supplementary_timing',
                      'memory', 'manifest_sha256', 'case_manifest_sha256', 'harness_sha256', 'meter_sha256')},
        formula='100 * (arithmetic_mean(candidate_samples) / arithmetic_mean(baseline_samples) - 1); not mean of pairwise percentages. Thresholds use exact rational arithmetic on decimal sample values, with no tolerance added.',
        scoring_scope='Numeric wall-time and root-process peak-memory comparisons only; CPU metrics remain separate diagnostics, root CPU never adds a scoring gate; no process-tree-memory gate.',
        official_review_interpretation_confirmed=False, overall_submission_acceptance=False,
        formal_equivalence_verified_by_this_tool=False,
        summary=dict(status=STATUS,
            strict_first_wall_root_memory_within_5pct=not summaries['first_pair']['above_5pct_wall_or_root_memory'],
            strict_first_any_above_15pct=bool(summaries['first_pair']['above_15pct_wall_or_root_memory']),
            conditional_selected_wall_root_memory_within_5pct=all(c['conditional_selected_wall_root_memory_within_5pct'] for c in views),
            conditional_rule='IF baseline-first-under-1s qualifies and five ADDITIONAL pairs exclude first; otherwise first pair. This is the implemented interpretation, not an official ruling.',
            review_qualification_ambiguous_cases=[c['name'] for c in views if c['short_case_qualification']['review_performed'] and not c['short_case_qualification']['both_roles_under_1s']],
            official_acceptance_claim=False),
        absolute_observations=dict(candidate_sample_count=len(candidate_samples),
            max_wall_seconds=max(s['wall_seconds'] for s in candidate_samples),
            max_root_peak_bytes=max(s['peak_working_set_bytes'] for s in candidate_samples),
            within_60s_and_2e9_root_bytes=all(s['wall_seconds'] <= 60 and s['peak_working_set_bytes'] <= 2_000_000_000 for s in candidate_samples),
            scope='Only retained candidate samples and declared root-process memory measure; not all possible <=1000-cell designs.'),
        unresolved_interpretations=['Whether <1s refers to baseline, candidate or combined time.',
            'Whether five review measurements include the first run.',
            'Final official CPU-versus-wall timing rule and any approved symmetric warmup/dependency layout.'],
        cohort_summaries=summaries, cases=views)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True, help='Existing complete raw JSON report; never modified')
    parser.add_argument('--output', type=Path, required=True, help='New JSON view path; existing files are never overwritten')
    args = parser.parse_args(argv)
    source, destination = args.report.resolve(), args.output.resolve()
    try:
        require(source != destination, 'Input and output must be different paths')
        require(not destination.exists(), 'Output already exists; refusing overwrite')
        require(destination.parent.is_dir(), 'Output parent directory must already exist')
        data = source.read_bytes()
        view = build_view(load_bytes(data), sha(data), str(source))
        require(source.read_bytes() == data, 'Raw report changed during the review')
        payload = json.dumps(view, ensure_ascii=False, indent=2, allow_nan=False)+'\n'
        with destination.open('x', encoding='utf-8', newline='\n') as stream:
            stream.write(payload)
    except (OSError, InvalidReport, TypeError, KeyError, OverflowError) as error:
        print('INVALID_OR_UNWRITABLE_REPORT: '+str(error), file=sys.stderr)
        return 2
    print(json.dumps(dict(status=STATUS, output=str(destination), raw_sha256=view['raw_report_sha256'],
        strict_first_within_5pct=view['summary']['strict_first_wall_root_memory_within_5pct'],
        conditional_selected_within_5pct=view['summary']['conditional_selected_wall_root_memory_within_5pct'],
        official_acceptance_claim=False), ensure_ascii=False))
    return 0  # The view was produced; this is not an acceptance/efficiency pass exit code.


if __name__ == '__main__':
    sys.exit(main())
