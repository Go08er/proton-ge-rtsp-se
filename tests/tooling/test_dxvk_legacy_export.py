#!/usr/bin/env python3
"""Legacy DXVK source export (T0c negatives, the exclude/clean question, T13 offline form).

The fixtures clone the dxvk object stores of a local checkout that already holds
the pinned commits (shared clones; the checkout itself is only read). Nothing is
fetched from a network.
"""
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from dxvk_legacy_common import (EXPORT, GIT_ENV, ROOT, git, local_ge_source, make_fixture, pin_values,
                                pin_with, run, shell)

REFERENCE = local_ge_source()
PIN_ENV = pin_values()
DIGEST = PIN_ENV['PIN_DXVK_LEGACY_TREE_SHA256']


def export(source, *extra, config=None, env=None):
    return run('bash', EXPORT, '--source', source, '--config', config or ROOT / 'config/ge-proton11-12-se4-p7.env',
               *extra, cwd=ROOT, env=env)


@unittest.skipIf(REFERENCE is None, 'no local checkout holding the pinned DXVK stores')
class DxvkLegacyExport(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='rtsp-dxvk-legacy-export-')
        self.addCleanup(temp.cleanup)
        self.tmp = Path(temp.name)

    def fixture(self, **kw):
        parent = Path(tempfile.mkdtemp(dir=self.tmp))
        return make_fixture(parent, REFERENCE, **kw)

    def ok(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    # -- the exported tree -------------------------------------------------
    def test_export_matches_the_pinned_digest_and_layout(self):
        source = self.fixture()
        result = export(source)
        self.ok(result)
        self.assertEqual(result.stdout.strip(), 'dxvk_legacy_source_sha256\t' + DIGEST)
        tree = source / 'dxvk-legacy'
        self.assertEqual(sorted(p.name for p in tree.iterdir()), ['dxvk'])
        for path in ('dxvk/meson.build', 'dxvk/version.h.in', 'dxvk/subprojects/dxbc-spirv/meson.build',
                     'dxvk/subprojects/dxbc-spirv/submodules/spirv_headers/include',
                     'dxvk/subprojects/libdisplay-info/meson.build', 'dxvk/include/vulkan/include',
                     'dxvk/include/spirv/include', 'dxvk/include/native/directx'):
            self.assertTrue((tree / path).exists(), path)
        self.assertFalse(list(tree.rglob('.git')), 'the exported tree must carry no .git')
        files = sum(len(f) for _, _, f in os.walk(tree))
        self.assertEqual(files, 582 + 163 + 110 + 75 + 88 + 113 + 66)

    def test_export_is_deterministic_across_umask_and_user_git_config(self):
        source_a, source_b = self.fixture(), self.fixture()
        config = self.tmp / 'gitconfig'
        config.write_text('[core]\n\tautocrlf = true\n\teol = crlf\n[tar]\n\tumask = 0077\n')
        env_b = {**GIT_ENV, 'GIT_CONFIG_GLOBAL': str(config), 'HOME': str(self.tmp)}
        self.ok(export(source_a))
        old = os.umask(0o077)
        try:
            self.ok(export(source_b, env=env_b))
        finally:
            os.umask(old)
        for source in (source_a, source_b):
            self.assertEqual(shell(ROOT / 'config/ge-proton11-12-se4-p7.env',
                                   'pinned_ge_dxvk_legacy_source_digest "$3/dxvk-legacy"', source
                                   ).stdout.strip(), DIGEST)

    def test_fresh_materialization_form_without_any_extra_fetch(self):
        # T13, offline form: full non-shared copies of the registered stores, made the way the
        # submodule materializer makes them (clone --local --no-hardlinks --no-checkout), already
        # hold every legacy commit; the export needs nothing else.
        source = self.fixture(local=True)
        self.assertFalse(list(source.glob('dxvk/**/objects/info/alternates')))
        result = export(source, env={**GIT_ENV, 'GIT_ALLOW_PROTOCOL': 'none'})
        self.ok(result)
        self.assertIn(DIGEST, result.stdout)

    # -- the exclude / clean-root question ---------------------------------
    def state_digest(self, source):
        return shell(ROOT / 'config/ge-proton11-12-se4-p7.env', 'pinned_ge_repo_state_digest "$3"', source)

    def test_root_state_digest_treats_the_excluded_export_as_clean(self):
        source = self.fixture()
        before = self.state_digest(source)
        self.ok(before)
        self.ok(export(source))
        exclude = git(source, 'rev-parse', '--git-path', 'info/exclude').stdout.strip()
        self.assertIn('/dxvk-legacy/', (source / exclude).read_text().splitlines())
        after = self.state_digest(source)
        self.ok(after)
        self.assertEqual(before.stdout, after.stdout)
        self.assertEqual(git(source, 'status', '--porcelain', '--untracked-files=all', '--ignore-submodules=all').stdout, '')
        # Without the exclude line the very same tree is visible and changes the digest.
        (source / exclude).write_text('')
        visible = self.state_digest(source)
        self.ok(visible)
        self.assertNotEqual(before.stdout, visible.stdout)

    def test_exclude_entry_is_idempotent_and_not_added_by_a_scratch_dest(self):
        source = self.fixture()
        exclude = source / git(source, 'rev-parse', '--git-path', 'info/exclude').stdout.strip()
        self.ok(export(source, '--dest', self.tmp / 'scratch-dest'))
        self.assertFalse(exclude.exists() and '/dxvk-legacy/' in exclude.read_text())
        self.ok(export(source))
        shell(ROOT / 'config/ge-proton11-12-se4-p7.env', 'pinned_ge_dxvk_legacy_ensure_excluded "$3"', source)
        self.assertEqual(exclude.read_text().splitlines().count('/dxvk-legacy/'), 1)

    # -- T0c negatives -----------------------------------------------------
    def rejected(self, result, fragment):
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(fragment, result.stderr)

    def test_wrong_nested_tree_id_is_rejected(self):
        source = self.fixture()
        for index, entry in enumerate(PIN_ENV['PIN_DXVK_LEGACY_NESTED'].split(',')):
            path, commit, tree = entry.split(':')
            wrong = ('0' if tree[0] != '0' else '1') + tree[1:]
            config = pin_with(self.tmp, 'wrong-tree-%d.env' % index,
                              [('PIN_DXVK_LEGACY_NESTED=', 'PIN_DXVK_LEGACY_NESTED=' +
                                PIN_ENV['PIN_DXVK_LEGACY_NESTED'].replace(entry, ':'.join((path, commit, wrong))))])
            with self.subTest(path=path):
                self.rejected(export(source, '--dest', self.tmp / ('d%d' % index), config=config),
                              'legacy DXVK tree of dxvk/%s is' % path)
                self.assertFalse((self.tmp / ('d%d' % index)).exists())

    def test_wrong_root_tree_id_is_rejected(self):
        config = pin_with(self.tmp, 'wrong-root.env', [('PIN_DXVK_LEGACY_TREE=', 'PIN_DXVK_LEGACY_TREE=' + '1' * 40)])
        self.rejected(export(self.fixture(), '--dest', self.tmp / 'd', config=config),
                      'legacy DXVK tree of dxvk/. is')

    def test_nested_commit_that_the_parent_does_not_pin_is_rejected(self):
        # vulkan headers at the commit P6's DXVK pins instead: a real commit with its real tree,
        # but not the gitlink the legacy DXVK commit records.
        source = self.fixture()
        other = git(source / 'dxvk/include/vulkan', 'rev-parse', 'HEAD').stdout.strip()
        tree = git(source / 'dxvk/include/vulkan', 'rev-parse', other + '^{tree}').stdout.strip()
        old = next(e for e in PIN_ENV['PIN_DXVK_LEGACY_NESTED'].split(',') if e.startswith('include/vulkan:'))
        config = pin_with(self.tmp, 'wrong-gitlink.env',
                          [('PIN_DXVK_LEGACY_NESTED=', 'PIN_DXVK_LEGACY_NESTED=' +
                            PIN_ENV['PIN_DXVK_LEGACY_NESTED'].replace(old, 'include/vulkan:%s:%s' % (other, tree)))])
        self.rejected(export(source, '--dest', self.tmp / 'd', config=config),
                      'not the gitlink pinned by its parent legacy commit')

    def test_missing_commit_in_a_shallow_store_is_rejected(self):
        for path in ('dxvk', 'dxvk/subprojects/dxbc-spirv', 'dxvk/include/vulkan'):
            with self.subTest(store=path):
                source = self.fixture(shallow=(path,))
                self.rejected(export(source), 'is absent from the store')
                self.assertFalse((source / 'dxvk-legacy').exists())

    def test_absent_store_is_rejected(self):
        source = self.fixture(omit=('dxvk/subprojects/libdisplay-info',))
        self.rejected(export(source), 'legacy DXVK store is absent: dxvk/subprojects/libdisplay-info')

    def test_existing_destination_is_refused(self):
        source = self.fixture()
        self.ok(export(source))
        self.rejected(export(source), 'destination exists')

    def test_tampered_exported_tree_does_not_match_the_pin_or_the_state(self):
        source = self.fixture()
        self.ok(export(source))
        config = ROOT / 'config/ge-proton11-12-se4-p7.env'
        state = self.tmp / 'prepared-source.tsv'
        state.write_text(shell(config, 'pinned_ge_dxvk_legacy_records "$3"', DIGEST).stdout)
        check = 'pinned_ge_require_dxvk_legacy_state "$3" "$4"'
        self.ok(shell(config, check, source, state))
        victim = source / 'dxvk-legacy/dxvk/meson.build'
        original = victim.read_bytes()
        mutations = {
            'edited byte': lambda: victim.write_bytes(original + b'#'),
            'extra file': lambda: (source / 'dxvk-legacy/dxvk/extra.txt').write_text('x'),
            'deleted file': lambda: victim.unlink(),
            'mode change': lambda: victim.chmod(0o755),
            'symlink': lambda: (victim.unlink(), victim.symlink_to('meson_options.txt')),
            'empty dir': lambda: (source / 'dxvk-legacy/dxvk/emptydir').mkdir(),
        }
        for name, mutate in mutations.items():
            with self.subTest(mutation=name):
                mutate()
                result = shell(config, check, source, state)
                self.assertNotEqual(result.returncode, 0, name)
                self.assertIn('differs from PIN_DXVK_LEGACY_TREE_SHA256', result.stderr)
                shutil.rmtree(source / 'dxvk-legacy/dxvk/emptydir', ignore_errors=True)
                (source / 'dxvk-legacy/dxvk/extra.txt').unlink(missing_ok=True)
                if victim.is_symlink() or not victim.exists():
                    victim.unlink(missing_ok=True)
                victim.write_bytes(original)
                victim.chmod(0o644)
                self.ok(shell(config, check, source, state))

    def test_prepared_state_records_must_match(self):
        source = self.fixture()
        self.ok(export(source))
        config = ROOT / 'config/ge-proton11-12-se4-p7.env'
        good = shell(config, 'pinned_ge_dxvk_legacy_records "$3"', DIGEST).stdout
        keys = [line.split('\t')[0] for line in good.splitlines()]
        self.assertEqual(keys, ['dxvk_legacy_commit', 'dxvk_legacy_source_sha256',
                                'dxvk_legacy_makefile_patch_sha256', 'dxvk_legacy_makefile_blob'])
        for key in keys:
            state = self.tmp / ('state-%s.tsv' % key)
            state.write_text(''.join(('%s\t%s\n' % (k, '0' * 40) if k == key else line + '\n')
                                     for k, line in zip(keys, good.splitlines())))
            with self.subTest(record=key):
                result = shell(config, 'pinned_ge_require_dxvk_legacy_state "$3" "$4"', source, state)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('prepared-state legacy DXVK record differs for ' + key, result.stderr)
        absent = self.tmp / 'absent.tsv'
        absent.write_text(good.split('\n', 1)[1])
        self.assertNotEqual(shell(config, 'pinned_ge_require_dxvk_legacy_state "$3" "$4"', source, absent).returncode, 0)

    # -- pins without the feature ------------------------------------------
    def test_pins_without_the_legacy_keys_export_nothing_and_record_nothing(self):
        config = ROOT / 'config/ge-proton11-12-se4-p6.env'
        self.assertEqual(shell(config, 'pinned_ge_dxvk_legacy_records anything; pinned_ge_require_dxvk_legacy_state /nonexistent /nonexistent',
                               ).stdout, '')
        self.assertEqual(shell(config, 'pinned_ge_dxvk_legacy_enabled').returncode, 1)
        source = self.fixture()
        result = export(source, config=config)
        self.assertNotEqual(result.returncode, 0)

    def test_exporter_never_writes_into_the_reference_checkout(self):
        exclude = REFERENCE / '.git/info/exclude'
        before = exclude.read_bytes() if exclude.exists() else None
        self.ok(export(self.fixture()))
        self.assertFalse((REFERENCE / 'dxvk-legacy').exists())
        self.assertEqual(exclude.read_bytes() if exclude.exists() else None, before)


if __name__ == '__main__':
    unittest.main(verbosity=2)
