#!/usr/bin/env python3
"""Dual DXVK launcher selection (T4, T5, T5b): drives the patched launcher's real code.

The carried patch 0002 is applied (git apply, zero fuzz) to the pinned GE-Proton
launcher in a scratch repository; the selection code is then extracted from the
patched file with the ast module and run against a stub environment. No Wine, no
prefix and no network are involved.
"""
import ast
import io
import os
from pathlib import Path
import tempfile
import textwrap
import types
import unittest

from dxvk_legacy_common import LAUNCHER_PATCH, ROOT, git, local_ge_source, pin_values, run, shell

SOURCE = local_ge_source()


def patched_launcher(directory):
    """Apply 0002 to the pinned GE launcher blob; return the patched source text."""
    commit = pin_values()['PIN_SOURCE_COMMIT']
    work = Path(directory) / 'launcher'
    work.mkdir()
    git(work, 'init', '-q')
    blob = git(SOURCE, 'show', commit + ':proton').stdout
    (work / 'proton').write_text(blob)
    os.chmod(work / 'proton', 0o755)
    check = git(work, 'apply', '--check', str(LAUNCHER_PATCH), check=False)
    assert check.returncode == 0, check.stderr
    git(work, 'apply', str(LAUNCHER_PATCH))
    return (work / 'proton').read_text()


