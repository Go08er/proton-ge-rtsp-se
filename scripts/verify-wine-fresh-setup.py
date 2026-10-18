#!/usr/bin/env python3
"""Require the two-architecture fresh Wine generation/consumer receipt before a build.

This checks local recorded evidence, not playback or cryptographic attestation.
The source binding hashes the actual prepared tree, including ignored files,
using the same normalized GNU-tar method as hash-source-tree.sh.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
# Reuse the producer's complete file/mode/symlink comparison and fixed GE
# generator allowlist, rather than introduce a second interpretation.
sys.path.insert(0, str(ROOT / 'tests/wine-header-compile'))
from fresh_setup import source_bridge
ARCHES = ('x86_64', 'i386')
MODULES = {'dlls/' + name for name in
           ('mfreadwrite', 'winedmo', 'mfsrcsnk', 'mfmp4srcsnk', 'mfasfsrcsnk')}


class ReceiptError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise ReceiptError(message)


def digest(value):
    return isinstance(value, str) and bool(re.fullmatch('[0-9a-f]{64}', value))


def source_hash(tree):
    result = subprocess.run(['bash', str(ROOT / 'scripts/hash-source-tree.sh'),
                             '--tree', str(tree)], capture_output=True, text=True, timeout=300)
    require(result.returncode == 0, 'could not hash the prepared Wine tree: ' + result.stderr.strip())
    hashes = [line.split('\t')[1] for line in result.stdout.splitlines()
              if line.startswith('normalized_tar_sha256\t')]
    require(len(hashes) == 1 and digest(hashes[0]), 'source-tree hash output is incomplete')
    return hashes[0]


def verify(receipt, expected):
    require(receipt.get('schema') == 1 and receipt.get('kind') == 'wine-fresh-setup',
            'not a supported wine-fresh-setup receipt')
    require(receipt.get('status') == 'PASS' and type(receipt.get('exit_status')) is int
            and receipt['exit_status'] == 0, 'fresh setup did not complete successfully')
    for key, value in expected.items():
        require(receipt.get(key) == value, f'stale or mismatched {key}')
    require(digest(receipt.get('compiled_source_hash'))
            and receipt.get('restored_compiled_source_hash') == receipt['compiled_source_hash'],
            'missing or unrestored compiled-source identity')
    require(isinstance(receipt.get('compiled_source_path'), str)
            and Path(receipt['compiled_source_path']).is_absolute()
            and isinstance(receipt.get('generated_source_changes'), dict),
            'missing preserved compiled-source path/generation bridge')
    stages = receipt.get('stages', {})
    require(isinstance(stages, dict) and set(stages) ==
            {f'{phase}-{arch}' for phase in ('red', 'green', 'compile') for arch in ARCHES},
            'both x86_64 and i386 red/green/compile stages are required')
    for arch in ARCHES:
        for phase in ('red', 'green', 'compile'):
            stage = stages[f'{phase}-{arch}']
            require(isinstance(stage, dict) and stage.get('fresh') is True,
                    f'{phase}-{arch}: not a fresh setup/consumer compile')
            code = stage.get('actual_exit')
            require(type(code) is int and (code > 0 and code != 124 if phase == 'red' else code == 0),
                    f'{phase}-{arch}: wrong or absent exit status')
            require(stage.get('timed_out') is False and digest(stage.get('command_sha256'))
                    and digest(stage.get('log_sha256')), f'{phase}-{arch}: incomplete command evidence')
            require(isinstance(stage.get('object_dir'), str) and bool(stage['object_dir']),
                    f'{phase}-{arch}: missing object directory')
            if phase == 'red':
                require(stage.get('expected_failure') is True,
                        f'red-{arch}: missing exact header-registration failure witness')
            if phase != 'compile':
                require(digest(stage.get('config_log_sha256')) and digest(stage.get('argv_config_log_sha256')),
                        f'{phase}-{arch}: missing config.log hash')
            if phase == 'green':
                generated = stage.get('generated', {})
                require(isinstance(generated, dict) and all(digest(generated.get(name)) for name in
                        ('Makefile', 'include/config.h', 'config.status')),
                        f'green-{arch}: missing freshly generated build files')
            if phase == 'compile':
                green = stages[f'green-{arch}']
                require(stage['object_dir'] == green['object_dir']
                        and stage.get('generated') == green.get('generated')
                        and stage.get('targets_from_regenerated_makefile') is True,
                        f'compile-{arch}: consumer targets not bound to the regenerated Makefile')
                modules = stage.get('modules', {})
                require(isinstance(modules, dict) and set(modules) == MODULES,
                        f'compile-{arch}: all five header consumers are required')
                targets = set()
                for module, objects in modules.items():
                    require(isinstance(objects, list) and bool(objects),
                            f'compile-{arch}: no compiled objects for {module}')
                    for obj in objects:
                        require(isinstance(obj, dict) and isinstance(obj.get('target'), str)
                                and obj['target'].startswith(module + '/') and obj['target'].endswith('.o')
                                and '..' not in Path(obj['target']).parts and obj['target'] not in targets
                                and digest(obj.get('source_sha256')) and digest(obj.get('object_sha256')),
                                f'compile-{arch}: missing/duplicate object or source hash for {module}')
                        targets.add(obj['target'])
        require(stages[f'red-{arch}']['argv_config_log_sha256'] ==
                stages[f'green-{arch}']['argv_config_log_sha256'],
                f'{arch}: red/green configure arguments came from different templates')
    directories = [stages[f'{phase}-{arch}']['object_dir']
                   for phase in ('red', 'green') for arch in ARCHES]
    require(len(set(directories)) == 4, 'red/green architectures reused an object directory')


def verify_source_bridge(receipt, prepared):
    compiled = Path(receipt['compiled_source_path'])
    require(compiled.is_dir() and compiled.resolve() != prepared.resolve(),
            'preserved compiled-source copy is missing or is the prepared tree')
    require(source_hash(compiled) == receipt['compiled_source_hash'], 'compiled source content changed')
    require(source_bridge(prepared, compiled) == receipt['generated_source_changes'],
            'complete generated-source bridge differs from the receipt')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receipt', type=Path, required=True)
    parser.add_argument('--wine-tree', type=Path, required=True)
    parser.add_argument('--pin-id', required=True)
    parser.add_argument('--series-digest', required=True)
    parser.add_argument('--steamrt-image-id', required=True)
    args = parser.parse_args()
    try:
        require(args.receipt.is_file() and not args.receipt.is_symlink(),
                'missing regular receipt; run the fresh configure/makedep and consumer gate first, '
                'then supply --fresh-setup-receipt FILE to build-pinned-ge.sh')
        require(digest(args.series_digest) and digest(args.steamrt_image_id), 'invalid expected identity')
        data = args.receipt.read_bytes()
        receipt = json.loads(data)
        require(isinstance(receipt, dict), 'receipt must be an object')
        verify(receipt, dict(pin_id=args.pin_id, source_hash=source_hash(args.wine_tree),
                             series_digest=args.series_digest, steamrt_image_id=args.steamrt_image_id))
        verify_source_bridge(receipt, args.wine_tree)
        print('Fresh Wine setup: PASS (x86_64 + i386, five consumers each); receipt SHA-256 '
              + hashlib.sha256(data).hexdigest())
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(f'ERROR: fresh Wine setup: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
