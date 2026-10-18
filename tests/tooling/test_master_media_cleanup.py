#!/usr/bin/env python3
"""Exercise both exact media-cleanup manifest policies in tiny offline trees."""

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import test_media_provenance as provenance

ROOT = Path(__file__).resolve().parents[2]
PATHS = ('dlls/winegstreamer/main.c',
         'dlls/winegstreamer/media-converter/videoconv.c',
         'dlls/winegstreamer/wg_parser.c')
UPSTREAM = 'patches/ge-video-rework/0001-winedmo-remove-winegstreamer-media-backend.patch'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class MediaCleanupTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='rtsp-master-media-cleanup.')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source'
        self.wine = self.source / 'wine'
        for path in (self.root / 'scripts', self.root / 'config', self.root / 'state',
                     self.source / Path(UPSTREAM).parent, self.wine):
            path.mkdir(parents=True, exist_ok=True)
        for name in ('normalize-pinned-ge-media-cleanup.sh', 'pinned-ge-common.sh'):
            shutil.copyfile(ROOT / 'scripts' / name, self.root / 'scripts' / name)
        self.git('init', '-q')
        for index, name in enumerate(PATHS):
            path = self.wine / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f'/* dormant fixture {index} */\n')
        (self.wine / 'source.c').write_text('/* active fixture */\n')
        self.git('add', '.')
        self.git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@invalid',
                 'commit', '-qm', 'exact cleanup fixture')
        self.commit = self.git('rev-parse', 'HEAD').strip()
        self.manifest = self.root / 'config/cleanup.tsv'
        self.config = self.root / 'config/fixture.env'
        self.audit = self.root / 'state/cleanup-audit.tsv'
        self.upstream = self.source / UPSTREAM
        self.deletions = [(name, self.git('rev-parse', 'HEAD:' + name).strip(), sha(self.wine / name))
                          for name in PATHS]
        self.write_manifest()

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.wine), *args], text=True,
            env={**os.environ, 'GIT_NO_LAZY_FETCH': '1', 'GIT_ALLOW_PROTOCOL': 'file'})

    def pin_manifest(self):
        # Copy data only into this temporary fixture; never edit the retained pin.
        updates = {'PIN_GE_MEDIA_CLEANUP_MANIFEST': 'config/cleanup.tsv',
                   'PIN_GE_MEDIA_CLEANUP_MANIFEST_SHA256': sha(self.manifest),
                   'PIN_SOURCE_COMMIT': self.commit}
        lines = (ROOT / 'config/ge-proton11-6-se2-p7.env').read_text().splitlines()
        self.config.write_text('\n'.join(
            line.split('=', 1)[0] + '=' + updates[line.split('=', 1)[0]]
            if line.split('=', 1)[0] in updates else line for line in lines) + '\n')

    def write_manifest(self, version=2, advertised=False, body=''):
        self.upstream.write_text('Subject: fixture removal\n' + ''.join(
            f' delete mode 100644 {name}\n' for name in PATHS if advertised) + body)
        self.manifest.write_text(
            f'media_cleanup_version\t{version}\nsource_commit\t{self.commit}\n'
            f'upstream_patch\t{UPSTREAM}\nupstream_patch_sha256\t{sha(self.upstream)}\n'
            + ''.join(f'delete\t{name}\t{blob}\t{digest}\n' for name, blob, digest in self.deletions))
        self.pin_manifest()

    def run_cleanup(self):
        return subprocess.run(['bash', str(self.root / 'scripts/normalize-pinned-ge-media-cleanup.sh')],
            cwd=self.wine, text=True, capture_output=True, timeout=10,
            env={**os.environ, 'PINNED_GE_CONFIG': str(self.config),
                 'RTSP_GE_SOURCE_ROOT': str(self.source), 'RTSP_GE_MEDIA_CLEANUP_AUDIT': str(self.audit),
                 'GIT_NO_LAZY_FETCH': '1', 'GIT_ALLOW_PROTOCOL': 'file', 'WINEDEBUG': '-all', 'PACKAGE_RELEASE': '0'})

    def assert_rejected(self, text, before_delete=True):
        result = self.run_cleanup()
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(text, result.stderr)
        self.assertFalse(self.audit.exists(), 'a rejection must not publish a successful audit')
        if before_delete:
            self.assertTrue(all((self.wine / name).exists() for name in PATHS))

    def assert_cleaned(self):
        result = self.run_cleanup()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(all(not (self.wine / name).exists() for name in PATHS))
        audit = self.audit.read_text()
        self.assertIn('media_cleanup_audit_version\t1\n', audit)
        self.assertIn('manifest_sha256\t' + sha(self.manifest) + '\n', audit)
        self.assertEqual(sum(line.startswith('deleted\t') for line in audit.splitlines()), 3)
        self.assertIn('remaining_non_evidence_winegstreamer_files\t0\n', audit)
        self.assertIn('media_cleanup\tpassed\n', audit)

    def test_v1_advertised_omissions_still_pass(self):
        self.write_manifest(version=1, advertised=True)
        self.assert_cleaned()

    def test_v1_missing_advertisement_still_fails(self):
        self.write_manifest(version=1)
        self.assert_rejected('does not advertise exactly one deletion')

    def test_v2_unadvertised_exact_omissions_pass(self):
        self.assert_cleaned()

    def test_v2_unexpected_advertisement_fails(self):
        self.write_manifest(advertised=True)
        self.assert_rejected('expects an unadvertised omission')

    def test_both_versions_reject_real_diff_body(self):
        for version in (1, 2):
            with self.subTest(version=version):
                path = PATHS[0]
                self.write_manifest(version=version, advertised=version == 1,
                                    body=f'diff --git a/{path} b/{path}\n')
                self.assert_rejected('contains a real diff body')

    def test_wrong_manifest_hash_fails(self):
        self.manifest.write_text(self.manifest.read_text() + '\n')
        self.assert_rejected('manifest differs from its pinned digest')

    def test_wrong_upstream_hash_fails(self):
        self.upstream.write_text('changed upstream patch\n')
        self.assert_rejected('patch differs from the cleanup manifest')

    def test_wrong_base_blob_fails(self):
        name, _, digest = self.deletions[0]
        self.deletions[0] = (name, '0' * 40, digest)
        self.write_manifest()
        self.assert_rejected('base blob changed')

    def test_changed_working_file_fails(self):
        (self.wine / PATHS[0]).write_text('unexpected source edit\n')
        self.assert_rejected('GE patching modified a media-cleanup path')

    def test_wrong_content_hash_fails(self):
        name, blob, _ = self.deletions[0]
        self.deletions[0] = (name, blob, '0' * 64)
        self.write_manifest()
        self.assert_rejected('content digest changed')

    def test_external_reference_fails_before_deleting(self):
        (self.wine / 'source.c').write_text('/* still using winegstreamer */\n')
        self.assert_rejected('still referenced outside its dormant source directory')

    def test_unreviewed_v2_path_fails(self):
        _, blob, digest = self.deletions[0]
        self.deletions[0] = ('dlls/winegstreamer/unreviewed.c', blob, digest)
        self.write_manifest()
        self.assert_rejected('unreviewed version-2 media-cleanup path')

    def test_survivor_proof_remains_required(self):
        (self.wine / 'dlls/winegstreamer/survivor.c').write_text('unexpected survivor\n')
        self.assert_rejected('source survived pinned cleanup', before_delete=False)


class ManifestVersionProvenanceTests(unittest.TestCase):
    def check_version(self, version):
        fixture = provenance.SelectedSeriesTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        old_sha = sha(fixture.manifest)
        fixture.manifest.write_text(fixture.manifest.read_text().replace(
            'media_cleanup_version\t1\n', f'media_cleanup_version\t{version}\n'))
        new_sha = sha(fixture.manifest)
        cleanup = fixture.state / 'ge-media-cleanup-audit.tsv'
        cleanup.write_text(cleanup.read_text().replace(old_sha, new_sha))
        fixture.audit_values['ge_media_cleanup_normalization_digest'] = new_sha
        fixture.state_values['ge_media_cleanup_normalization_digest'] = new_sha
        fixture.state_values['ge_media_cleanup_audit_sha256'] = sha(cleanup)
        fixture.write_evidence()
        return fixture.check(fixture.archived)

    def test_prepared_provenance_accepts_version2(self):
        result = self.check_version(2)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_prepared_provenance_rejects_unknown_version(self):
        result = self.check_version(3)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('unsupported GE media-cleanup manifest version', result.stderr)


if __name__ == '__main__':
    unittest.main(verbosity=2)
