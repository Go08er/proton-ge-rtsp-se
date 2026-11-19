#!/usr/bin/env python3
"""T12: the pin's whole Makefile.in module chain, including the dxvk-legacy module, on a fresh GE clone.

Pattern: test_ffmpeg_http_chunkend.py (apply the pin's modules to a fresh clone) and
test_mpegvideo_build_module.py. The fresh clone is a --shared --no-checkout clone of a
local checkout that holds the pinned GE commit; only Makefile.in is checked out.
Every intermediate blob is compared with the pin, then the final blob with
PIN_DXVK_LEGACY_MAKEFILE_BLOB. No build, no network.
"""
from pathlib import Path
import re
import shutil
import tempfile
import unittest

from dxvk_legacy_common import (MAKEFILE_PATCH, PIN, ROOT, git, local_ge_source, pin_values, pin_with, run, shell)

REFERENCE = local_ge_source()
PIN_ENV = pin_values()
STATE_SOURCE = ROOT / 'work/ge-proton11-12-se4-p6'
P6_PIN = ROOT / 'config/ge-proton11-12-se4-p6.env'


def blob(repo):
    return git(repo, 'hash-object', '--no-filters', 'Makefile.in').stdout.strip()


@unittest.skipIf(REFERENCE is None, 'no local checkout holding the pinned GE commit')
class DxvkLegacyBuildModule(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='rtsp-dxvk-legacy-module-')
        self.addCleanup(temp.cleanup)
        self.tmp = Path(temp.name)

    def fresh_clone(self, name='fresh'):
        clone = self.tmp / name
        run('git', 'clone', '--shared', '--no-checkout', '--no-tags', '--quiet', REFERENCE, clone, check=True)
        git(clone, 'checkout', '--quiet', PIN_ENV['PIN_SOURCE_COMMIT'], '--', 'Makefile.in')
        return clone

    def chain(self):
        """(label, patch path, expected blob) for every Makefile.in module of the pin, in order."""
        crypto = shell(PIN, 'pinned_ge_ffmpeg_crypto_build_patch_record "$3/patches/ffmpeg-build" '
                            '"$(pinned_ge_ffmpeg_crypto_build_series)"', ROOT).stdout.split('\t')[0]
        return [
            ('crypto', ROOT / 'patches/ffmpeg-build' / crypto, PIN_ENV['PIN_FFMPEG_CRYPTO_BUILD_MAKEFILE_BLOB']),
            ('mpegvideo', ROOT / 'patches/proposed/ffmpeg-enable-mpeg-video-parser.patch',
             PIN_ENV['PIN_FFMPEG_MPEGVIDEO_MAKEFILE_BLOB']),
            ('aac', ROOT / 'patches/proposed/ffmpeg-enable-aac-parser.patch',
             PIN_ENV['PIN_FFMPEG_AAC_PARSER_MAKEFILE_BLOB']),
            ('dxvk-legacy', MAKEFILE_PATCH, PIN_ENV['PIN_DXVK_LEGACY_MAKEFILE_BLOB']),
        ]

    def test_module_chain_blob_by_blob_on_a_fresh_clone(self):
        clone = self.fresh_clone()
        self.assertEqual(blob(clone), 'e4039398d2c95f8b63455e2081f165ed2456fee9')  # GE-Proton11-12's Makefile.in
        for label, patch, expected in self.chain():
            with self.subTest(module=label):
                git(clone, 'apply', '--check', '--whitespace=error-all', patch)
                git(clone, 'apply', '--whitespace=error-all', patch)
                self.assertEqual(blob(clone), expected)
        self.assertEqual(blob(clone), PIN_ENV['PIN_DXVK_LEGACY_MAKEFILE_BLOB'])
        # The scripts' notion of the final blob is the legacy blob, the FFmpeg one stays the AAC blob.
        self.assertEqual(shell(PIN, 'pinned_ge_final_makefile_blob').stdout.strip(),
                         PIN_ENV['PIN_DXVK_LEGACY_MAKEFILE_BLOB'])
        self.assertEqual(shell(PIN, 'pinned_ge_ffmpeg_final_makefile_blob').stdout.strip(),
                         PIN_ENV['PIN_FFMPEG_AAC_PARSER_MAKEFILE_BLOB'])
        self.assertEqual(shell(P6_PIN, 'pinned_ge_final_makefile_blob').stdout.strip(),
                         'fcf554c93afb1e3f13173909d74273cfee58ee19')

    def test_module_is_a_pure_addition_that_never_touches_the_primary_dxvk(self):
        patch = MAKEFILE_PATCH.read_text()
        body = patch[patch.index('\ndiff --git'):]
        removed = [l for l in body.splitlines() if l.startswith('-') and not l.startswith('---')]
        self.assertEqual(removed, [])
        self.assertEqual(re.findall(r'^diff --git (.*)$', body, re.M), ['a/Makefile.in b/Makefile.in'])
        added = '\n'.join(l[1:] for l in body.splitlines() if l.startswith('+') and not l.startswith('+++'))
        self.assertNotIn('arm64ec', added.replace('No arm64ec', ''))
        self.assertNotRegex(added, r'wine/dxvk/(?!-)')

    def test_module_carries_the_pinned_identity(self):
        added = MAKEFILE_PATCH.read_text()
        commit, tag = PIN_ENV['PIN_DXVK_LEGACY_COMMIT'], PIN_ENV['PIN_DXVK_LEGACY_VERSION_TAG']
        self.assertIn("s#@VCS_TAG@#%s#" % tag, added)
        # DESIGN 2.4 / Beta4 version-file text: " <commit> dxvk (<tag with an 8-digit abbreviation>)".
        short = tag.rsplit('-g', 1)[0] + '-g' + commit[:8]
        self.assertIn('echo " %s dxvk (%s)" > $(DST_LIBDIR)/wine/dxvk-legacy/version' % (commit, short), added)
        for rule in ('rules-source,dxvk-legacy,$(SRCDIR)/dxvk-legacy/dxvk', 'rules-meson,dxvk-legacy,i386,windows',
                     'rules-meson,dxvk-legacy,x86_64,windows', 'default_pfx: dxvk-legacy',
                     'DXVK_LEGACY_i386_MESON_ARGS = --bindir=$(DXVK_LEGACY_i386_DST)/lib/wine/dxvk-legacy/i386-windows',
                     'DXVK_LEGACY_x86_64_MESON_ARGS = --bindir=$(DXVK_LEGACY_x86_64_DST)/lib/wine/dxvk-legacy/x86_64-windows',
                     'OVR_LEGACY_i386_DIST := $(DST_LIBDIR)/wine/dxvk-legacy/i386-windows/openvr_api_dxvk.dll',
                     'OVR_LEGACY_x86_64_DIST := $(DST_LIBDIR)/wine/dxvk-legacy/x86_64-windows/openvr_api_dxvk.dll',
                     'DXVK_LEGACY_SOURCE_ARGS', '--exclude version.h.in'):
            self.assertIn(rule, added)
        self.assertNotIn('ge-dirty-tag', added.split('\n---\n', 1)[1])
        for epoch in ('i386', 'x86_64'):
            self.assertIn('DXVK_LEGACY_%s_SOURCE_DATE_EPOCH := $(shell expr $(%s_SOURCE_DATE_EPOCH) - 3)' % (epoch, epoch), added)

    # -- the pin binds the module -------------------------------------------
    def test_changed_patch_or_pin_values_are_rejected(self):
        self.assertEqual(shell(PIN, 'pinned_ge_dxvk_legacy_makefile_patch').returncode, 0)
        bad = shell(PIN, 'PIN_DXVK_LEGACY_MAKEFILE_PATCH_SHA256=' + '0' * 64 + '; pinned_ge_dxvk_legacy_makefile_patch')
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn('dxvk-legacy build patch differs from the selected pin', bad.stderr)
        clone = self.fresh_clone()
        for _, patch, _ in self.chain()[:3]:
            git(clone, 'apply', '--whitespace=error-all', patch)
        tampered = self.tmp / 'tampered.patch'
        tampered.write_text(MAKEFILE_PATCH.read_text().replace('- 3)', '- 4)', 1))
        git(clone, 'apply', '--whitespace=error-all', tampered)
        self.assertNotEqual(blob(clone), PIN_ENV['PIN_DXVK_LEGACY_MAKEFILE_BLOB'])

    def test_keys_and_policy_come_together(self):
        for key in ('PIN_DXVK_LEGACY_COMMIT', 'PIN_DXVK_LEGACY_MAKEFILE_BLOB', 'PIN_DXVK_LEGACY_NESTED'):
            config = pin_with(self.tmp, 'drop-%s.env' % key, drop=(key,))
            with self.subTest(dropped=key):
                result = shell(config, ':')
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('dual DXVK requires launcher policy dxvk-legacy', result.stderr)
        upstream = pin_with(self.tmp, 'upstream.env', [('PIN_PROTON_LAUNCHER_POLICY=', 'PIN_PROTON_LAUNCHER_POLICY=upstream')])
        self.assertNotEqual(shell(upstream, ':').returncode, 0)
        for name, old, new in (('tag', 'PIN_DXVK_LEGACY_VERSION_TAG=', 'PIN_DXVK_LEGACY_VERSION_TAG=v2.7.1-668-g0000000000000aa'),
                               ('sha', 'PIN_DXVK_LEGACY_TREE_SHA256=', 'PIN_DXVK_LEGACY_TREE_SHA256=xyz'),
                               ('nested', 'PIN_DXVK_LEGACY_NESTED=', 'PIN_DXVK_LEGACY_NESTED=../escape:%s:%s' % ('a' * 40, 'b' * 40))):
            with self.subTest(malformed=name):
                self.assertNotEqual(shell(pin_with(self.tmp, name + '.env', [(old, new)]), ':').returncode, 0)

    # -- provenance chain (the AAC/MPEGVIDEO/dav1d peel now starts with the new module) --------------
    def provenance(self, config, source, state):
        return shell(config, 'pinned_ge_require_prepared_ffmpeg_crypto_build_provenance "$3" "$4"', source, state)

    @unittest.skipUnless(STATE_SOURCE.is_dir(), 'retained SE4-P6 state is not present')
    def test_prepared_provenance_peels_the_new_module_first(self):
        state = self.tmp / 'state'
        state.mkdir()
        for name in ('ffmpeg-crypto-build-audit.tsv', 'prepared-source.tsv'):
            shutil.copy2(STATE_SOURCE / name, state / name)
        source = self.tmp / 'prepared'
        source.mkdir()
        git(source, 'init', '-q')
        clone = self.fresh_clone()
        shutil.copy2(clone / 'Makefile.in', source / 'Makefile.in')
        chain = self.chain()
        for _, patch, _ in chain[:3]:
            git(source, 'apply', '--whitespace=error-all', patch)
        # The FFmpeg-final Makefile is the final one for SE4-P6, and not for SE4-P7.
        self.assertEqual(self.provenance(P6_PIN, source, state).returncode, 0)
        self.assertNotEqual(self.provenance(PIN, source, state).returncode, 0)
        git(source, 'apply', '--whitespace=error-all', MAKEFILE_PATCH)
        result = self.provenance(PIN, source, state)
        self.assertEqual(result.returncode, 0, result.stderr)
        # ... and the other way round.
        self.assertNotEqual(self.provenance(P6_PIN, source, state).returncode, 0)
        # An unrelated edit on top of the legacy module is rejected.
        (source / 'Makefile.in').write_text((source / 'Makefile.in').read_text() + '# unrelated change\n')
        self.assertNotEqual(self.provenance(PIN, source, state).returncode, 0)
        self.assertEqual(list(Path(source).glob('*.orig')), [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
