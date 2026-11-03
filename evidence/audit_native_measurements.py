"""Independently audit one completed native Windows report, without execution.

The only output is a new audit JSON. No package/report file is modified and no
Yosys, ABC, proof tool, runner, or meter is imported or executed. This auditor
implements the unchanged both-roles-under-one-second protocol for the explicit
co-located v26 deployment only. It must not be applied retroactively to other
layouts or older baseline-only eligibility reports.
"""
from collections import Counter
from datetime import datetime, timezone
import argparse
import ast
import hashlib
import json
import math
from pathlib import Path, PureWindowsPath
import re
import statistics
import sys

ROLES = ('baseline', 'candidate')
METRICS = ('wall_seconds', 'peak_working_set_bytes', 'cpu_seconds', 'root_cpu_seconds')
METER_SHA256 = '2eb7ffc6564a40a09310e17be8e7b5746766ca148bbe1564d03cc533540496bf'
SHARED_FILES = {'yosys-abc.exe', 'libffi-8.dll', 'libgcc_s_seh-1.dll',
                'libstdc++-6.dll', 'libwinpthread-1.dll', 'zlib1.dll'}
LAYOUT = 'colocated_yosys_shared_runtime'
PARENT_RUNNER_SHA256 = '0db05e1a8a3fde6edd9cc421e3449afa70caa4558178d2bd3e27b7739baaced6'
APPROVED_RUNNER_SHA256 = '8edf2322f8a25f6db8d3c7ad71b7d6174e8b9ebbe055cc8a8a56e0f342ed8baa'
PARENT_MANIFEST_SHA256 = '8e9276621054adf00367875ad756bd5bc0d0741a421a35090d0c180bab5fcf57'
SOURCE_SHA256 = '75ed360b73180441fccbe0f5f8ed3f10e1d07147842d38eb74baedc133ce47d2'
SCRIPT_SHA256 = '0ad315064a884d94676997ac6094cf7e679c7b0d3ff2d09431530b76d208c86e'
PATCH_SHA256 = '9a52af4ea1ffec9b5f15ed509b014855089ce35487e94455589aa9d7e0b6a073'
ABC_RECIPE = '&dch -f; &if -K 4 -a -C 4 -F 3 -A 1'


def need(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def reject_constant(value):
    raise ValueError('Nonfinite JSON number: ' + value)


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'), parse_constant=reject_constant)


def equal(actual, expected, label):
    if isinstance(expected, dict):
        need(isinstance(actual, dict) and set(actual) == set(expected), label + ': keys differ')
        for key in expected:
            equal(actual[key], expected[key], label + '.' + key)
    elif isinstance(expected, (list, tuple)):
        need(isinstance(actual, (list, tuple)) and len(actual) == len(expected), label + ': length differs')
        for index, (left, right) in enumerate(zip(actual, expected)):
            equal(left, right, label + '[' + str(index) + ']')
    elif isinstance(expected, float):
        need(isinstance(actual, (int, float)) and not isinstance(actual, bool)
             and math.isfinite(actual) and math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-8),
             label + ': ' + repr(actual) + ' != ' + repr(expected))
    else:
        need(type(actual) is type(expected) and actual == expected,
             label + ': ' + repr(actual) + ' != ' + repr(expected))


def overhead(candidate, baseline):
    return 100.0 * (candidate / baseline - 1.0) if baseline > 0 else None


def summary(samples):
    need(bool(samples), 'Empty selected sample set')
    result = {'sample_count': len(samples)}
    result.update({'mean_' + metric: statistics.mean(sample[metric] for sample in samples)
                   for metric in METRICS})
    result.update({'max_' + metric: max(sample[metric] for sample in samples)
                   for metric in METRICS[:2]})
    return result


def cohort(pairs, required_count=None):
    if not pairs or (required_count is not None and len(pairs) != required_count):
        return {'available': False, 'pair_count': len(pairs),
                'reason': 'Not enough recorded pairs; no inferred samples or reruns'}
    metrics = {}
    for metric in METRICS:
        b = statistics.mean(pair['baseline'][metric] for pair in pairs)
        c = statistics.mean(pair['candidate'][metric] for pair in pairs)
        metrics[metric] = {'baseline_mean': b, 'candidate_mean': c,
                           'overhead_percent': overhead(c, b)}
    return {'available': True, 'pair_count': len(pairs), 'metrics': metrics}


def review_rule(first):
    b, c = (first[role]['wall_seconds'] for role in ROLES)
    eligible = b < 1.0 and c < 1.0
    first_overheads = {
        'wall_overhead_percent': overhead(c, b),
        'memory_overhead_percent': overhead(first['candidate']['peak_working_set_bytes'],
                                            first['baseline']['peak_working_set_bytes']),
    }
    trigger = eligible and any(value > 5.0 for value in first_overheads.values())
    return eligible, trigger, first_overheads