@unittest.skipIf(SOURCE is None, 'no local checkout with the pinned GE launcher')
class DxvkLegacyLauncher(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='rtsp-dxvk-legacy-launcher-')
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.text = patched_launcher(cls.tmp.name)
        cls.tree = ast.parse(cls.text)
        names = {'nonzero', 'file_exists', 'dxvk_variant_dir'}
        body = [n for n in cls.tree.body
                if (isinstance(n, ast.FunctionDef) and n.name in names)
                or (isinstance(n, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id == 'DXVK_LEGACY_DEFAULT_APPIDS' for t in n.targets))]
        session = next(n for n in cls.tree.body if isinstance(n, ast.ClassDef) and n.name == 'Session')
        methods = [n for n in session.body
                   if isinstance(n, ast.FunctionDef) and n.name in ('select_dxvk_variant', 'check_environment')]
        assert len(methods) == 2 and len(body) == 4
        stub = ast.ClassDef(name='StubSession', bases=[], keywords=[], body=methods, decorator_list=[])
        module = ast.Module(body=body + [stub], type_ignores=[])
        cls.ns = {'os': os}
        exec(compile(ast.fix_missing_locations(module), 'patched-proton', 'exec'), cls.ns)

    def session(self, env=None, compat=()):
        stub = self.ns['StubSession']()
        stub.env = dict(env or {})
        stub.compat_config = set(compat)
        return stub

    def select(self, env=None, compat=()):
        stub = self.session(env, compat)
        reason = stub.select_dxvk_variant()
        return 'dxvklegacy' in stub.compat_config, reason

    # T4: explicit beats the VRChat default, both ways.
    def test_vrchat_defaults_to_legacy(self):
        self.assertEqual(self.select({'SteamGameId': '438100'}), (True, 'appid-default'))

    def test_env_zero_beats_the_vrchat_default(self):
        # Also the user_settings.py case: init_session loads user_settings into
        # self.env before the selection runs, so the value is seen as env.
        self.assertEqual(self.select({'SteamGameId': '438100', 'PROTON_DXVK_LEGACY': '0'}), (False, 'env'))

    def test_nodxvklegacy_token_beats_the_vrchat_default(self):
        self.assertEqual(self.select({'SteamGameId': '438100'}, {'nodxvklegacy'}), (False, 'token'))

    def test_env_one_and_token_select_legacy_elsewhere(self):
        self.assertEqual(self.select({'SteamGameId': '220', 'PROTON_DXVK_LEGACY': '1'}), (True, 'env'))
        self.assertEqual(self.select({'SteamGameId': '220'}, {'dxvklegacy'}), (True, 'token'))

    def test_env_zero_beats_token(self):
        self.assertEqual(self.select({'SteamGameId': '220', 'PROTON_DXVK_LEGACY': '0'}, {'dxvklegacy'}),
                         (False, 'env'))

    def test_env_one_beats_the_nodxvklegacy_token(self):
        self.assertEqual(self.select({'SteamGameId': '220', 'PROTON_DXVK_LEGACY': '1'}, {'nodxvklegacy'}),
                         (True, 'env'))

    def test_both_tokens_without_env_fail_safe_to_primary(self):
        self.assertEqual(self.select({'SteamGameId': '438100'}, {'dxvklegacy', 'nodxvklegacy'}),
                         (False, 'token'))
        self.assertEqual(self.select({'SteamGameId': '220'}, {'dxvklegacy', 'nodxvklegacy'}),
                         (False, 'token'))

    def test_empty_env_value_counts_as_explicit_primary(self):
        self.assertEqual(self.select({'SteamGameId': '438100', 'PROTON_DXVK_LEGACY': ''}), (False, 'env'))

    def test_umu_id_fallback_matches_the_steam_appid_path(self):
        self.assertEqual(self.select({'UMU_ID': 'umu-438100'}), (True, 'appid-default'))
        self.assertEqual(self.select({'UMU_ID': 'umu-220'}), (False, 'none'))
        self.assertEqual(self.select({'UMU_ID': 'umu-'}), (False, 'none'))
        self.assertEqual(self.select({'UMU_ID': 'umu-43810x'}), (False, 'none'))
        # A set SteamGameId wins over UMU_ID.
        self.assertEqual(self.select({'SteamGameId': '220', 'UMU_ID': 'umu-438100'}), (False, 'none'))

    # T5: everything else defaults to the primary DXVK.
    def test_other_appids_use_the_primary_dxvk(self):
        for appid in ('0', '220', '1091500', '4381000', '43810', '1438100', ' 438100', ''):
            with self.subTest(appid=appid):
                self.assertEqual(self.select({'SteamGameId': appid}), (False, 'none'))
        self.assertEqual(self.select({}), (False, 'none'))

    # T5b and the directory switch.
    def test_missing_legacy_directory_falls_back_to_primary(self):
        with tempfile.TemporaryDirectory(prefix='rtsp-dxvk-lib-') as lib:
            lib = lib + '/'
            os.makedirs(lib + 'wine/dxvk')
            fn = self.ns['dxvk_variant_dir']
            self.assertEqual(fn(lib, False), ('wine/dxvk', False))
            self.assertEqual(fn(lib, True), ('wine/dxvk', False))
            os.makedirs(lib + 'wine/dxvk-legacy')
            self.assertEqual(fn(lib, True), ('wine/dxvk-legacy', True))
            self.assertEqual(fn(lib, False), ('wine/dxvk', False))

    def setup_prefix_log(self, compat, reason, lib):
        """Run the patched setup_prefix statements that pick the directory and log."""
        lines = self.text.splitlines()
        start = next(i for i, l in enumerate(lines) if 'dxvk_dir, dxvk_legacy_active = dxvk_variant_dir(' in l)
        end = next(i for i in range(start, len(lines)) if 'g_session.log_file.flush()' in lines[i])
        snippet = textwrap.dedent('\n'.join(lines[start:end + 1]))
        messages, logfile = [], io.StringIO()
        ns = dict(self.ns)
        ns.update(g_proton=types.SimpleNamespace(lib_dir=lib),
                  g_session=types.SimpleNamespace(compat_config=set(compat), dxvk_legacy_reason=reason,
                                                  log_file=logfile),
                  log=messages.append)
        exec(compile(snippet, 'patched-setup_prefix', 'exec'), ns)
        return ns['dxvk_dir'], messages, logfile.getvalue()

    def test_one_log_line_names_variant_and_reason(self):
        with tempfile.TemporaryDirectory(prefix='rtsp-dxvk-lib-') as lib:
            lib = lib + '/'
            os.makedirs(lib + 'wine/dxvk-legacy')
            for compat, reason, directory, text in (
                    ({'dxvklegacy'}, 'appid-default', 'wine/dxvk-legacy', 'DXVK variant: legacy (appid-default)'),
                    ({'dxvklegacy'}, 'env', 'wine/dxvk-legacy', 'DXVK variant: legacy (env)'),
                    ({'dxvklegacy'}, 'token', 'wine/dxvk-legacy', 'DXVK variant: legacy (token)'),
                    (set(), 'none', 'wine/dxvk', 'DXVK variant: default (none)'),
                    (set(), 'env', 'wine/dxvk', 'DXVK variant: default (env)')):
                with self.subTest(text=text):
                    got_dir, messages, logfile = self.setup_prefix_log(compat, reason, lib)
                    self.assertEqual((got_dir, messages), (directory, [text]))
                    self.assertEqual(logfile, text + '\n')
        with tempfile.TemporaryDirectory(prefix='rtsp-dxvk-lib-') as lib:
            got_dir, messages, _ = self.setup_prefix_log({'dxvklegacy'}, 'env', lib + '/')
            self.assertEqual(got_dir, 'wine/dxvk')
            self.assertEqual(len(messages), 1)
            self.assertTrue(messages[0].startswith('DXVK variant: default (env;'), messages)
            self.assertIn('wine/dxvk-legacy is missing', messages[0])

    # Structure of the patched launcher.
    def test_resolution_runs_after_user_settings_and_before_check_environment(self):
        init = next(n for c in self.tree.body if isinstance(c, ast.ClassDef) and c.name == 'Session'
                    for n in c.body if isinstance(n, ast.FunctionDef) and n.name == 'init_session')
        text = self.text
        body_start = text.index('    def init_session(self, update_prefix_files):')
        loaded = text.index('for key, value in user_settings.user_settings.items():', body_start)
        select = text.index('self.dxvk_legacy_reason = self.select_dxvk_variant()', body_start)
        first_check = text.index('self.check_environment("PROTON_USE_WOW64", "wow64")', body_start)
        self.assertLess(loaded, select)
        self.assertLess(select, first_check)
        self.assertTrue(any(isinstance(n, ast.Assign) and any(
            isinstance(t, ast.Attribute) and t.attr == 'dxvk_legacy_reason' for t in n.targets)
            for n in ast.walk(init)))
        # The flag is not part of prefix_info (no builtin-lib rewrite on a flip), and no stamp file.
        info = text[text.index('prefix_info = '):text.index('# check whether any prefix config has changed')]
        self.assertNotIn('dxvk_dir', info)
        self.assertNotIn('dxvklegacy', info)
        self.assertNotIn('dxvk_legacy', info)
        self.assertNotIn('.dxvk-variant', text)

    def test_every_dxvk_copy_uses_the_selected_directory(self):
        self.assertNotIn('arch_pe_dir("wine/dxvk"', self.text)
        self.assertEqual(self.text.count('arch_pe_dir(dxvk_dir,'), 4)

    def test_patch_leaves_user_settings_sample_alone_and_compiles(self):
        compile(self.text, 'patched-proton', 'exec')
        patch = LAUNCHER_PATCH.read_text()
        self.assertEqual([l for l in patch.splitlines() if l.startswith('diff --git')],
                         ['diff --git a/proton b/proton'])


    def test_upstream_launcher_check_rejects_the_patched_launcher_and_accepts_the_blob(self):
        patched = Path(self.tmp.name) / 'launcher/proton'
        stock = Path(self.tmp.name) / 'stock-proton'
        stock.write_text(git(SOURCE, 'show', pin_values()['PIN_SOURCE_COMMIT'] + ':proton').stdout)
        check = 'pinned_ge_require_upstream_launcher "$3" "$4"'
        config = ROOT / 'config/ge-proton11-12-se4-p6.env'
        self.assertEqual(shell(config, check, SOURCE, stock).returncode, 0)
        rejected = shell(config, check, SOURCE, patched)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn('launcher differs', rejected.stderr)
        # git apply --reverse (the build-time check) accepts the patched launcher only.
        work = patched.parent
        self.assertEqual(git(work, 'apply', '--check', '--reverse', str(LAUNCHER_PATCH), check=False).returncode, 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
