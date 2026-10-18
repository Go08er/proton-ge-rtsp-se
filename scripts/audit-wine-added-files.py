#!/usr/bin/env python3
"""Check added-file registration in an explicitly selected, applied Wine series.

This is an inventory check, not a substitute for fresh configure/makedep and
consumer links. In particular it cannot infer required DLL imports from C.
Rules follow tools/makedep.c: global headers and generator inputs use SOURCES;
ordinary DLL specs may be selected implicitly by MODULE. Unmodelled routes
(including unlisted private-header dependencies) fail with a review request.
No patch is applied and no tree/configuration is changed.
"""
import argparse
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys


class AuditError(ValueError):
    pass


def relative(name):
    path = PurePosixPath(name)
    if (not name or path.is_absolute() or str(path) != name
            or '..' in path.parts or re.search(r'[^A-Za-z0-9_./+\-]', name)):
        raise AuditError(f'unsupported or unsafe path: {name!r}')
    return path


def read_file(root, name):
    path = root / relative(name)
    if not path.resolve().is_relative_to(root.resolve()) or not path.is_file():
        raise AuditError(f'missing/non-local file: {name}')
    return path


def added_files(series, patch_root):
    """Use Git's read-only parser, including plain --- /dev/null patches."""
    added, count, seen = {}, 0, set()
    for line in series.read_text().splitlines():
        name = line.split('#', 1)[0].strip()
        if not name:
            continue
        if name in seen:
            raise AuditError(f'duplicate series entry: {name}')
        seen.add(name)
        patch = read_file(patch_root, name)
        result = subprocess.run(
            ['git', 'apply', '--summary', str(patch.resolve())], text=True,
            capture_output=True, timeout=30,
            env=dict(os.environ, GIT_NO_LAZY_FETCH='1', GIT_ALLOW_PROTOCOL='file'))
        if result.returncode:
            raise AuditError(f'{name}: invalid patch: {result.stderr.strip()}')
        count += 1
        for summary in result.stdout.splitlines():
            match = re.fullmatch(r' (create|delete)(?: mode ([0-7]+))? (.+)', summary)
            if match:
                action, mode, path = match.groups()
                relative(path)
                if action == 'create':
                    if mode not in (None, '100644', '100755'):
                        raise AuditError(f'{name}: unsupported added file mode {mode}: {path}')
                    added[path] = name
                else:
                    added.pop(path, None)
            elif summary.startswith(' mode change '):
                continue
            else:
                raise AuditError(f'{name}: unsupported patch summary: {summary.strip()}')
    if not count:
        raise AuditError('empty patch series')
    return count, added


def make_variables(path):
    # makedep set_make_variable accepts '=' (not GNU make += or :=).
    text = re.sub(r'\\\r?\n', ' ', path.read_text())
    variables = {}
    for line in text.splitlines():
        if line.startswith('\t'):
            continue
        match = re.fullmatch(r'\s*([A-Za-z0-9_]+)\s*=\s*(.*?)\s*', line.split('#', 1)[0])
        if match:
            variables[match[1]] = match[2].split()
    return variables


def literal(variables, name):
    words = variables.get(name, [])
    if any('$' in word or '@' in word for word in words):
        raise AuditError(f'{name}: computed registration needs explicit audit support')
    return words


def registration(tree, name):
    read_file(tree, name)
    path = relative(name)
    # Global include lookup is explicitly inventory based, even for subdirs.
    directory = PurePosixPath('include') if path.parts[0] == 'include' else path.parent
    make_name = str(directory / 'Makefile.in')
    make = read_file(tree, make_name)
    configured = read_file(tree, 'configure.ac').read_text()
    if not re.search(r'^\s*WINE_CONFIG_MAKEFILE\(\s*' + re.escape(str(directory))
                     + r'\s*\)\s*$', configured, re.MULTILINE):
        raise AuditError(f'{make_name}: not explicitly registered in configure.ac')
    variables = make_variables(make)
    local = str(path.relative_to(directory))
    # These are input files; e.g. an IDL-generated header need not be listed,
    # but its added .idl input must be. Never bless a checked-in generated
    # output merely because a similarly named generator exists.
    kinds = {'.h', '.rh', '.in', '.c', '.m', '.S', '.s', '.idl', '.rc', '.y', '.l', '.spec'}
    if path.suffix not in kinds:
        raise AuditError(f'{name}: unsupported added-file category; review its build route')
    sources = literal(variables, 'SOURCES')
    if local in sources:
        return f'{make_name}: SOURCES={local}'
    if path.suffix == '.spec' and directory != PurePosixPath('include'):
        module = literal(variables, 'MODULE')
        flags = literal(variables, 'EXTRADLLFLAGS')
        # output_module uses ordinary foo.dll -> foo.spec without SOURCES.
        # Data/native/driver and auxiliary import specs use other routes.
        if (len(module) == 1 and module[0].endswith('.dll')
                and local == module[0][:-4] + '.spec'
                and not {'-Wb,--data-only', '-Wl,--subsystem,native', '-mconsole', '-mwindows'} & set(flags)):
            imports = literal(variables, 'IMPORTLIB')
            return f'{make_name}: MODULE={module[0]}; IMPORTLIB={",".join(imports) or "none"}'
    hint = 'register the input in SOURCES'
    if path.suffix == '.h' and directory != PurePosixPath('include'):
        hint = 'unlisted private headers need a dependency-route review (not guessed registration)'
    raise AuditError(f'{name}: absent from {make_name} SOURCES; {hint}')


def audit(tree, series, patch_root):
    count, added = added_files(series, patch_root)
    rows, errors = [], []
    for path, patch in sorted(added.items()):
        try:
            rows.append((path, patch, registration(tree, path)))
        except (AuditError, OSError) as error:
            errors.append(f'{patch}: {error}')
    return count, rows, errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wine-tree', type=Path, required=True)
    parser.add_argument('--series', type=Path, required=True)
    parser.add_argument('--patch-root', type=Path, required=True)
    args = parser.parse_args()
    try:
        count, rows, errors = audit(args.wine_tree, args.series, args.patch_root)
        for path, patch, route in rows:
            print(f'PASS\t{path}\t{patch}\t{route}')
        for error in errors:
            print(f'ERROR: {error}', file=sys.stderr)
        print(f'Added-file registration: {count} patches, {len(rows)} registered, {len(errors)} rejected')
        return bool(errors)
    except (AuditError, OSError, subprocess.SubprocessError) as error:
        print(f'ERROR: added-file registration: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
