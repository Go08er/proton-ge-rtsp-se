#!/usr/bin/env python3
"""Fresh offline Wine configure/makedep red/green and five-module C compile.

Run inside the pinned SDK with only an owned scratch dependency tree writable.
The host supplies the checked prepared-to-generated source bridge, lock, image,
resource limits and network isolation. Retained config.logs supply argv only.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import signal
import stat
import subprocess
import time

from run import objects

ARCHES = ('x86_64', 'i386')
MODULES = tuple('dlls/' + name for name in
                ('mfreadwrite', 'winedmo', 'mfsrcsnk', 'mfmp4srcsnk', 'mfasfsrcsnk'))
REGISTRATION = b'\twine/mforigin.h \\\n'
GENERATED_PATHS = frozenset((
    'configure', 'dlls/icuin/icuin.spec', 'dlls/icuuc/icuuc.spec',
    'dlls/win32k.sys/win32k.sys.spec', 'dlls/ntdll/ntsyscalls.h',
    'dlls/win32u/win32syscalls.h', 'dlls/vulkan-1/vulkan-1.spec',
    'include/wine/vulkan.h', 'dlls/winevulkan/loader_thunks.c',
    'dlls/winevulkan/loader_thunks.h', 'dlls/winevulkan/vulkan_thunks.c',
    'dlls/winevulkan/vulkan_thunks.h', 'dlls/winevulkan/winevulkan.json',
    'dlls/winevulkan/winevulkan.spec'))


def digest(path):
    with Path(path).open('rb') as stream:
        value = hashlib.sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def source_digest(path, env):
    # Exactly scripts/hash-source-tree.sh's normalized_tar_sha256, including modes.
    command = ['tar', '--sort=name', '--format=gnu', '--mtime=@0', '--owner=0',
               '--group=0', '--numeric-owner', '--exclude=./.git', '-cf', '-', '.']
    process = subprocess.Popen(command, cwd=path, env=env, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE)
    value = hashlib.sha256()
    for block in iter(lambda: process.stdout.read(1024 * 1024), b''):
        value.update(block)
    error = process.stderr.read()
    if process.wait():
        raise ValueError('normalized source hash failed: ' + error.decode(errors='replace'))
    return value.hexdigest()


def configure_argv(text, scratch, arch):
    commands = [shlex.split(line.split('$ ', 1)[1]) for line in text.splitlines()
                if re.match(r'^\s*\$ .*configure(?:\s|$)', line)]
    if len(commands) != 1 or not commands[0] or Path(commands[0][0]).name != 'configure':
        raise ValueError('config.log must contain exactly one $ /absolute/src-wine/configure invocation')
    original = Path(commands[0][0])
    if not original.is_absolute() or original.parent.name != 'src-wine':
        raise ValueError('configure argv does not identify an absolute src-wine root')
    validate_architecture(commands[0], arch)
    old = str(original.parent.parent)
    remap = re.compile(re.escape(old) + r'(?=/|$)')
    result, skip = [], False
    for word in commands[0]:
        if skip:
            skip = False
            continue
        if word in ('-C', '--config-cache'):
            continue
        if word in ('--cache-file', '--with-wine-tools'):
            skip = True
            continue
        if word.startswith(('--cache-file=', '--with-wine-tools=')):
            continue
        result.append(remap.sub(str(scratch), word))
    if skip:
        raise ValueError('truncated configure option')
    result.append('--cache-file=/dev/null')
    if arch == 'i386':
        result.append('--with-wine-tools=' + str(scratch / 'fresh-green-x86_64'))
    elif arch != 'x86_64':
        raise ValueError('unsupported architecture')
    return result


def validate_architecture(command, arch):
    host = {'x86_64': 'x86_64-linux-gnu', 'i386': 'i686-linux-gnu'}.get(arch)
    if (host is None or [arg for arg in command if arg.startswith('--host=')] != ['--host=' + host]
            or [arg for arg in command if arg.startswith('CC=')] != ['CC=' + host + '-gcc']):
        raise ValueError('configure host/compiler do not match requested architecture: ' + arch)
    arches = [arg for arg in command if arg.startswith('--enable-archs=')]
    win64 = [arg for arg in command if arg.startswith(('--enable-win64', '--disable-win64'))]
    if ((arch == 'x86_64' and (arches != ['--enable-archs=x86_64'] or win64 != ['--enable-win64']))
            or (arch == 'i386' and (arches not in ([], ['--enable-archs=i386']) or win64))):
        raise ValueError('configure Wine architecture switches do not match: ' + arch)


def failing_inventory(data):
    if data.count(REGISTRATION) != 1 or data.count(b'wine/mforigin.h') != 1:
        raise ValueError('expected exactly one tab-indented wine/mforigin.h SOURCES registration')
    if b'SOURCES = \\\n' not in data:
        raise ValueError('unexpected include/Makefile.in SOURCES preimage')
    return data.replace(REGISTRATION, b'', 1)


def reproduced(log, actual_exit):
    return actual_exit > 0 and actual_exit != 124 and bool(re.search(
        r'error: wine/mforigin\.h: No such file or directory', log)) and (
        'config.status: error: could not create Makefile' in log)


def generated(build):
    return {name: digest(build / name) for name in
            ('Makefile', 'include/config.h', 'config.status') if (build / name).is_file()}


def run_command(command, cwd, output, name, env, timeout):
    (output / (name + '.command.json')).write_text(json.dumps(command, indent=2) + '\n')
    started = time.monotonic()
    with (output / (name + '.log')).open('wb') as log:
        child = subprocess.Popen(command, cwd=cwd, env=env, stdout=log,
                                 stderr=subprocess.STDOUT, start_new_session=True)
        timed_out = False
        try:
            actual_exit = child.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(child.pid, signal.SIGTERM)
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()
            actual_exit = 124
    result = dict(actual_exit=actual_exit, timed_out=timed_out,
                  elapsed_seconds=time.monotonic() - started,
                  command_sha256=digest(output / (name + '.command.json')),
                  log_sha256=digest(output / (name + '.log')))
    (output / (name + '.exit.json')).write_text(json.dumps(result, indent=2) + '\n')
    print(f'{name}: exit={actual_exit}', flush=True)
    return result


def verify_identity(identity, prepared, source, env):
    for name in ('source_hash', 'compiled_source_hash', 'series_digest', 'steamrt_image_id'):
        if not re.fullmatch(r'[0-9a-f]{64}', identity[name]):
            raise ValueError('invalid identity hash: ' + name)
    if not re.fullmatch(r'[a-zA-Z0-9_.-]+', identity['pin_id']):
        raise ValueError('invalid pin identity')
    if source_digest(prepared, env) != identity['source_hash']:
        raise ValueError('prepared-source digest differs from host identity')
    if source_digest(source, env) != identity['compiled_source_hash']:
        raise ValueError('scratch compiled-source digest differs from host identity')
    changes = source_bridge(prepared, source)
    if changes != identity['generated_source_changes']:
        raise ValueError('complete generated-source bridge differs from host identity')


def inventory_tree(root):
    """Complete file/symlink/mode map; exclude only root Git administration."""
    result = {}
    for directory, dirs, files in os.walk(root, followlinks=False):
        if Path(directory) == root:
            dirs[:] = [name for name in dirs if name != '.git']
            files = [name for name in files if name != '.git']
        for name in dirs + files:
            path = Path(directory) / name
            info = path.lstat()
            mode = stat.S_IMODE(info.st_mode)
            if stat.S_ISLNK(info.st_mode):
                row = ('link', mode, os.readlink(path))
            elif stat.S_ISREG(info.st_mode):
                row = ('file', mode, digest(path))
            elif stat.S_ISDIR(info.st_mode):
                row = ('dir', mode, None)
            else:
                raise ValueError('unsupported source filesystem entry: ' + str(path))
            result[str(path.relative_to(root))] = row
    return result


def source_bridge(prepared, source):
    before, after = inventory_tree(prepared), inventory_tree(source)
    changes = {}
    for name in sorted(before.keys() | after.keys()):
        left, right = before.get(name), after.get(name)
        if left == right:
            continue
        if (name not in GENERATED_PATHS or right is None or right[0] != 'file'
                or (left is not None and (left[0] != 'file' or left[1] != right[1]))):
            raise ValueError('non-generator source difference: ' + name)
        changes[name] = dict(prepared_sha256=left[2] if left else None,
                             compiled_sha256=right[2])
    return changes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scratch-root', required=True, type=Path)
    parser.add_argument('--prepared-source', required=True, type=Path)
    parser.add_argument('--config-log-x86_64', required=True, type=Path)
    parser.add_argument('--config-log-i386', required=True, type=Path)
    parser.add_argument('--identity', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--jobs', required=True, type=int, choices=range(1, 17))
    parser.add_argument('--configure-timeout', type=int, default=600)
    parser.add_argument('--compile-timeout', type=int, default=1200)
    args = parser.parse_args()
    scratch = args.scratch_root
    source = scratch / 'src-wine'
    if (not scratch.is_absolute() or scratch.resolve() != scratch or not source.is_dir()
            or source.is_symlink() or source.resolve() == args.prepared_source.resolve()):
        parser.error('scratch must be an explicit real directory containing an owned src-wine copy')
    if args.output.exists() or not (1 <= args.configure_timeout <= 1800
                                  and 1 <= args.compile_timeout <= 3600):
        parser.error('output must be fresh and timeouts bounded')
    builds = {name + '-' + arch: scratch / ('fresh-' + name + '-' + arch)
              for name in ('red', 'green') for arch in ARCHES}
    if any(path.exists() for path in builds.values()):
        parser.error('all four object directories must be absent; nothing is resumed')
    inventory = source / 'include/Makefile.in'
    if inventory.is_symlink() or inventory.stat().st_nlink != 1:
        parser.error('scratch include/Makefile.in must not be a symlink or shared hardlink')
    original = inventory.read_bytes()
    red = failing_inventory(original)
    timestamps = (inventory.stat().st_atime_ns, inventory.stat().st_mtime_ns)
    args.output.mkdir(parents=True, mode=0o700)
    env = {key: value for key, value in os.environ.items()
           if key not in ('MAKEFLAGS', 'MFLAGS', 'GNUMAKEFLAGS', 'TAR_OPTIONS', 'POSIXLY_CORRECT')
           and not key.startswith('PYTHON')}
    env.update(LC_ALL='C', CCACHE_DISABLE='1', WINEDEBUG='-all', PACKAGE_RELEASE='0')
    identity = json.loads(args.identity.read_text())
    if not Path(identity.get('compiled_source_path', '')).is_absolute():
        parser.error('identity must name the preserved absolute host compiled_source_path')
    result = dict(identity)
    result.update(schema=1, kind='wine-fresh-setup', status='INCOMPLETE', exit_status=80,
                  identity_sha256=digest(args.identity), container_source_path=str(source), stages={})

    def save():
        (args.output / 'results.json').write_text(json.dumps(result, indent=2) + '\n')

    def set_inventory(value):
        if inventory.read_bytes() not in (original, red):
            raise ValueError('scratch inventory changed unexpectedly; refusing overwrite')
        inventory.write_bytes(value)
        os.utime(inventory, ns=timestamps)

    try:
        verify_identity(identity, args.prepared_source, source, env)
        result['header_sha256'] = digest(source / 'include/wine/mforigin.h')
        result['corrected_inventory_sha256'] = hashlib.sha256(original).hexdigest()
        result['failing_inventory_sha256'] = hashlib.sha256(red).hexdigest()
        save()
        for arch in ARCHES:
            config_log = getattr(args, 'config_log_' + arch)
            command = configure_argv(config_log.read_text(), scratch, arch)
            for variant in ('red', 'green'):
                name = variant + '-' + arch
                build = builds[name]
                build.mkdir()  # Never copy config.cache, config.status, Makefile or objects.
                set_inventory(red if variant == 'red' else original)
                row = run_command(command, build, args.output, name, env, args.configure_timeout)
                row.update(fresh=True, object_dir=str(build),
                           argv_config_log_sha256=digest(config_log), generated=generated(build))
                if (build / 'config.log').is_file():
                    row['config_log_sha256'] = digest(build / 'config.log')
                if variant == 'red':
                    row['expected_failure'] = reproduced((args.output / (name + '.log')).read_text(
                        errors='replace'), row['actual_exit'])
                    passed = row['expected_failure']
                else:
                    passed = row['actual_exit'] == 0 and len(row['generated']) == 3
                result['stages'][name] = row
                save()
                if not passed:
                    raise RuntimeError(name + ': fresh generation did not produce the required result')
            if arch == 'x86_64' and not (builds['green-x86_64'] / 'tools/makedep').is_file():
                raise RuntimeError('fresh x86_64 configure did not produce makedep for i386')
        for arch in ARCHES:
            build = builds['green-' + arch]
            makefile = (build / 'Makefile').read_text()
            units = {module: objects(makefile, module) for module in MODULES}
            if any(not group for group in units.values()):
                raise RuntimeError('missing consumer C recipes: ' + arch)
            targets = [target for group in units.values() for target, _ in group]
            if len(targets) != len(set(targets)) or any((build / target).exists() for target in targets):
                raise RuntimeError('duplicate or pre-existing consumer object: ' + arch)
            for group in units.values():
                for _, filename in group:
                    if not Path(filename).resolve().is_relative_to(source):
                        raise RuntimeError('consumer recipe escaped candidate src-wine')
            name = 'compile-' + arch
            row = run_command(['make', '--no-print-directory', '-j' + str(args.jobs)] + targets,
                              build, args.output, name, env, args.compile_timeout)
            row.update(fresh=True, targets_from_regenerated_makefile=True,
                       object_dir=str(build), generated=generated(build), modules={})
            for module, group in units.items():
                row['modules'][module] = [dict(target=target, source_sha256=digest(filename),
                    object_sha256=digest(build / target) if (build / target).is_file() else None)
                    for target, filename in group]
            result['stages'][name] = row
            save()
            if row['actual_exit'] or any(not unit['object_sha256'] for group in row['modules'].values()
                                       for unit in group):
                raise RuntimeError(name + ': consumer compilation failed')
        result.update(status='PASS', exit_status=0)
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        result.update(status='FAIL', exit_status=1, error=str(error))
    finally:
        try:
            set_inventory(original)
            result['restored_compiled_source_hash'] = source_digest(source, env)
            if result['restored_compiled_source_hash'] != identity['compiled_source_hash']:
                raise RuntimeError('compiled source changed beyond the temporary inventory control')
        except (OSError, ValueError, KeyError, RuntimeError) as error:
            result.update(status='INCOMPLETE', exit_status=80, restoration_error=str(error))
        save()
    print(result['status'] + ': fresh configure/makedep and C objects only; no link/playback claim', flush=True)
    return result['exit_status']


if __name__ == '__main__':
    raise SystemExit(main())