def final_counts(netlist, top):
    """Traverse hierarchy independently; repeated instances count repeatedly."""
    modules = netlist['modules']
    need(top in modules, 'Final JSON lacks top module ' + top)
    result = Counter()
    leaves = {'cycloneiv_lcell_comb', 'dffeas', '$not', '$scopeinfo'}
    pending = [(top, ())]
    while pending:
        name, ancestors = pending.pop()
        need(name not in ancestors, 'Recursive final netlist hierarchy')
        for cell in modules[name].get('cells', {}).values():
            kind = cell['type']
            module = modules.get(kind)
            if kind not in leaves and module is not None:
                attrs = module.get('attributes', {})
                opaque = any(str(attrs.get(key, '0')).strip('0') for key in ('blackbox', 'whitebox'))
                if not opaque:
                    pending.append((kind, ancestors + (name,)))
                    continue
            result[kind] += 1
    unsupported = [kind for kind in result if kind.startswith('$') and kind not in {'$not', '$scopeinfo'}]
    need(not unsupported, 'Unmapped final cells: ' + repr(unsupported))
    return {'by_type': dict(sorted(result.items())), 'lut_cells': result['cycloneiv_lcell_comb'],
            'not_cells': result['$not'], 'scored_logic_cells': result['cycloneiv_lcell_comb'] + result['$not'],
            'dff_cells': result['dffeas'], 'total_cells': sum(n for kind, n in result.items() if kind != '$scopeinfo')}


def compare_runner_sources(before, after):
    """Parse source only; neither runner is imported or executed."""
    old = ast.parse(before)
    new = ast.parse(after)
    def protected_module(tree):
        return ast.dump(ast.Module(body=[node for node in tree.body
            if not isinstance(node, ast.FunctionDef) or node.name not in {'main', 'role_file'}],
            type_ignores=[]), include_attributes=False)
    equal(protected_module(new), protected_module(old), 'Unchanged imports/constants/statistical helpers/entry point AST')
    old_functions = {node.name for node in old.body if isinstance(node, ast.FunctionDef)}
    new_functions = {node.name for node in new.body if isinstance(node, ast.FunctionDef)}
    equal(new_functions, old_functions | {'role_file'}, 'Only declared resolver function added')
    expected_resolver = ast.parse('''def role_file(root, manifest, role, name):
    """Resolve one logical role file to its declared colocated physical file."""
    description = manifest["roles"][role]
    expected = "yosys-" + role + ".exe" if name == "yosys.exe" else name
    if description["file_origins"].get(name) != expected:
        raise RuntimeError("Unexpected physical origin for " + role + "/" + name)
    return relative_file(root, expected)
''').body[0]
    resolver = next(node for node in new.body if isinstance(node, ast.FunctionDef) and node.name == 'role_file')
    equal(ast.dump(resolver, include_attributes=False), ast.dump(expected_resolver, include_attributes=False),
          'Exact physical resolver AST')
    marker = '    out = Path(tempfile.mkdtemp(prefix="validation-current-", dir=root))\n'
    need(before.count(marker) == after.count(marker) == 1, 'Missing unique measurement-section boundary')
    old_tail, new_tail = (text[text.index(marker):] for text in (before, after))
    old_expression = 'str(root / role / "yosys.exe")'
    new_expression = 'str(role_file(root, manifest, role, "yosys.exe"))'
    need(old_tail.count(old_expression) == new_tail.count(new_expression) == 2,
         'Expected two physical executable expression changes')
    equal(new_tail.replace(new_expression, old_expression), old_tail,
          'Complete measurement section after exact two path-expression reversions')
    return {'status': 'PASS_INDEPENDENT_SOURCE_AND_AST_COMPARISON',
            'parent_runner_sha256': PARENT_RUNNER_SHA256, 'new_runner_sha256': APPROVED_RUNNER_SHA256,
            'protected_measurement_section_sha256': hashlib.sha256(old_tail.encode('utf-8')).hexdigest(),
            'measurement_section_unchanged_after_two_exe_path_normalizations': True,
            'non_main_toplevel_ast_unchanged_except_declared_resolver': True,
            'warmups_reviews_thresholds_timing_memory_aggregation_unchanged': True,
            'meter_self_test_and_measure_calls_unchanged': True,
            'main_initialization_changes_reviewed_and_entire_new_runner_sha256_pinned': True}


