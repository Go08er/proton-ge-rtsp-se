#!/usr/bin/env python3
"""T0a/T0b: the artifact verifier's dual-DXVK payload and launcher expectations.

The verifier cannot run without a built artifact, so its two dual-DXVK blocks are
extracted from scripts/verify-pinned-ge-artifact.sh and run against synthetic
artifact trees (fabricated DLL bytes that carry, or lack, the identity strings).
Phase B runs the full verifier on the real build; this test keeps the expectations
themselves honest in the meantime. The launcher token list is checked against the
patched launcher (patch 0002 applied to the pinned GE launcher).
"""
from pathlib import Path
import re
import shutil
import tempfile
import unittest

from dxvk_legacy_common import LAUNCHER_PATCH, PIN, ROOT, git, local_ge_source, pin_values, run, shell

VERIFIER = (ROOT / 'scripts/verify-pinned-ge-artifact.sh').read_text()
PIN_ENV = pin_values()
COMMIT = PIN_ENV['PIN_DXVK_LEGACY_COMMIT']
TAG = PIN_ENV['PIN_DXVK_LEGACY_VERSION_TAG']
SHORT = TAG.rsplit('-g', 1)[0] + '-g' + COMMIT[:8]
PRIMARY_TAG = 'v3.1.1-174-gf8637768'
DLLS = ('d3d8', 'd3d9', 'd3d10core', 'd3d11', 'dxgi', 'openvr_api_dxvk')


def payload_block():
    start = VERIFIER.index('if pinned_ge_dxvk_legacy_enabled; then\n  # Dual DXVK payload')
    end = VERIFIER.index('\ninternal_pattern=', start)
    return VERIFIER[start:end]


def token_list():
    match = re.search(r"  dxvk-legacy\)\n    launcher_policy_tokens=\(\n(.*?)\n    \)\n", VERIFIER, re.S)
    return [t.strip()[1:-1] for t in match.group(1).splitlines()]


