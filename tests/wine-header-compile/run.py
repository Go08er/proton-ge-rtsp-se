#!/usr/bin/env python3
"""Compile real Wine C objects in an isolated configured build COPY, not redist.

Run inside the same offline SDK used for the retained configuration. Mount only
the scratch copy at its original configured path. Never mount the original
build writable. This gate compiles every C object of each named module; it does
not link a complete Proton artifact or substitute for runtime qualification.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess


def objects(makefile, module):
    # Actual generated rules, including native Unix and architecture PE C.
    pattern = rf'^{re.escape(module)}/[^ :]+\.o: ([^\n]+\.c)\n'
    return [(m[0].split(':', 1)[0], m[1])
            for m in re.finditer(pattern, makefile, re.M)]


def compile_command(dry_run, target):
    matches = []
    for line in dry_run.replace('\\\n', ' ').splitlines():
        words = shlex.split(line)
        if '-c' in words and '-o' in words and words[words.index('-o')+1] == target:
            matches.append(words)
    if len(matches) != 1:
        raise ValueError(f'Expected one real compiler command for {target}, got {len(matches)}')
    return matches[0]


def domains(text):
    # GCC -dD keeps enum declarations and macro definitions in expansion order.
    names = ('INCOMPLETE', 'SYNC_POINT', 'DISCONTINUITY')
    macros = {}
    enums = {}
    for name in names:
        token = 'WINEDMO_SAMPLE_FLAG_' + name
        macro = re.search(r'^#define '+token+r'\s+(0x[0-9a-fA-F]+|\d+)\b', text, re.M)
        enum = re.search(r'\b'+token+r'\s*=\s*(0x[0-9a-fA-F]+|\d+)\b', text)
        if macro:
            macros[name] = int(macro[1], 0)
        if enum:
            enums[name] = int(enum[1], 0)
    return dict(public_macros=macros, private_enum=enums,
                sees_both=bool(macros and enums))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-copy', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--module', action='append', default=[])
    parser.add_argument('--negative', action='store_true', help='reproduce P16 main.c collision, not a pass')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('output must be fresh')
    modules = args.module or ['dlls/winedmo']
    if any(not re.fullmatch(r'dlls/[a-zA-Z0-9_.-]+', m) for m in modules):
        parser.error('only explicit Wine DLL modules are accepted')
    args.output.mkdir(parents=True, mode=0o700)
    results = []
    for arch in ('x86_64', 'i386'):
        build = args.build_copy / ('obj-wine-' + arch)
        makefile = (build/'Makefile').read_text()
        configured = dict(makefile_sha256=hashlib.sha256(makefile.encode()).hexdigest(),
                          config_sha256=hashlib.sha256((build/'include/config.h').read_bytes()).hexdigest())
        for module in modules:
            units = objects(makefile, module)
            if args.negative:
                units = [(o, s) for o, s in units if o == f'{module}/{arch}-windows/main.o']
            if not units:
                raise ValueError(f'No configured C objects: {arch} {module}')
            for target, source in units:
                stem = arch + '-' + target.replace('/', '_')
                dry = subprocess.run(['make', '--no-print-directory', '-n', '-o', 'Makefile',
                                      '-W', source, target], cwd=build, text=True, capture_output=True)
                if dry.returncode:
                    raise RuntimeError(dry.stdout+dry.stderr)
                command = compile_command(dry.stdout, target)
                (args.output/(stem+'.command.json')).write_text(json.dumps(command)+'\n')
                (build/target).parent.mkdir(parents=True, exist_ok=True)
                with (args.output/(stem+'.log')).open('w') as log:
                    result = subprocess.run(command, cwd=build, stdout=log, stderr=subprocess.STDOUT)
                row = dict(architecture=arch, module=module, target=target, source=source,
                           source_sha256=hashlib.sha256((build / source).read_bytes()).hexdigest(),
                           configured=configured, compile_exit=result.returncode)
                if args.negative:
                    error = (args.output/(stem+'.log')).read_text()
                    row['negative_reproduced'] = result.returncode != 0 and (
                        'expected identifier before numeric constant' in error and
                        'WINEDMO_SAMPLE_FLAG_INCOMPLETE' in error)
                elif result.returncode == 0:
                    pre = command.copy()
                    index = pre.index('-o')
                    del pre[index:index+2]
                    pre.remove('-c')
                    pre += ['-E', '-dD']
                    expanded = subprocess.run(pre, cwd=build, text=True, capture_output=True)
                    if expanded.returncode:
                        raise RuntimeError(expanded.stderr)
                    row.update(domains(expanded.stdout))
                    row['object_sha256'] = hashlib.sha256((build/target).read_bytes()).hexdigest()
                results.append(row)
                (args.output/'results.json').write_text(json.dumps(results, indent=2)+'\n')
                print(arch, target, 'compile_exit='+str(result.returncode), flush=True)
                if not args.negative and result.returncode:
                    return 1
    passed = all(r.get('negative_reproduced', False) for r in results) if args.negative else all(r['compile_exit']==0 for r in results)
    print(('REPRODUCED expected P16 failure' if args.negative else 'PASS real-header C compilation')
          + f': {len(results)} objects; not link/runtime qualification', flush=True)
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
