#!/usr/bin/env python3
"""Exercise optional AV1 build-patch provenance without preparing/building GE.

Copies SE1's crypto-patched Makefile into a disposable directory and supplies
synthetic preparation audit records to the real validator. No container/network.
"""

import argparse
import hashlib
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = None
OLD_PIN = ROOT / 'config/ge-proton11-6-se1.env'
NEW_PIN = ROOT / 'config/ge-proton11-6-se2-p1.env'


def pin_values(path):
    return dict(line.split('=', 1) for line in path.read_text().splitlines()
                if line.startswith('PIN_'))


def shell(config, script, *args):
    return subprocess.run(['bash', '-eu', '-c',
        'source "$1/scripts/pinned-ge-common.sh"; PINNED_GE_CONFIG="$2"; pinned_ge_load_config; ' + script,
        'dav1d-test', str(ROOT), str(config), *map(str, args)],
        text=True, capture_output=True)


def tsv(path, records):
    path.write_text(''.join(f'{key}\t{value}\n' for key, value in records.items()))


class Dav1dBuildModule(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='rtsp-dav1d-provenance-')
        self.addCleanup(temp.cleanup)
        self.temp = Path(temp.name)
        self.source = self.temp / 'source'
        self.state = self.temp / 'state'
        self.source.mkdir()
        self.state.mkdir()
        shutil.copy2(SOURCE / 'Makefile.in', self.source / 'Makefile.in')
        self.pin = pin_values(NEW_PIN)
        digest = shell(OLD_PIN, 'pinned_ge_series_digest "$1/patches/ffmpeg-build" "$1/patches/ffmpeg-build/series"')
        self.assertEqual(digest.returncode, 0, digest.stderr)
        self.series_digest = digest.stdout.strip()
        self.audit = {
            'ffmpeg_crypto_build_audit_version': '1',
            'source_commit': self.pin['PIN_SOURCE_COMMIT'],
            'patch_origin': self.pin['PIN_FFMPEG_CRYPTO_BUILD_ORIGIN'],
            'patch_path': 'patches/ffmpeg-build/0001-ffmpeg-enable-crypto-protocol-for-AES-128-HLS.patch',
            'patch_sha256': self.pin['PIN_FFMPEG_CRYPTO_BUILD_PATCH_SHA256'],
            'series_sha256': self.pin['PIN_FFMPEG_CRYPTO_BUILD_SERIES_SHA256'],
            'series_digest': self.series_digest,
            'touched_path': 'Makefile.in',
            'final_makefile_blob': self.pin['PIN_FFMPEG_CRYPTO_BUILD_MAKEFILE_BLOB'],
            'crypto_enable_count': '1',
            'application': 'passed',
        }
        self.write_records()

    def write_records(self):
        audit_path = self.state / 'ffmpeg-crypto-build-audit.tsv'
        tsv(audit_path, self.audit)
        tsv(self.state / 'prepared-source.tsv', {
            'ffmpeg_crypto_build_origin': self.audit['patch_origin'],
            'ffmpeg_crypto_build_patch_sha256': self.audit['patch_sha256'],
            'ffmpeg_crypto_build_series_sha256': self.audit['series_sha256'],
            'ffmpeg_crypto_build_series_digest': self.audit['series_digest'],
            'ffmpeg_crypto_build_audit_sha256': hashlib.sha256(audit_path.read_bytes()).hexdigest(),
            'ffmpeg_crypto_build_makefile_blob': self.audit['final_makefile_blob'],
        })

    def apply_module(self):
        result = shell(NEW_PIN,
            'pinned_ge_git -C "$3" apply --whitespace=error-all -- "$(pinned_ge_dav1d_build_patch)"',
            self.source)
        self.assertEqual(result.returncode, 0, result.stderr)

    def validate(self, config=NEW_PIN):
        return shell(config, 'pinned_ge_require_prepared_ffmpeg_crypto_build_provenance "$3" "$4"',
                     self.source, self.state)

    def test_old_pin_still_accepts_crypto_only(self):
        result = self.validate(OLD_PIN)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_new_pin_requires_module_and_preserves_crypto_intermediate(self):
        self.assertNotEqual(self.validate().returncode, 0)
        self.apply_module()
        result = self.validate()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotEqual(self.validate(OLD_PIN).returncode, 0)
        self.assertNotEqual(self.pin['PIN_FFMPEG_DAV1D_MAKEFILE_BLOB'], self.audit['final_makefile_blob'])

    def test_crypto_removal_and_unrelated_changes_rejected(self):
        self.apply_module()
        makefile = self.source / 'Makefile.in'
        original = makefile.read_text()
        for bad in (original.replace('\t--enable-protocol=crypto \\\n', ''), original + '# unrelated\n'):
            makefile.write_text(bad)
            self.assertNotEqual(self.validate().returncode, 0)

    def test_cannot_relabel_crypto_audit_as_combined_result(self):
        self.apply_module()
        self.audit['final_makefile_blob'] = self.pin['PIN_FFMPEG_DAV1D_MAKEFILE_BLOB']
        self.write_records()
        self.assertNotEqual(self.validate().returncode, 0)

    def test_optional_pair_must_be_complete_and_cannot_leak_between_loads(self):
        partial = self.temp / 'partial.env'
        partial.write_text('\n'.join(line for line in NEW_PIN.read_text().splitlines()
                                    if not line.startswith('PIN_FFMPEG_DAV1D_PATCH_SHA256=')) + '\n')
        self.assertNotEqual(shell(partial, ':').returncode, 0)
        result = shell(NEW_PIN,
            'PINNED_GE_CONFIG="$3"; pinned_ge_load_config; test -z "${PIN_FFMPEG_DAV1D_PATCH_SHA256:-}"', OLD_PIN)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_changed_module_hash_is_rejected(self):
        result = shell(NEW_PIN, 'PIN_FFMPEG_DAV1D_PATCH_SHA256=' + '0' * 64 + '; pinned_ge_dav1d_build_patch')
        self.assertNotEqual(result.returncode, 0)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    args = parser.parse_args()
    SOURCE = args.source.resolve(strict=True)
    unittest.main(argv=[__file__], verbosity=2)
