"""Rebuild both Windows Yosys roles from a released, source-pinned package.

This script belongs in PACKAGE/source/. It creates a new ASCII output tree,
uses only local tools/inputs, preserves the delivered binaries, and never runs
Yosys, ABC, the competition runner, or a performance/formal acceptance test.
The fixed packaged ABC binary is reused, not rebuilt.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import struct
import subprocess
import tarfile

PINNED_COMMIT = '9f75ca1f9834a39a863915b5dae0c7b1e33533bc'
PINNED_PRISTINE = '086045e23253917b93c71fc2d9db495df3c153cdc5d212bac505df7c4ad62e2f'
COMPATIBILITY_FLAG = '-fno-declone-ctor-dtor'
EXPECTED_CHANGES = {
    'passes/opt/CMakeLists.txt', 'passes/opt/pmux_competition_opt.cc',
    'techlibs/intel/CMakeLists.txt', 'techlibs/intel/synth_intel.cc',
    'techlibs/intel/competition_abc_v11.abc',
}
RUNTIME_NAMES = ('yosys-abc.exe', 'libffi-8.dll', 'libgcc_s_seh-1.dll',
                 'libstdc++-6.dll', 'libwinpthread-1.dll', 'zlib1.dll')
GENERATED_RESOURCES = {
    'techlibs/gatemate/lut_tree_cells.genlib': ('techlibs/gatemate/make_lut_tree_lib.py', 'share/gatemate/lut_tree_cells.genlib'),
    'techlibs/gatemate/lut_tree_map.v': ('techlibs/gatemate/make_lut_tree_lib.py', 'share/gatemate/lut_tree_map.v'),
    'techlibs/quicklogic/qlf_k6n10f/bram_types_sim.v': ('techlibs/quicklogic/qlf_k6n10f/generate_bram_types_sim.py', 'share/quicklogic/qlf_k6n10f/bram_types_sim.v'),
}


def require(test, message):
    if not test:
        raise RuntimeError(message)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def stamp():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def save_new(path, data):
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def copy_new(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    with Path(source).open('rb') as inp, target.open('xb') as out:
        shutil.copyfileobj(inp, out)
    require(sha(source) == sha(target), f'Copy mismatch: {target}')


def inventory(root):
    result = {}
    for path in sorted(root.rglob('*')):
        require(not path.is_symlink(), f'Symlink not allowed in this build: {path}')
        if path.is_file():
            result[path.relative_to(root).as_posix()] = sha(path)
    return result


def index_without_stat_cache(data):
    require(len(data) >= 32, 'Truncated Git index')
    signature, version, count = struct.unpack('>4sII', data[:12])
    require(signature == b'DIRC' and version in (2, 3), 'Unsupported Git index format')
    require(hashlib.sha1(data[:-20]).digest() == data[-20:], 'Git index checksum mismatch')
    normalized = bytearray(data[:-20])
    offset = 12
    for _ in range(count):
        start = offset
        require(offset+62 <= len(data)-20, 'Truncated Git index entry')
        flags = struct.unpack('>H', data[offset+60:offset+62])[0]
        normalized[offset:offset+24] = b'\0'*24
        normalized[offset+28:offset+40] = b'\0'*12
        offset += 62 + (2 if flags & 0x4000 else 0)
        end = data.index(b'\0', offset)
        offset = start + ((end+1-start+7)//8)*8
        require(offset <= len(data)-20, 'Invalid Git index pathname/padding')
    return bytes(normalized)


def package_root():
    source = Path(__file__).resolve().parent
    require(source.name == 'source' and (source.parent/'manifest.json').is_file(),
            'Place this script in the released package source/ directory, next to the pristine archive and patch.')
    return source.parent


def validated_members(tar):
    members = tar.getmembers()
    names = set()
    for member in members:
        name = member.name.rstrip('/')
        path = PurePosixPath(name)
        require(name and not path.is_absolute() and '..' not in path.parts
                and ':' not in name and '\\' not in name, f'Unsafe archive path: {name}')
        require(member.isfile() or member.isdir(), f'Unsupported archive entry: {name}')
        require(name.casefold() not in names, f'Archive name collision: {name}')
        names.add(name.casefold())
    return members


def apply_checked_patch(tar, patch, approved_source, approved_abc_script):
    members = {m.name: m for m in validated_members(tar) if m.isfile()}
    result = {}
    for block in patch.decode('utf-8').split('diff --git ')[1:]:
        lines = block.splitlines(True)
        name = lines[0].split(' b/', 1)[1].strip()
        require(name in EXPECTED_CHANGES and name not in result, f'Unexpected patch target: {name}')
        original = tar.extractfile(members[name]).read() if name in members else b''
        before = original.replace(b'\r\n', b'\n').decode('utf-8').splitlines(True)
        output, cursor = [], 0
        pos = next(i for i, line in enumerate(lines) if line.startswith('@@ '))
        while pos < len(lines):
            hunk = re.match(r'@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@', lines[pos])
            require(hunk is not None, f'Invalid patch hunk: {name}')
            old_start = int(hunk.group(1))
            old_count, new_count = int(hunk.group(2) or '1'), int(hunk.group(4) or '1')
            old_pos = old_start-1 if old_count else old_start
            require(old_pos >= cursor, f'Overlapping patch hunks: {name}')
            output.extend(before[cursor:old_pos])
            cursor, consumed, produced = old_pos, 0, 0
            pos += 1
            while pos < len(lines) and not lines[pos].startswith('@@ '):
                prefix, body = lines[pos][:1], lines[pos][1:]
                require(prefix in (' ', '+', '-'), f'Unsupported patch line: {name}')
                if prefix in (' ', '-'):
                    require(cursor < len(before) and before[cursor] == body,
                            f'Patch context mismatch: {name}:{cursor+1}')
                    cursor += 1
                    consumed += 1
                if prefix in (' ', '+'):
                    output.append(body)
                    produced += 1
                pos += 1
            require((consumed, produced) == (old_count, new_count), f'Hunk count mismatch: {name}')
        output.extend(before[cursor:])
        result[name] = ''.join(output).encode('utf-8')
    require(set(result) == EXPECTED_CHANGES, 'The patch must change exactly the five declared files')
    require(result['passes/opt/pmux_competition_opt.cc'] == approved_source, 'Patch/source disagreement')
    require(result['techlibs/intel/competition_abc_v11.abc'] == approved_abc_script, 'Patch/ABC-script disagreement')
    return result


def validate_inputs(package, manifest):
    require(manifest.get('package_layout') == 'colocated_yosys_shared_runtime', 'Expected a colocated shared-runtime package')
    source = package/'source'
    expected = {
        'yosys-0.69-pristine.tar.gz': manifest['source_pristine_sha256'],
        'synth-intel-competition.patch': manifest['source_patch_sha256'],
        'pmux_competition_v11.cc': manifest['source_sha256'],
        'competition_abc_dch.abc': manifest['script_sha256'],
    }
    require(manifest['yosys_commit'] == PINNED_COMMIT, 'Manifest does not identify the verified Yosys 0.69 commit')
    require(expected['yosys-0.69-pristine.tar.gz'] == PINNED_PRISTINE,
            'Pristine archive is not the verified expanded Yosys 0.69 source package')
    frozen = {str(package/'manifest.json'): sha(package/'manifest.json')}
    for name, digest in expected.items():
        require(sha(source/name) == digest, f'Manifest input hash mismatch: source/{name}')
        frozen[str(source/name)] = digest
    runtime = {}
    for name in RUNTIME_NAMES:
        a = manifest['roles']['baseline']['files'][name]
        b = manifest['roles']['candidate']['files'][name]
        require(a == b, f'The roles do not share the same runtime bytes: {name}')
        require(manifest['shared_files'][name] == a, f'Shared runtime identity differs: {name}')
        require(sha(package/name) == a, f'Shared root runtime hash mismatch: {name}')
        frozen[str(package/name)] = a
        for role in ('baseline', 'candidate'):
            origin = manifest['roles'][role].get('file_origins', {}).get(name)
            require(origin == name, f'Runtime must originate at package root: {role}/{name}')
        runtime[name] = a
    resources = {}
    for role in ('baseline', 'candidate'):
        require(not (package/role).exists(), f'Unexpected role directory: {role}')
        files = manifest['roles'][role]['files']
        origins = manifest['roles'][role]['file_origins']
        require(origins == {name: f'yosys-{role}.exe' if name == 'yosys.exe' else name for name in files},
                f'Every role file must have a declared colocated origin: {role}')
        for name, digest in files.items():
            require(name == 'yosys.exe' or name in RUNTIME_NAMES or name.startswith('share/'), f'Unexpected role file: {name}')
            path = package/origins[name]
            require(path.resolve().is_relative_to(package.resolve()), f'Path escapes package: {name}')
            require(sha(path) == digest, f'Delivered role file changed: {role}/{name}')
            frozen[str(path)] = digest
            if name.startswith('share/'):
                require(name not in resources or resources[name] == digest, f'Conflicting resources: {name}')
                resources[name] = digest
    require(resources == manifest['shared_resources'], 'Shared resource manifest differs from role union')
    require({'share/'+name: digest for name, digest in inventory(package/'share').items()} == resources,
            'Shared resource tree differs from the complete union')
    return frozen, runtime


def prepare_sources(package, output):
    source = package/'source'
    with tarfile.open(source/'yosys-0.69-pristine.tar.gz', 'r:gz') as tar:
        members = validated_members(tar)
        regular = {m.name: m for m in members if m.isfile()}
        commit = tar.extractfile(regular['.gitcommit']).read().decode().strip()
        require(commit == PINNED_COMMIT, 'Archive .gitcommit mismatch')
        version = tar.extractfile(regular['cmake/YosysVersionData.cmake']).read().decode()
        require('set(YOSYS_VERSION_MAJOR 0)' in version and 'set(YOSYS_VERSION_MINOR 69)' in version, 'Archive version data mismatch')
        modules = re.findall(r'^\s*path\s*=\s*(.+)$', tar.extractfile(regular['.gitmodules']).read().decode(), re.M)
        module_counts = {m.strip(): sum(n.startswith(m.strip()+'/') for n in regular) for m in modules}
        require(len(module_counts) >= 8 and all(module_counts.values()), 'Expanded submodules are missing')
        reconstructed = apply_checked_patch(tar, (source/'synth-intel-competition.patch').read_bytes(),
                                             (source/'pmux_competition_v11.cc').read_bytes(),
                                             (source/'competition_abc_dch.abc').read_bytes())
        maps = {}
        for role in ('baseline', 'candidate'):
            dest = output/'sources'/role
            dest.mkdir(parents=True)
            for member in members:
                target = dest.joinpath(*PurePosixPath(member.name).parts)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    data = reconstructed[member.name] if role == 'candidate' and member.name in reconstructed else tar.extractfile(member).read()
                    with target.open('xb') as stream:
                        stream.write(data)
            if role == 'candidate':
                for name in EXPECTED_CHANGES-set(regular):
                    target = dest/name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with target.open('xb') as stream:
                        stream.write(reconstructed[name])
            maps[role] = inventory(dest)
        a, b = maps['baseline'], maps['candidate']
        changed = sorted(n for n in a.keys() | b.keys() if a.get(n) != b.get(n))
        require(set(changed) == EXPECTED_CHANGES, f'Unexpected source difference: {changed}')
        original_index = tar.extractfile(regular['.git/index']).read()
        return {'source_inventories': maps, 'source_changed_files': changed, 'submodule_file_counts': module_counts,
                'index_nonstat_content_sha256': hashlib.sha256(index_without_stat_cache(original_index)).hexdigest(),
                'upstream_generator_sha256': {name: hashlib.sha256(tar.extractfile(regular[name]).read()).hexdigest()
                                             for name in {value[0] for value in GENERATED_RESOURCES.values()}},
                'normalization': 'Baseline archive bytes retained. Candidate patch normalizes only its three existing target files to LF.'}


def cmake_command(tools, output, role):
    flags = {
        'CMAKE_BUILD_TYPE': 'MinSizeRel', 'CMAKE_EXPORT_COMPILE_COMMANDS': 'ON',
        'CMAKE_C_COMPILER': tools['gcc.exe'], 'CMAKE_CXX_COMPILER': tools['g++.exe'],
        'CMAKE_MAKE_PROGRAM': tools['ninja.exe'], 'CMAKE_RC_COMPILER': tools['windres.exe'],
        'BISON_EXECUTABLE': tools['bison.exe'], 'BISON_M4_EXECUTABLE': tools['m4.exe'],
        'FLEX_EXECUTABLE': tools['flex.exe'], 'Python3_EXECUTABLE': tools['python.exe'],
        'CMAKE_C_COMPILER_LAUNCHER': '', 'CMAKE_CXX_COMPILER_LAUNCHER': '',
        'CMAKE_C_FLAGS': '', 'CMAKE_CXX_FLAGS': COMPATIBILITY_FLAG, 'CMAKE_EXE_LINKER_FLAGS': '',
        'CMAKE_INTERPROCEDURAL_OPTIMIZATION': 'OFF', 'BUILD_SHARED_LIBS': 'OFF',
        'YOSYS_CHECKOUT_INFO': PINNED_COMMIT + ('-dirty' if role == 'candidate' else ''),
        'YOSYS_COMPONENTS': 'everything', 'YOSYS_ABC_EXECUTABLE': '', 'YOSYS_WITHOUT_ABC': 'OFF',
        'YOSYS_USE_BUNDLED_LIBS': 'ON', 'YOSYS_WITHOUT_SLANG': 'ON',
        'YOSYS_WITHOUT_READLINE': 'ON', 'YOSYS_WITHOUT_EDITLINE': 'ON',
        'YOSYS_WITHOUT_TCL': 'ON', 'YOSYS_WITHOUT_LIBFFI': 'OFF',
        'YOSYS_WITHOUT_ZLIB': 'OFF', 'YOSYS_WITH_PYTHON': 'OFF',
        'YOSYS_ENABLE_COVERAGE': 'OFF', 'YOSYS_ENABLE_PROFILING': 'OFF',
        'YOSYS_ENABLE_FUNCTIONAL_TESTS': 'OFF', 'YOSYS_ENABLE_UNIT_TESTS': 'OFF',
        'YOSYS_INSTALL_DRIVER': 'ON', 'YOSYS_INSTALL_LIBRARY': 'OFF',
    }
    return [str(tools['cmake.exe']), '-S', (output/'sources'/role).as_posix(),
            '-B', (output/'build'/role).as_posix(), '-G', 'Ninja',
            *[f'-D{k}={v.as_posix() if isinstance(v, Path) else v}' for k, v in flags.items()]]


def audit_configuration(output, role):
    build, source = output/'build'/role, output/'sources'/role
    entries = json.loads((build/'compile_commands.json').read_text(encoding='utf-8'))
    commands = {}
    for entry in entries:
        file = Path(entry['file'])
        try:
            name = file.relative_to(source).as_posix()
        except ValueError:
            name = '@build/'+file.relative_to(build).as_posix()
        if name.startswith('abc/'):
            continue
        text = (entry.get('command') or subprocess.list2cmdline(entry['arguments'])).replace('\\', '/')
        text = text.replace(source.as_posix(), '@source').replace(build.as_posix(), '@build')
        require(re.search(r'(?:^|\s)-Os(?:\s|$)', text), f'Missing -Os: {name}')
        require(not re.search(r'(?:^|\s)-O(?:0|1|2|3|g|fast)(?:\s|$)', text), f'Unexpected optimization level: {name}')
        require('-flto' not in text and 'ccache' not in text, f'Unexpected LTO/cache launcher: {name}')
        if Path(name).suffix in ('.cc', '.cpp', '.cxx', '.C', '.c++'):
            require(text.count(COMPATIBILITY_FLAG) == 1 and text.index(COMPATIBILITY_FLAG) < text.index('-Os'),
                    f'GNU compatibility flag missing or wrong precedence: {name}')
        require('-fdeclone-ctor-dtor' not in text, f'Conflicting constructor decloning flag: {name}')
        require(name not in commands, f'Duplicate compile entry: {name}')
        commands[name] = text
    require(len(commands) > 300, 'Unexpected component pruning')
    cache = (build/'CMakeCache.txt').read_text(encoding='utf-8')
    require('CMAKE_BUILD_TYPE:STRING=MinSizeRel' in cache, 'Wrong build type')
    require('CMAKE_CXX_FLAGS:STRING='+COMPATIBILITY_FLAG in cache, 'Wrong GNU compatibility flag')
    require(re.search(r'^YOSYS_ABC_EXECUTABLE:FILEPATH=$', cache, re.M), 'ABC lookup changed')
    ninja = (build/'build.ninja').read_text(encoding='utf-8')
    link = next(line for line in ninja.splitlines() if line.startswith('build yosys.exe '))
    require('yosys-abc.exe' not in link, 'yosys unexpectedly depends on rebuilding ABC')
    require('-municode' in ninja and '--export-all-symbols' in ninja, 'Original native link mode missing')
    compiler_files = sorted((build/'CMakeFiles').glob('*/CMakeCXXCompiler.cmake'))
    require(len(compiler_files) == 1, 'Could not identify the configured C++ compiler')
    compiler_info = compiler_files[0].read_text(encoding='utf-8')
    require('set(CMAKE_CXX_COMPILER_ID "GNU")' in compiler_info, 'This reconstruction requires the GNU UCRT64 compiler')
    compiler_version = re.search(r'set\(CMAKE_CXX_COMPILER_VERSION "([^"]+)"\)', compiler_info)
    require(compiler_version is not None, 'Configured GNU compiler version is missing')
    return {'normalized_commands': commands, 'cache_sha256': sha(build/'CMakeCache.txt'),
            'ninja_sha256': sha(build/'build.ninja'), 'compile_commands_sha256': sha(build/'compile_commands.json'),
            'compiler_id': 'GNU', 'compiler_version': compiler_version.group(1),
            'compatibility_flag': COMPATIBILITY_FLAG, 'compatibility_scope': 'all C++ units in both roles'}


def run(command, log, env, cwd):
    print('RUN', subprocess.list2cmdline(command), flush=True)
    with log.open('xb') as stream:
        completed = subprocess.run(command, env=env, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT)
    require(completed.returncode == 0, f'Command failed ({completed.returncode}); preserved log: {log}')


def verify_generated_resources(output, role, added, sources, configured, tools):
    if not added:
        return {}
    source, build = output/'sources'/role, output/'build'/role
    ninja_file = build/'build.ninja'
    require(sha(ninja_file) == configured['ninja_sha256'], f'Reviewed Ninja rules changed: {role}')
    ninja = ninja_file.read_text(encoding='utf-8')
    specifications = [
        (['techlibs/gatemate/lut_tree_cells.genlib', 'techlibs/gatemate/lut_tree_map.v'],
         'techlibs/gatemate/make_lut_tree_lib.py', source/'techlibs/gatemate', 'make_lut_tree_lib.py'),
        (['techlibs/quicklogic/qlf_k6n10f/bram_types_sim.v'],
         'techlibs/quicklogic/qlf_k6n10f/generate_bram_types_sim.py', source/'techlibs/quicklogic',
         'qlf_k6n10f/generate_bram_types_sim.py qlf_k6n10f/bram_types_sim.v'),
    ]
    generator_checks = {}
    for outputs, generator, cwd, arguments in specifications:
        if not set(outputs) & set(added):
            continue
        token = lambda path: path.as_posix().replace('$', '$$').replace(' ', '$ ').replace(':', '$:')
        declaration = 'build '+' '.join(token(source/name) for name in outputs)
        declaration += ': CUSTOM_COMMAND '+token(source/generator)
        blocks = [block for block in ninja.split('\n\n') if block.splitlines() and block.splitlines()[0] == declaration]
        require(len(blocks) == 1, f'Unrecognized upstream generation rule: {role}/{generator}')
        commands = [line.strip()[10:] for line in blocks[0].splitlines() if line.strip().startswith('COMMAND = ')]
        cmd_exe = subprocess.list2cmdline([str(Path(os.environ['SystemRoot'])/'system32/cmd.exe')])
        cmd_cwd = subprocess.list2cmdline([str(cwd)])
        cmd_python = subprocess.list2cmdline([str(tools['python.exe'])])
        expected_command = f'{cmd_exe} /C "cd /D {cmd_cwd} && {cmd_python} {arguments}"'
        normalize = lambda text: text.replace('\\', '/').casefold()
        require(len(commands) == 1 and normalize(commands[0]) == normalize(expected_command),
                f'Generation command differs from the approved upstream command: {role}/{generator}')
        digest = sha(source/generator)
        require(digest == sources['source_inventories'][role][generator] == sources['upstream_generator_sha256'][generator],
                f'Generator differs from pristine: {role}/{generator}')
        generator_checks[generator] = {'sha256': digest, 'ninja_rule': declaration, 'command': commands[0]}
    checks = {}
    for name in sorted(added):
        generator, share_name = GENERATED_RESOURCES[name]
        require((build/share_name).is_file(), f'Generated resource share copy is missing: {role}/{name}')
        digest = sha(source/name)
        require(digest == sha(build/share_name), f'Generated source and share copy disagree: {role}/{name}')
        checks[name] = {'sha256': digest, 'share_copy': share_name, 'generator': generator_checks[generator]}
    return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--toolchain-bin', required=True, type=Path, help='Existing MSYS2 UCRT64 bin directory containing GNU gcc/g++, CMake, Ninja and strip')
    parser.add_argument('--msys-bin', required=True, type=Path, help='Existing MSYS2 usr/bin directory containing bison/flex/m4')
    parser.add_argument('--python', required=True, type=Path, help='Complete Python executable for CMake/code generators; not the embedded runtime')
    parser.add_argument('--output', required=True, type=Path, help='New absolute ASCII directory outside the delivery package')
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--prepare-only', action='store_true', help='Validate/extract sources and record the plan without invoking build tools')
    args = parser.parse_args()
    require(os.name == 'nt', 'This script targets native Windows')
    require(1 <= args.jobs <= 8, '--jobs must be between 1 and 8')
    require(args.output.is_absolute(), '--output must be absolute')
    output = args.output.resolve()
    package = package_root()
    require(str(output).isascii(), '--output must contain only ASCII characters')
    require(not output.exists(), f'Output already exists; preserved without modification: {output}')
    require(not output.is_relative_to(package), 'Output must be outside the original delivery package')
    toolbin, msysbin, python = args.toolchain_bin.resolve(), args.msys_bin.resolve(), args.python.resolve()
    require(not python.is_relative_to(package/'runtime') and not list(python.parent.glob('python*._pth')),
            '--python must identify a complete Python installation, not an embedded runtime')
    require(not output.is_relative_to(toolbin) and not output.is_relative_to(msysbin)
            and not output.is_relative_to(python.parent), 'Output must be outside installed tool directories')
    tools = {name: toolbin/name for name in ('gcc.exe', 'g++.exe', 'cmake.exe', 'ninja.exe', 'strip.exe', 'windres.exe')}
    tools.update({name: msysbin/name for name in ('bison.exe', 'flex.exe', 'm4.exe')})
    tools['python.exe'] = python
    for name, path in tools.items():
        require(path.is_file(), f'Missing local tool: {name}: {path}')
    manifest = json.loads((package/'manifest.json').read_text(encoding='utf-8'))
    frozen, runtime = validate_inputs(package, manifest)
    # Reusing the fixed ABC requires its known runtime. Reject mixing runtime
    # generations silently when a different locally installed GCC is supplied.
    for name, digest in runtime.items():
        if name.endswith('.dll'):
            require((toolbin/name).is_file() and sha(toolbin/name) == digest,
                    f'Toolchain runtime differs from the delivered reference: {name}. Use the matching UCRT64 toolchain.')
    output.mkdir(parents=True)
    (output/'records').mkdir()
    (output/'inputs').mkdir()
    for name in ('manifest.json',):
        copy_new(package/name, output/'inputs'/name)
    for name in ('yosys-0.69-pristine.tar.gz', 'synth-intel-competition.patch', 'pmux_competition_v11.cc', 'competition_abc_dch.abc'):
        copy_new(package/'source'/name, output/'inputs'/name)
    tool_records = {name: {'path': str(path), 'sha256': sha(path)} for name, path in tools.items()}
    record = {'status': 'PREPARING', 'started_utc': stamp(), 'script_sha256': sha(__file__),
              'package': str(package), 'output': str(output), 'tools': tool_records,
              'frozen_input_hashes': frozen, 'runtime_hashes': runtime, 'abc_rebuilt': False,
              'compatibility_flag': COMPATIBILITY_FLAG,
              'compatibility_source': 'https://github.com/msys2/MINGW-packages/issues/31015',
              'no_yosys_or_abc_execution': True, 'formal_and_performance_acceptance': 'NOT_RUN'}
    save_new(output/'records/started.json', record)
    sources = prepare_sources(package, output)
    save_new(output/'records/prepared.json', {**record, **sources, 'status': 'PREPARED_NOT_BUILT',
             'configure_commands': {role: cmake_command(tools, output, role) for role in ('baseline', 'candidate')}})
    if args.prepare_only:
        print(f'PREPARED ONLY: {output}. This directory is not reused by a later full invocation; use a new output directory to build.')
        return
    env = os.environ.copy()
    for key in ('CFLAGS', 'CXXFLAGS', 'LDFLAGS', 'CC', 'CXX', 'CMAKE_GENERATOR', 'CMAKE_TOOLCHAIN_FILE',
                'CMAKE_BUILD_PARALLEL_LEVEL', 'CCACHE_DIR', 'PYTHONHOME', 'PYTHONPATH', 'ABC', 'YOSYS_ABC', 'YOSYS_DATDIR'):
        env.pop(key, None)
    env['PATH'] = str(toolbin)+';'+str(msysbin)+';'+str(python.parent)+';'+env.get('PATH', '')
    temp = output/'tmp'
    temp.mkdir()
    env.update(TMP=str(temp), TEMP=str(temp), TMPDIR=str(temp), CCACHE_DISABLE='1')
    configs = {}
    for role in ('baseline', 'candidate'):
        run(cmake_command(tools, output, role), output/'records'/f'configure-{role}.log', env, output)
        configs[role] = audit_configuration(output, role)
        save_new(output/'records'/f'configured-{role}.json', configs[role])
    a, b = configs['baseline']['normalized_commands'], configs['candidate']['normalized_commands']
    require(set(b)-set(a) == {'passes/opt/pmux_competition_opt.cc'} and not set(a)-set(b), 'Unexpected compile-unit difference')
    require(all(a[name] == b[name] for name in a), 'Common compile flags differ between roles')
    save_new(output/'records/config-parity.json', {'status': 'PASS', 'common_commands': len(a),
             'candidate_added_unit': 'passes/opt/pmux_competition_opt.cc',
             'allowed_version_metadata_difference': 'Candidate checkout info has -dirty; both source origins identify the same verified commit.'})
    roles = {}
    # The rebuilt native EXEs share one directory, one ABC, DLLs and resources.
    # Upstream lookup uses the executable directory; no Yosys source changes.
    runtime_root = output/'roles'
    runtime_root.mkdir()
    for name in RUNTIME_NAMES:
        copy_new(package/name, runtime_root/name)
    shared_resources = {}
    for role in ('baseline', 'candidate'):
        build = output/'build'/role
        run([str(tools['cmake.exe']), '--build', str(build), '--target', 'yosys', '--parallel', str(args.jobs)],
            output/'records'/f'build-{role}.log', env, output)
        exe = runtime_root/f'yosys-{role}.exe'
        copy_new(build/'yosys.exe', exe)
        unstripped = sha(exe)
        run([str(tools['strip.exe']), str(exe)], output/'records'/f'strip-{role}.log', env, output)
        require((build/'share/intel').is_dir(), 'Build share data is missing')
        script = build/'share/intel/competition_abc_v11.abc'
        require(script.exists() == (role == 'candidate'), 'Wrong role share data')
        if role == 'candidate':
            require(sha(script) == manifest['script_sha256'], 'Packaged candidate ABC script differs')
        role_resources = {'share/'+name: digest for name, digest in inventory(build/'share').items()}
        for name, digest in role_resources.items():
            if name in shared_resources:
                require(shared_resources[name] == digest == sha(runtime_root/name), f'Conflicting rebuilt resources: {name}')
            else:
                copy_new(build/name, runtime_root/name)
                shared_resources[name] = digest
        role_files = {'yosys.exe': sha(exe), **runtime, **role_resources}
        roles[role] = {'files': role_files, 'file_origins': {name: f'yosys-{role}.exe' if name == 'yosys.exe' else name for name in role_files},
                       'unstripped_exe_sha256': unstripped,
                       'binary_bytes': exe.stat().st_size, 'executable_invocations': 0}
        require(audit_configuration(output, role) == configs[role], f'Build configuration changed: {role}')
    source_checks = {}
    for role in ('baseline', 'candidate'):
        expected = sources['source_inventories'][role]
        actual = inventory(output/'sources'/role)
        require(set(expected) <= set(actual), f'Original source paths removed during build: {role}')
        added = set(actual)-set(expected)
        require(added <= set(GENERATED_RESOURCES), f'Unapproved source paths added during build: {role}: {sorted(added-set(GENERATED_RESOURCES))}')
        changed = [name for name in expected if expected[name] != actual[name]]
        require(set(changed) <= {'.git/index'}, f'Non-index source changed during build: {role}: {changed}')
        index = (output/'sources'/role/'.git/index').read_bytes()
        require(hashlib.sha256(index_without_stat_cache(index)).hexdigest() == sources['index_nonstat_content_sha256'],
                f'Git index changed beyond stat-cache metadata: {role}')
        generated = verify_generated_resources(output, role, added, sources, configs[role], tools)
        source_checks[role] = {'status': 'PASS_ORIGINAL_SOURCES_INDEX_STAT_AND_THREE_VERIFIED_UPSTREAM_OUTPUTS', 'changed_paths': changed,
                              'index_prepared_sha256': expected['.git/index'], 'index_current_sha256': actual['.git/index'],
                              'all_other_files_byte_identical': len(expected)-1,
                              'index_paths_modes_objects_flags_extensions_unchanged': True,
                              'generated_upstream_resources': generated}
    for path, digest in frozen.items():
        require(sha(path) == digest, f'Delivered input changed during build: {path}')
    for name, desc in tool_records.items():
        require(sha(desc['path']) == desc['sha256'], f'Build tool changed during build: {name}')
    save_new(output/'records/build-result.json', {**record, 'status': 'BUILT_UNEXECUTED_VALIDATION_REQUIRED',
             'finished_utc': stamp(), 'roles': roles, 'shared_files': runtime,
             'package_layout': 'colocated_yosys_shared_runtime', 'shared_resources': shared_resources,
             'runtime_root': str(runtime_root), 'source_preservation_checks': source_checks,
             'delivered_inputs_unchanged': True,
             'config_parity': 'PASS', 'source_difference_files': sources['source_changed_files']})
    print(f'BUILT, NOT VALIDATED: {output}/roles. Rebuilt binaries have not been executed; retain new proof and performance evidence separately.')


if __name__ == '__main__':
    main()
