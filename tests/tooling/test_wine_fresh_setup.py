#!/usr/bin/env python3
"""Synthetic receipt controls; no compiler, Wine, network or production bypass."""
import copy
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'scripts/verify-wine-fresh-setup.py'
spec = importlib.util.spec_from_file_location('fresh_setup', SCRIPT)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def synthetic_receipt(source_hash, compiled_source_path):
    receipt = dict(schema=1, kind='wine-fresh-setup', status='PASS', exit_status=0,
                   pin_id='test-pin', source_hash=source_hash, series_digest='a' * 64,
                   steamrt_image_id='b' * 64, stages={}, compiled_source_hash=source_hash,
                   restored_compiled_source_hash=source_hash, compiled_source_path=str(compiled_source_path),
                   generated_source_changes={})
    for arch in gate.ARCHES:
        for phase in ('red', 'green', 'compile'):
            stage = dict(actual_exit=1 if phase == 'red' else 0, fresh=True,
                         object_dir=f'/synthetic/{phase}-{arch}', timed_out=False,
                         command_sha256='1' * 64, log_sha256='2' * 64)
            if phase == 'red':
                stage['expected_failure'] = True
            if phase != 'compile':
                stage['config_log_sha256'] = 'c' * 64
                stage['argv_config_log_sha256'] = '3' * 64
            if phase in ('green', 'compile'):
                stage['generated'] = {name: 'd' * 64 for name in
                                      ('Makefile', 'include/config.h', 'config.status')}
            if phase == 'compile':
                stage['object_dir'] = f'/synthetic/green-{arch}'
                stage['targets_from_regenerated_makefile'] = True
                stage['modules'] = {name: [dict(target=f'{name}/test.o', source_sha256='e' * 64,
                                               object_sha256='f' * 64)] for name in gate.MODULES}
            receipt['stages'][f'{phase}-{arch}'] = stage
    return receipt


class FreshSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='wine-fresh-receipt-')
        self.addCleanup(self.temp.cleanup)
        self.tree = Path(self.temp.name) / 'wine'
        self.tree.mkdir()
        (self.tree / 'input.h').write_text('/* synthetic source, not Wine */\n')
        self.compiled = Path(self.temp.name) / 'compiled'
        shutil.copytree(self.tree, self.compiled)
        self.receipt = synthetic_receipt(gate.source_hash(self.tree), self.compiled)
        self.expected = {key: self.receipt[key] for key in
                         ('pin_id', 'source_hash', 'series_digest', 'steamrt_image_id')}

    def test_complete_receipt(self):
        gate.verify(self.receipt, self.expected)
        gate.verify_source_bridge(self.receipt, self.tree)

    def test_compiled_source_bridge_and_non_generator_change(self):
        (self.compiled / 'input.h').write_text('/* wrong product source */\n')
        with self.assertRaisesRegex(gate.ReceiptError, 'content changed'):
            gate.verify_source_bridge(self.receipt, self.tree)
        self.receipt['compiled_source_hash'] = gate.source_hash(self.compiled)
        with self.assertRaisesRegex(ValueError, 'non-generator'):
            gate.verify_source_bridge(self.receipt, self.tree)

    def test_generated_source_bridge_must_be_complete(self):
        (self.compiled / 'configure').write_text('# synthetic generated configure\n')
        self.receipt['compiled_source_hash'] = gate.source_hash(self.compiled)
        with self.assertRaisesRegex(gate.ReceiptError, 'bridge differs'):
            gate.verify_source_bridge(self.receipt, self.tree)
        self.receipt['generated_source_changes'] = gate.source_bridge(self.tree, self.compiled)
        gate.verify_source_bridge(self.receipt, self.tree)

    def test_wrong_consumer_or_old_makefile_rejected(self):
        mutations = (
            lambda row: row['modules']['dlls/winedmo'][0].update(target='dlls/other/one.o'),
            lambda row: row.update(object_dir='/old/retained'),
            lambda row: row.update(targets_from_regenerated_makefile=False),
            lambda row: row['generated'].update(Makefile='0' * 64),
        )
        for mutation in mutations:
            mutated = copy.deepcopy(self.receipt)
            mutation(mutated['stages']['compile-i386'])
            with self.assertRaises(gate.ReceiptError):
                gate.verify(mutated, self.expected)

    def test_stale_source_pin_series_or_sdk_rejected(self):
        for key in self.expected:
            mutated = copy.deepcopy(self.receipt)
            mutated[key] = 'wrong' if key == 'pin_id' else '0' * 64
            with self.subTest(key=key), self.assertRaises(gate.ReceiptError):
                gate.verify(mutated, self.expected)

    def test_missing_architecture_and_stage_rejected(self):
        for key in self.receipt['stages']:
            mutated = copy.deepcopy(self.receipt)
            del mutated['stages'][key]
            with self.subTest(stage=key), self.assertRaises(gate.ReceiptError):
                gate.verify(mutated, self.expected)
        mutated = copy.deepcopy(self.receipt)
        mutated['stages']['green-aarch64'] = mutated['stages'].pop('green-i386')
        with self.assertRaises(gate.ReceiptError):
            gate.verify(mutated, self.expected)

    def test_failed_nonfresh_or_wrong_red_control_rejected(self):
        for key in self.receipt['stages']:
            for field, value in (('actual_exit', 0 if key.startswith('red-') else 1), ('fresh', False)):
                mutated = copy.deepcopy(self.receipt)
                mutated['stages'][key][field] = value
                with self.subTest(stage=key, field=field), self.assertRaises(gate.ReceiptError):
                    gate.verify(mutated, self.expected)
        mutated = copy.deepcopy(self.receipt)
        mutated['stages']['red-i386']['expected_failure'] = False
        with self.assertRaises(gate.ReceiptError):
            gate.verify(mutated, self.expected)
        for code in (-9, 124):
            mutated = copy.deepcopy(self.receipt)
            mutated['stages']['red-i386']['actual_exit'] = code
            with self.assertRaises(gate.ReceiptError):
                gate.verify(mutated, self.expected)

    def test_missing_generated_files_or_consumer_objects_rejected(self):
        for arch in gate.ARCHES:
            for path in (('green-' + arch, 'generated', 'Makefile'),
                         ('compile-' + arch, 'modules', 'dlls/mfsrcsnk')):
                mutated = copy.deepcopy(self.receipt)
                del mutated['stages'][path[0]][path[1]][path[2]]
                with self.subTest(path=path), self.assertRaises(gate.ReceiptError):
                    gate.verify(mutated, self.expected)
            mutated = copy.deepcopy(self.receipt)
            mutated['stages']['compile-' + arch]['modules']['dlls/mfreadwrite'] = []
            with self.assertRaises(gate.ReceiptError):
                gate.verify(mutated, self.expected)

    def test_cli_missing_receipt_and_changed_actual_tree(self):
        path = Path(self.temp.name) / 'receipt.json'
        command = [sys.executable, str(SCRIPT), '--receipt', str(path), '--wine-tree', str(self.tree),
                   '--pin-id', 'test-pin', '--series-digest', 'a' * 64, '--steamrt-image-id', 'b' * 64]
        missing = subprocess.run(command, capture_output=True, text=True, timeout=30)
        self.assertEqual(missing.returncode, 1)
        self.assertIn('fresh configure/makedep', missing.stderr)
        path.write_text(json.dumps(self.receipt))
        good = subprocess.run(command, capture_output=True, text=True, timeout=30)
        self.assertEqual(good.returncode, 0, good.stderr)
        (self.tree / 'input.h').write_text('/* changed */\n')
        stale = subprocess.run(command, capture_output=True, text=True, timeout=30)
        self.assertEqual(stale.returncode, 1)
        self.assertIn('source_hash', stale.stderr)


if __name__ == '__main__':
    unittest.main(verbosity=2)