class Audit:
    def __init__(self, package, report):
        self.root = package.resolve()
        self.report = report.resolve()
        self.fingerprints = {}
        self.seen_logs = set()
        self.manifest = None
        self.runner_change_audit = None

    def path(self, relative):
        need(isinstance(relative, str) and bool(relative), 'Empty/non-string relative path')
        win = PureWindowsPath(relative)
        need(not win.is_absolute() and not win.drive and '..' not in win.parts,
             'Unsafe package-relative path: ' + relative)
        path = self.root.joinpath(*win.parts).resolve()
        path.relative_to(self.root)
        need(path.is_file(), 'Missing package file: ' + str(path))
        return path

    def logged_file(self, token, logical, log, directory):
        """Check execution-log path semantics without depending on relocation."""
        token = token.strip().strip('"').strip("'").replace('\\', '/')
        relative = '<yosys-exe-dir>/' + logical
        alternatives = {str(self.root / logical).replace('\\', '/').casefold()}
        # A release copy may preserve an original absolute execution path. Bind
        # that path to the logged full-flow location, never just a basename.
        header = re.search(r"(?m)^-- Executing script file [`'](.+?)[`'] --$", log)
        if header:
            original_flow = header.group(1).replace('\\', '/')
            suffix = '/' + directory + '/flow.ys'
            if original_flow.casefold().endswith(suffix.casefold()):
                alternatives.add((original_flow[:-len(suffix)] + '/' + logical).casefold())
        if logical.endswith('.exe') and not token.lower().endswith('.exe'):
            token += '.exe'
        need(token == relative or token.casefold() in alternatives,
             'Logged file is not the shared physical payload: ' + token)
        return self.pin(logical)

    def pin(self, relative, expected=None):
        path = self.path(relative)
        actual = sha(path)
        if expected is not None:
            need(isinstance(expected, str) and len(expected) == 64 and actual == expected.lower(),
                 'Fingerprint mismatch: ' + relative)
        old = self.fingerprints.setdefault(str(path), actual)
        need(old == actual, 'File changed within audit: ' + relative)
        return path

    def sample(self, sample, label, role, directory):
        equal(sample['label'], label, 'sample label')
        for key in ('exit_code', 'active_job_processes', 'limit_terminated_processes'):
            equal(sample[key], 0, key)
        need(sample['final_memory_counter_read'] is True and sample['memory_counter_reads'] > 0,
             'Incomplete root peak memory observation')
        need(sample['total_job_processes'] >= 1, 'No accounted root process')
        for metric in METRICS:
            value = sample[metric]
            need(isinstance(value, (int, float)) and not isinstance(value, bool)
                 and math.isfinite(value) and value >= 0, 'Invalid sample metric ' + metric)
        need(sample['wall_seconds'] > 0 and sample['peak_working_set_bytes'] > 0, 'Zero primary metric')
        expected_log = directory + '/' + label + '.log'
        equal(sample['log'].replace('\\', '/'), expected_log, 'sample log binding')
        need(expected_log not in self.seen_logs, 'A log was reused for multiple samples: ' + expected_log)
        self.seen_logs.add(expected_log)
        log = self.pin(expected_log).read_text(encoding='utf-8', errors='replace')
        need('Executing ABC9 pass' in log, 'ABC9 is absent in ' + expected_log)
        abc_commands = re.findall(r'(?m)^Running ABC command: "([^"]+)"', log)
        need(len(abc_commands) == 1, 'Expected exactly one ABC process command in ' + expected_log)
        self.logged_file(abc_commands[0], 'yosys-abc.exe', log, directory)
        if role == 'baseline':
            need('Executing PMUX_COMPETITION_OPT' not in log, 'Custom PMUX pass in baseline')
        else:
            need('Executing PMUX_COMPETITION_OPT v26.' in log, 'Missing v26 candidate PMUX pass')
            recipes = re.findall(r'(?m)^\s*ABC:\s+\+\s+source\s+(.+?)\s*$', log)
            need(len(recipes) == 1, 'Candidate must source exactly one external F3 recipe')
            script = self.logged_file(recipes[0], 'share/intel/competition_abc_v11.abc', log, directory)
            need(sha(script) == SCRIPT_SHA256 and script.read_text(encoding='utf-8').strip() == ABC_RECIPE,
                 'Logged shared ABC recipe is not the pinned F3 script')

    def audit_runner_change(self, raw, manifest):
        equal(raw['harness_sha256'], APPROVED_RUNNER_SHA256, 'Independently reviewed shared-layout runner')
        equal(manifest['parent_runner_sha256'], PARENT_RUNNER_SHA256, 'Frozen package-relative parent runner')
        parent_runner = self.pin(manifest['parent_runner_path'], PARENT_RUNNER_SHA256)
        self.pin('deployment-records/runner-before.py', PARENT_RUNNER_SHA256)
        current_runner = self.pin('run_current_cases.py', APPROVED_RUNNER_SHA256)
        declared_records = manifest['deployment_records_sha256']
        need(isinstance(declared_records, dict) and declared_records, 'Missing deployment-record inventory')
        record_root = self.root / 'deployment-records'
        actual_records = set()
        for path in record_root.rglob('*'):
            need(not path.is_symlink() and path.resolve().is_relative_to(record_root.resolve()),
                 'Symbolic/external deployment record')
            if path.is_file():
                actual_records.add(path.relative_to(record_root).as_posix())
        equal(actual_records, set(declared_records), 'Complete deployment-record file set')
        for name, digest in declared_records.items():
            self.pin('deployment-records/' + name, digest)
        parent = read_json(self.pin('deployment-records/parent-manifest.json', PARENT_MANIFEST_SHA256))
        equal(manifest['parent_deployment_manifest_sha256'], PARENT_MANIFEST_SHA256, 'Frozen parent deployment')
        equal(parent['package_layout'], 'separate_yosys_shared_parent_abc', 'Expected parent layout')
        for field in ('source_sha256', 'source_patch_sha256', 'script_sha256', 'source_pristine_sha256',
                      'runtime_sha256', 'shared_files', 'compiler_compatibility_option', 'cases_current_sha256'):
            equal(manifest[field], parent[field], 'Unchanged deployment payload ' + field)
        for role in ROLES:
            equal(manifest['roles'][role]['files'], parent['roles'][role]['files'], 'Parent/current logical role bytes')
        before = parent_runner.read_text(encoding='utf-8')
        after = current_runner.read_text(encoding='utf-8')
        self.runner_change_audit = compare_runner_sources(before, after)
        recorded = read_json(self.pin('deployment-records/runner-change-audit.json'))
        equal(recorded['status'], 'PASS_EXACT_PATH_ONLY_REPLACEMENTS', 'Recorded runner change audit')
        for field in ('parent_runner_sha256', 'new_runner_sha256', 'protected_measurement_section_sha256',
                      'measurement_section_unchanged_after_two_exe_path_normalizations',
                      'warmups_reviews_thresholds_timing_memory_aggregation_unchanged',
                      'meter_self_test_and_measure_calls_unchanged'):
            equal(recorded[field], self.runner_change_audit[field], 'Independent/recorded runner change ' + field)
        equal(recorded['meter_sha256'], METER_SHA256, 'Recorded frozen meter')
        self.pin('deployment-records/runner-path-only.diff')

    def files(self, raw):
        for field, relative in (
            ('manifest_sha256', 'manifest.json'), ('harness_sha256', 'run_current_cases.py'),
            ('meter_sha256', 'windows_metrics.py'), ('case_manifest_sha256', 'cases_current.json')):
            self.pin(relative, raw[field])
        need(raw['meter_sha256'] == METER_SHA256, 'Frozen root-process meter changed')
        manifest = read_json(self.path('manifest.json'))
        self.manifest = manifest
        need(str(manifest['yosys_release']) == '0.69', 'Unexpected Yosys release')
        need(manifest.get('package_layout') == LAYOUT, 'Only the declared co-located v26 layout is supported')
        need(manifest['candidate_version'].startswith('v26'), 'Unexpected candidate version')
        equal(manifest['source_sha256'], SOURCE_SHA256, 'Reviewed v26 source')
        equal(manifest['script_sha256'], SCRIPT_SHA256, 'Reviewed v26 F3 script')
        equal(manifest['source_patch_sha256'], PATCH_SHA256, 'Reviewed v26 full patch')
        equal(manifest['runner_sha256'], raw['harness_sha256'], 'Declared actual runner hash')
        equal(manifest['meter_sha256'], METER_SHA256, 'Declared frozen meter hash')
        equal(manifest['deployment_change'], 'shared_runtime_same_binary_bytes', 'Deployment scope')
        equal(set(manifest['roles']), set(ROLES), 'manifest roles')
        need(set(manifest['shared_files']) == SHARED_FILES, 'Unexpected shared-runtime file set')
        for name, digest in manifest['shared_files'].items():
            self.pin(name, digest)
        abc_bindings = {}
        resource_union = {}
        for role in ROLES:
            item = manifest['roles'][role]
            role_path = self.root / role
            need(not role_path.exists() and not role_path.is_symlink(), 'Legacy role directory is forbidden')
            need({'yosys.exe', 'yosys-abc.exe'} <= set(item['files']), 'Missing role executable pins')
            need(len({name.casefold() for name in item['files']}) == len(item['files']), 'Duplicate case-folded role paths')
            origins = {name: ('yosys-' + role + '.exe' if name == 'yosys.exe' else name)
                       for name in item['files']}
            equal(item.get('file_origins'), origins, 'Complete role physical origins')
            for logical, digest in item['files'].items():
                need(logical in SHARED_FILES | {'yosys.exe'} or logical.startswith('share/'),
                     'Unexpected role payload kind: ' + logical)
                self.pin(origins[logical], digest)
                if logical.startswith('share/'):
                    old = resource_union.setdefault(logical, digest)
                    equal(digest, old, 'Shared resource bytes differ between roles: ' + logical)
            abc_bindings[role] = item['files']['yosys-abc.exe']
            for dll in SHARED_FILES - {'yosys-abc.exe'}:
                equal(item['files'][dll], manifest['shared_files'][dll], 'Role/root DLL identity')
        need(abc_bindings['baseline'] == abc_bindings['candidate'] == manifest['shared_files']['yosys-abc.exe'],
             'Shared ABC identity differs')
        equal(manifest['shared_resources'], resource_union, 'Complete shared resource union')
        share = self.root / 'share'
        actual_resources = set()
        for path in share.rglob('*'):
            need(not path.is_symlink() and path.resolve().is_relative_to(share.resolve()), 'Symbolic/external shared resource')
            if path.is_file():
                actual_resources.add(path.relative_to(self.root).as_posix())
        equal(actual_resources, set(resource_union), 'Unmanifested shared resources')
        root_binaries = {p.name for p in self.root.iterdir() if p.is_file() and p.suffix.lower() in {'.exe', '.dll'}}
        equal(root_binaries, SHARED_FILES | {'yosys-baseline.exe', 'yosys-candidate.exe'}, 'Root binary closure')
        baseline_resources = {name: digest for name, digest in manifest['roles']['baseline']['files'].items() if name.startswith('share/')}
        candidate_resources = {name: digest for name, digest in manifest['roles']['candidate']['files'].items() if name.startswith('share/')}
        equal(set(candidate_resources) - set(baseline_resources), {'share/intel/competition_abc_v11.abc'}, 'Only candidate resource addition')
        need(set(baseline_resources) <= set(candidate_resources), 'Baseline resource missing in candidate')
        for name, digest in manifest['runtime_sha256'].items():
            self.pin('runtime/' + name, digest)
        for field, name in (
            ('source_pristine_sha256', 'source/yosys-0.69-pristine.tar.gz'),
            ('source_sha256', 'source/pmux_competition_v11.cc'),
            ('script_sha256', 'source/competition_abc_dch.abc'),
            ('source_patch_sha256', 'source/synth-intel-competition.patch')):
            self.pin(name, manifest[field])
        scripts = [name for name in manifest['roles']['candidate']['files'] if name.endswith(('.abc', '.script'))]
        need(len(scripts) == 1, 'Expected a single fixed candidate ABC script')
        need(manifest['roles']['candidate']['files'][scripts[0]] == manifest['script_sha256'],
             'Installed and submitted ABC script identities differ')
        need(self.path('source/competition_abc_dch.abc').read_text(encoding='utf-8').strip() == ABC_RECIPE,
             'Unexpected source ABC recipe')
        prepared = read_json(self.pin('build-records/prepared.json'))
        equal(manifest['source_sha256'], prepared['candidate_source_sha256'], 'Compiled source binding')
        equal(manifest['source_patch_sha256'], prepared['patch_sha256'], 'Prepared patch binding')
        parity = read_json(self.pin('build-records/pair-config-parity.json'))
        need(parity['status'].startswith('PASS_'), 'Build parameter parity not established')
        for role in ROLES:
            built = read_json(self.pin('build-records/built-' + role + '.json'))
            equal(manifest['roles'][role]['files'], built['files'], 'Built role artifact inventory')
        self.audit_runner_change(raw, manifest)
        return manifest, {'layout': LAYOUT, 'shared_abc_path': 'yosys-abc.exe',
                          'sha256': abc_bindings['baseline'], 'role_abc_shadows_absent': True,
                          'shared_dll_count': 5, 'shared_resource_count': len(resource_union),
                          'physical_executables': {role: 'yosys-' + role + '.exe' for role in ROLES}}

    def run(self):
        raw_hash = sha(self.report)
        self.fingerprints[str(self.report)] = raw_hash
        raw = read_json(self.report)
        need(raw['status'] in {'MEASUREMENTS_PASS_FORMAL_PENDING', 'MEASUREMENTS_REVIEW_FORMAL_PENDING'},
             'Require a completed measurement report; formal acceptance is separate')
        equal(raw['formal_status'], 'PENDING', 'formal status')
        equal(raw['meter_self_test'], 'PASS', 'Meter positive control')
        protocol = raw['protocol']
        equal(protocol['pair_order'], list(ROLES), 'Declared pair order')
        equal(protocol['warmup'], 'Ten baseline-only full runs per case immediately before the first measured pair',
              'Declared baseline warmups')
        equal(protocol['review_trigger'], 'Both first baseline and candidate wall times <1s and either overhead >5%',
              'Require explicitly declared new eligibility protocol')
        equal(protocol['review'], 'Five additional baseline-then-candidate pairs; retain first pair separately',
              'Review protocol')
        equal(protocol['aggregation'], 'If reviewed, ratio of the two role arithmetic means from five additional pairs; first pair excluded',
              'Mean-ratio protocol')
        equal(protocol['large_case'], 'Either first execution >10s: first pair only, no review',
              'Large-case protocol')
        equal(protocol['middle_case'], 'Maximum of the two first executions 1..10s: first pair only; FAQ does not specify a review rule',
              'Middle-case protocol')
        manifest, abc = self.files(raw)
        registry = read_json(self.path('cases_current.json'))
        entries = registry['cases'] if isinstance(registry, dict) else registry
        need(raw['case_count'] == len(raw['cases']) == len(entries) == 9, 'Require all nine cases')
        names = [str(entry.get('name', entry.get('id', ''))) for entry in entries]
        need(len(set(names)) == 9, 'Duplicate registry cases')
        equal([row['name'] for row in raw['cases']], names, 'Case order')
        output = {'status': 'AUDIT_RUNNING', 'package': str(self.root), 'raw_report': str(self.report),
                  'raw_report_sha256': raw_hash, 'raw_status': raw['status'], 'shared_abc': abc,
                  'script_sha256': sha(__file__), 'cases': [],
                   'runner_change_audit': self.runner_change_audit,
                  'formula': '100 * (mean(candidate) / mean(baseline) - 1); never mean(pair percentages)',
                  'protocol_scope': 'Predeclared v25 both-first-executions-under-1s eligibility; five additional pairs',
                  'formal_status': 'NOT_AUDITED; no proof success is asserted',
                  'official_interpretation_confirmed': False,
                  'sensitivity_is_not_an_extra_acceptance_gate': True,
                  'declared_order_and_labels_verified_not_external_execution_timestamps': True,
                  'security_environment_condition_not_verified': True,
                  'no_yosys_abc_or_performance_runs': True}
        all_candidates = []
        for row, entry in zip(raw['cases'], entries):
            name = row['name']
            top = str(entry.get('top', name))
            equal(row['top'], top, name + ' top')
            equal(row['source_path'], entry['path'], name + ' RTL path')
            equal(row['source_sha256'], entry['sha256'], name + ' RTL digest')
            self.pin(entry['path'], entry['sha256'])
            equal(set(row['roles']), set(ROLES), name + ' roles')
            for role in ROLES:
                equal(row['roles'][role]['path'], raw['directory'] + '/' + name + '/' + role,
                      name + '/' + role + ' case output directory')
            need(len(row['warmup_samples']) == 10, name + ': need ten baseline warmups')
            baseline_dir = row['roles']['baseline']['path']
            for i, sample in enumerate(row['warmup_samples'], 1):
                self.sample(sample, f'warmup-{i:02d}', 'baseline', baseline_dir)
            first, reviews = row['first_pair'], row['review_pairs']
            for pair in [first, *reviews]:
                equal(list(pair), list(ROLES), name + ' pair role insertion order')
            # Validate raw sample numbers before computing threshold decisions.
            role_samples = {}
            for role in ROLES:
                data = row['roles'][role]
                samples = [first[role], *[pair[role] for pair in reviews]]
                equal(data['samples'], samples, name + '/' + role + ' complete sample history')
                for i, sample in enumerate(samples):
                    self.sample(sample, 'first' if i == 0 else f'review-{i:02d}', role, data['path'])
                role_samples[role] = samples
            eligible, trigger, first_overheads = review_rule(first)
            equal(row['review_triggered'], trigger, name + ' review trigger')
            need(len(reviews) == (5 if trigger else 0), name + ': wrong fixed review pair count')
            equal(row['first_pair_overheads'], first_overheads, name + ' first overheads')
            b, c = (first[role]['wall_seconds'] for role in ROLES)
            eligibility = {'baseline_under_1s': b < 1, 'candidate_under_1s': c < 1,
                           'pair_sum_seconds': b + c, 'pair_sum_under_1s': b + c < 1,
                           'interpretation': 'Each complete execution in the first pair must be under 1s; not just baseline'}
            equal(row['review_eligibility'], eligibility, name + ' eligibility metadata')
            band = 'both_under_1s' if eligible else ('over_10s' if max(b, c) > 10 else '1_to_10s_unspecified_review')
            equal(row['runtime_band'], band, name + ' runtime band')
            selected_pairs = reviews if trigger else [first]
            equal(row['selected_measurements'], 'five_additional_review_pairs_mean' if trigger else 'first_pair',
                  name + ' selection')
            selected = cohort(selected_pairs)
            for key, metric in (('wall_overhead_percent', 'wall_seconds'),
                                ('memory_overhead_percent', 'peak_working_set_bytes'),
                                ('cpu_overhead_percent_supplementary', 'cpu_seconds')):
                equal(row[key], selected['metrics'][metric]['overhead_percent'], name + ' ' + key)
            counts = {}
            for role in ROLES:
                data = row['roles'][role]
                equal(data['selected_summary'], summary([pair[role] for pair in selected_pairs]), name + '/' + role + ' selected summary')
                equal(data['all_measured_summary'], summary(role_samples[role]), name + '/' + role + ' all summary')
                equal(data['executable_sha256'], manifest['roles'][role]['files']['yosys.exe'], name + '/' + role + ' PE')
                for key, filename in (('flow_sha256', 'flow.ys'), ('postabc_flow_sha256', 'postabc.ys'), ('ilang_sha256', 'postabc.il')):
                    self.pin(data['path'] + '/' + filename, data[key])
                need(data['formal_object_status'] == 'EXPORTED_NOT_PROVED', 'Unexpected formal claim in measurement')
                counts[role] = final_counts(read_json(self.pin(data['path'] + '/netlist.json')), top)
                split_counts = final_counts(read_json(self.pin(data['path'] + '/split-final.json')), top)
                equal(split_counts, counts[role], name + '/' + role + ' split export resources')
                for key, value in counts[role].items():
                    equal(data[key], value, name + '/' + role + ' ' + key)
            original, optimized = (counts[role]['scored_logic_cells'] for role in ROLES)
            need(original > 0, 'Zero baseline scored logic: ' + name)
            gain = 100.0 * (original - optimized) / original
            nonincrease = optimized <= original
            equal(row['logic_gain_percent'], gain, name + ' area gain')
            equal(row['logic_cells_nonincrease'], nonincrease, name + ' nonincrease')
            equal(row['dff_cells_nonincrease_diagnostic'], counts['candidate']['dff_cells'] <= counts['baseline']['dff_cells'], name + ' DFF diagnostic')
            wall = selected['metrics']['wall_seconds']['overhead_percent']
            memory = selected['metrics']['peak_working_set_bytes']['overhead_percent']
            efficient = wall <= 5 and memory <= 5
            over15 = wall > 15 or memory > 15
            absolute = all(s['wall_seconds'] <= 60 and s['peak_working_set_bytes'] <= 2_000_000_000 for s in role_samples['candidate'])
            equal(row['efficiency_5pct_pass'], efficient, name + ' efficiency flag')
            equal(row['efficiency_over_15pct'], over15, name + ' >15% flag')
            equal(row['efficiency_band'], 'FULL_MARKS' if efficient else ('NO_EFFICIENCY_MARKS' if over15 else 'PARTIAL_MARKS_REVIEW'), name + ' efficiency band')
            equal(row['absolute_limits_pass'], absolute, name + ' absolute limits')
            all_candidates.extend(role_samples['candidate'])
            output['cases'].append({'name': name, 'review_time_eligible': eligible, 'review_triggered': trigger,
                                    'first_pair_sum_seconds': b + c, 'first_pair_sum_under_1s': b + c < 1,
                                    'selected': selected, 'logic_gain_percent': gain, 'counts': counts,
                                    'logic_nonincrease': nonincrease, 'efficiency_5pct_pass': efficient,
                                    'efficiency_over_15pct': over15, 'absolute_limits_pass': absolute,
                                    'sensitivity_diagnostic_only': {
                                        'first_pair': cohort([first]), 'five_additional_pairs': cohort(reviews, 5),
                                        'first_plus_first_four': cohort([first, *reviews[:4]], 5),
                                        'all_six_pairs': cohort([first, *reviews], 6),
                                        'all_measured_pairs': cohort([first, *reviews])}})
        rows = output['cases']
        derived = {'average_gain_percent': statistics.mean(row['logic_gain_percent'] for row in rows),
                   'all_logic_cells_nonincrease': all(row['logic_nonincrease'] for row in rows),
                   'all_efficiency_5pct_pass': all(row['efficiency_5pct_pass'] for row in rows),
                   'any_efficiency_over_15pct': any(row['efficiency_over_15pct'] for row in rows),
                   'all_absolute_limits_pass': all(row['absolute_limits_pass'] for row in rows)}
        for key, value in derived.items():
            equal(raw[key], value, 'overall ' + key)
        passed = derived['average_gain_percent'] >= 20 and all(derived[key] for key in (
            'all_logic_cells_nonincrease', 'all_efficiency_5pct_pass', 'all_absolute_limits_pass'))
        equal(raw['status'], 'MEASUREMENTS_PASS_FORMAL_PENDING' if passed else 'MEASUREMENTS_REVIEW_FORMAL_PENDING', 'overall status')
        output['recomputed'] = {**derived, 'area_average_at_least_20pct': derived['average_gain_percent'] >= 20,
                                'predeclared_measurement_criteria_pass': passed,
                                'candidate_measured_sample_count': len(all_candidates),
                                'candidate_max_wall_seconds': max(s['wall_seconds'] for s in all_candidates),
                                'candidate_max_root_peak_working_set_bytes': max(s['peak_working_set_bytes'] for s in all_candidates)}
        eligible_rows = [r for r in rows if r['review_time_eligible']]
        reviewed_rows = [r for r in rows if r['review_triggered']]
        output['additional_interpretation_information_only'] = {
            'time_eligible_cases': [r['name'] for r in eligible_rows],
            'reviewed_cases': [r['name'] for r in reviewed_rows],
            'all_time_eligible_first_pair_sums_under_1s': all(r['first_pair_sum_under_1s'] for r in eligible_rows) if eligible_rows else None,
            'all_reviewed_first_pair_sums_under_1s': all(r['first_pair_sum_under_1s'] for r in reviewed_rows) if reviewed_rows else None,
            'time_eligible_sum_at_least_1s': [r['name'] for r in eligible_rows if not r['first_pair_sum_under_1s']],
            'reviewed_sum_at_least_1s': [r['name'] for r in reviewed_rows if not r['first_pair_sum_under_1s']],
            'affects_predeclared_verdict': False}
        for path, expected in self.fingerprints.items():
            need(sha(path) == expected, 'Input changed during read-only audit: ' + path)
        output['file_fingerprints'] = self.fingerprints
        output['all_inputs_unchanged_after_audit'] = True
        output['status'] = 'INDEPENDENT_AUDIT_PASS'
        output['audited_utc'] = datetime.now(timezone.utc).isoformat()
        return output