class ArtifactPayload(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='rtsp-dxvk-legacy-artifact-')
        self.addCleanup(temp.cleanup)
        self.tool = Path(temp.name) / 'tool'
        for variant, tag, other in (('dxvk', PRIMARY_TAG + '0682448-GE-Proton(dirty)', None),
                                    ('dxvk-legacy', TAG, None)):
            for arch in ('i386', 'x86_64'):
                directory = self.tool / 'files/lib/wine' / variant / (arch + '-windows')
                directory.mkdir(parents=True)
                for dll in DLLS:
                    if dll == 'openvr_api_dxvk':
                        data = b'MZ openvr ' + arch.encode()
                    else:
                        data = ('MZ %s %s %s\0' % (variant, dll, tag if dll in ('d3d11', 'dxgi') else 'x')).encode()
                    (directory / (dll + '.dll')).write_bytes(data)
        (self.tool / 'files/lib/wine/dxvk/version').write_text(
            ' f863776806824486d709fee16ea619c03e22def4 dxvk (%s)\n' % PRIMARY_TAG)
        (self.tool / 'files/lib/wine/dxvk-legacy/version').write_text(' %s dxvk (%s)\n' % (COMMIT, SHORT))

    def verify(self):
        script = ('pinned_ge_dxvk_legacy_enabled || exit 3\nTOOL_DIR="$3"\n' + payload_block() + '\necho PAYLOAD-OK\n')
        return shell(PIN, script, self.tool)

    def test_complete_payload_passes(self):
        result = self.verify()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('PAYLOAD-OK', result.stdout)

    def rejected(self, fragment):
        result = self.verify()
        self.assertNotEqual(result.returncode, 0, 'accepted a bad payload')
        self.assertIn(fragment, result.stderr)

    def test_missing_legacy_directory_or_file_is_rejected(self):
        shutil.rmtree(self.tool / 'files/lib/wine/dxvk-legacy')
        self.assertNotEqual(self.verify().returncode, 0)

    def test_each_expected_file_is_required(self):
        for arch in ('i386', 'x86_64'):
            for dll in DLLS:
                path = self.tool / 'files/lib/wine/dxvk-legacy' / (arch + '-windows') / (dll + '.dll')
                data = path.read_bytes()
                path.unlink()
                with self.subTest(file=f'{arch}/{dll}'):
                    self.rejected('dual DXVK payload is incomplete: %s-windows/%s.dll' % (arch, dll))
                path.write_bytes(data)

    def test_version_file_must_be_exact(self):
        for text in ('', ' %s dxvk (%s)' % (COMMIT, SHORT), ' %s dxvk (v3.1.1-174-gf8637768)\n' % COMMIT,
                     ' %s dxvk (%s)\n' % ('0' * 40, SHORT), ' %s dxvk (%s)\n\n' % (COMMIT, SHORT)):
            (self.tool / 'files/lib/wine/dxvk-legacy/version').write_text(text)
            with self.subTest(text=text):
                self.rejected('legacy DXVK version file does not carry the pinned identity')

    def test_openvr_copies_must_be_equal(self):
        path = self.tool / 'files/lib/wine/dxvk-legacy/x86_64-windows/openvr_api_dxvk.dll'
        path.write_bytes(b'different')
        self.rejected('legacy and primary openvr_api_dxvk.dll differ (x86_64)')

    def test_identity_strings_are_required(self):
        for arch in ('i386', 'x86_64'):
            for dll in ('d3d11', 'dxgi'):
                path = self.tool / 'files/lib/wine/dxvk-legacy' / (arch + '-windows') / (dll + '.dll')
                good = path.read_bytes()
                for label, bad in (('no tag', b'MZ nothing\0'), ('GE tag', good + b'-GE-Proton(dirty)\0')):
                    path.write_bytes(bad)
                    with self.subTest(file=f'{arch}/{dll}', case=label):
                        self.rejected('identity strings are wrong in %s-windows/%s.dll' % (arch, dll))
                path.write_bytes(good)
                primary = self.tool / 'files/lib/wine/dxvk' / (arch + '-windows') / (dll + '.dll')
                primary_good = primary.read_bytes()
                for label, bad in (('primary lacks its tag', b'MZ nothing\0'), ('primary has the legacy tag', primary_good + TAG.encode())):
                    primary.write_bytes(bad)
                    with self.subTest(file=f'{arch}/{dll}', case=label):
                        self.assertNotEqual(self.verify().returncode, 0)
                primary.write_bytes(primary_good)

    def test_identical_d3d11_in_both_directories_is_rejected(self):
        for arch in ('i386', 'x86_64'):
            shutil.copy2(self.tool / 'files/lib/wine/dxvk' / (arch + '-windows/d3d11.dll'),
                         self.tool / 'files/lib/wine/dxvk-legacy' / (arch + '-windows/d3d11.dll'))
            with self.subTest(arch=arch):
                self.rejected('legacy and primary d3d11.dll are identical (%s)' % arch)
            (self.tool / 'files/lib/wine/dxvk-legacy' / (arch + '-windows/d3d11.dll')).write_bytes(
                ('MZ dxvk-legacy d3d11 %s\0' % TAG).encode())

    def test_primary_version_must_be_a_distinct_dxvk_build(self):
        (self.tool / 'files/lib/wine/dxvk/version').write_text(' %s dxvk (%s)\n' % (COMMIT, SHORT))
        self.rejected('primary DXVK version file is not a distinct DXVK build')

    def test_artifact_is_expected_to_carry_the_dual_provenance_lines(self):
        for line in ('"DXVK legacy commit: $PIN_DXVK_LEGACY_COMMIT"',
                     '"DXVK legacy build-module SHA-256: $PIN_DXVK_LEGACY_MAKEFILE_PATCH_SHA256"'):
            self.assertIn(line, VERIFIER)
        builder = (ROOT / 'scripts/build-pinned-ge.sh').read_text()
        for line in ("'DXVK legacy commit: %s\\n'", "'DXVK legacy source SHA-256: %s\\n'",
                     "'DXVK legacy build-module SHA-256: %s\\n'"):
            self.assertIn(line, builder)


class LauncherTokens(unittest.TestCase):
    @unittest.skipIf(local_ge_source() is None, 'no local checkout with the pinned GE launcher')
    def test_token_list_discriminates_the_patched_launcher_from_the_stock_one(self):
        source = local_ge_source()
        tokens = token_list()
        self.assertGreaterEqual(len(tokens), 8)
        with tempfile.TemporaryDirectory(prefix='rtsp-dxvk-legacy-tokens-') as tmp:
            work = Path(tmp)
            git(work, 'init', '-q')
            stock = git(source, 'show', PIN_ENV['PIN_SOURCE_COMMIT'] + ':proton').stdout
            (work / 'proton').write_text(stock)
            git(work, 'apply', str(LAUNCHER_PATCH))
            patched = (work / 'proton').read_text()
        for token in tokens:
            with self.subTest(token=token):
                self.assertIn(token, patched)
                self.assertNotIn(token, stock)
        # The XRizer token list of the other carried-patch policy must not be satisfied by this launcher.
        self.assertNotIn('PROTON_XR_MODE', patched)


if __name__ == '__main__':
    unittest.main(verbosity=2)