def self_test():
    def sample(wall, memory=100, cpu=0.01):
        return dict(wall_seconds=wall, peak_working_set_bytes=memory, cpu_seconds=cpu, root_cpu_seconds=cpu)
    first = {'baseline': sample(.2), 'candidate': sample(.24)}
    eligible, trigger, _ = review_rule(first)
    need(eligible and trigger, 'Short time-overhead trigger')
    need(not review_rule({'baseline': sample(.2), 'candidate': sample(1.0)})[1], 'Both sides must be <1, not <=1')
    need(not review_rule({'baseline': sample(.99), 'candidate': sample(.99)})[1], 'Eligibility alone is not trigger')
    need(review_rule({'baseline': sample(.2), 'candidate': sample(.2, 106)})[1], 'Memory can trigger review')
    pairs = [{'baseline': sample(.1), 'candidate': sample(.2)},
             {'baseline': sample(.3), 'candidate': sample(.3)}]
    equal(cohort(pairs)['metrics']['wall_seconds']['overhead_percent'], 25.0, 'Ratio of means, not mean ratios')
    need(not cohort(pairs, 5)['available'], 'Missing sensitivity samples cannot be invented')
    equal(summary([sample(.1), sample(.3)])['max_wall_seconds'], .3, 'All-sample maximum')
    need(cohort([{'baseline': sample(.1, cpu=0), 'candidate': sample(.1, cpu=0)}])['metrics']['cpu_seconds']['overhead_percent'] is None,
         'Zero supplementary CPU denominator is undefined, not primary failure')
    circuit = {'modules': {'top': {'cells': {'a': {'type': 'sub'}, 'b': {'type': 'sub'}, 'd': {'type': 'dffeas'}}},
                           'sub': {'cells': {'l': {'type': 'cycloneiv_lcell_comb'}, 'n': {'type': '$not'}}}}}
    counted = final_counts(circuit, 'top')
    equal(counted['scored_logic_cells'], 4, 'Hierarchical instance multiplicity and NOT count')
    equal(counted['dff_cells'], 1, 'DFF separate')
    try:
        final_counts({'modules': {'top': {'cells': {'loop': {'type': 'top'}}}}}, 'top')
    except ValueError:
        pass
    else:
        raise AssertionError('Recursive hierarchy was not rejected')
    fake = Audit(Path('synthetic-shared-package'), Path('synthetic-report.json'))
    fake.pin = lambda name, expected=None: Path(name)
    directory = 'validation-current-example/test1/candidate'
    header = "-- Executing script file `D:\\original-package\\validation-current-example\\test1\\candidate\\flow.ys' --\n"
    fake.logged_file('<yosys-exe-dir>/yosys-abc', 'yosys-abc.exe', header, directory)
    fake.logged_file('D:/original-package/yosys-abc', 'yosys-abc.exe', header, directory)
    fake.logged_file('<yosys-exe-dir>/share/intel/competition_abc_v11.abc',
                     'share/intel/competition_abc_v11.abc', header, directory)
    for wrong in ('<yosys-exe-dir>/../yosys-abc', 'D:/different-package/yosys-abc',
                  '<yosys-exe-dir>/candidate/yosys-abc'):
        try:
            fake.logged_file(wrong, 'yosys-abc.exe', header, directory)
        except ValueError:
            pass
        else:
            raise AssertionError('Unexpected logged ABC origin accepted: ' + wrong)
    print('SYNTHETIC_STATISTICS_AND_COUNTING_SELF_TEST_PASS (no files, Yosys, or performance samples)')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--self-test', action='store_true', help='Pure synthetic arithmetic/counting checks only')
    args = parser.parse_args()
    if args.self_test:
        need(not any((args.package, args.report, args.output)), '--self-test takes no file arguments')
        self_test()
        return 0
    need(all((args.package, args.report, args.output)), '--package, --report and --output are required')
    target = args.output.resolve()
    need(not target.exists(), 'Refusing to overwrite an existing audit output')
    need(target.parent.is_dir(), 'Audit output parent must already exist')
    need(target != args.report.resolve(), 'Audit output must not replace the original report')
    try:
        result = Audit(args.package, args.report).run()
    except Exception as error:
        result = {'status': 'INDEPENDENT_AUDIT_FAILED', 'error': str(error),
                  'package': str(args.package.resolve()), 'raw_report': str(args.report.resolve()),
                  'formal_status': 'NOT_AUDITED', 'no_yosys_abc_or_performance_runs': True,
                  'audited_utc': datetime.now(timezone.utc).isoformat()}
        with target.open('x', encoding='utf-8') as stream:
            stream.write(json.dumps(result, indent=2, ensure_ascii=False) + '\n')
        print(json.dumps(result, ensure_ascii=False), file=sys.stderr)
        return 1
    with target.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(result, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({'status': result['status'], 'output': str(target),
                      'recomputed': result['recomputed']}, ensure_ascii=False))
    return 0 if result['recomputed']['predeclared_measurement_criteria_pass'] else 2


if __name__ == '__main__':
    sys.exit(main())
