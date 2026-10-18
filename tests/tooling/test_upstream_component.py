#!/usr/bin/env python3
"""Exact GE component patch verification, without compiling or networking."""

from pathlib import Path
import ast
import os
import shlex
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class ComponentPatchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="rtsp-ge-component-test.")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.repo = self.base / "component"
        self.repo.mkdir()
        self.patches = self.base / "patches"
        self.patches.mkdir()
        self.git("init", "-q")
        (self.repo / "source.c").write_text("before\n")
        self.git("add", "source.c")
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@invalid",
                 "commit", "-qm", "baseline")
        (self.repo / "source.c").write_text("after\n")
        (self.patches / "0001.patch").write_text(self.git("diff"))
        self.original_index = (self.repo / ".git/index").read_bytes()

    def git(self, *args):
        return subprocess.check_output(
            ["git", "-C", str(self.repo), *args], text=True,
            env={**os.environ, "GIT_NO_LAZY_FETCH": "1"})

    def check(self):
        result = subprocess.run(
            ["bash", "-c", 'source "$1"; '
             'pinned_ge_require_upstream_component_patch_state "$2" "$3"',
             "fixture", str(ROOT / "scripts/pinned-ge-common.sh"),
             str(self.repo), str(self.patches)], capture_output=True, text=True)
        self.assertEqual((self.repo / ".git/index").read_bytes(), self.original_index)
        return result

    def test_exact_upstream_result_passes_without_altering_source(self):
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.repo / "source.c").read_text(), "after\n")

    def test_missing_patch_application_fails(self):
        (self.repo / "source.c").write_text("before\n")
        self.assertNotEqual(self.check().returncode, 0)

    def test_extra_tracked_change_fails(self):
        (self.repo / "source.c").write_text("after\nnot authorized\n")
        self.assertNotEqual(self.check().returncode, 0)

    def test_untracked_file_fails(self):
        (self.repo / "unexpected.c").write_text("extra source\n")
        self.assertNotEqual(self.check().returncode, 0)

    def test_empty_patch_directory_fails(self):
        (self.patches / "0001.patch").unlink()
        self.assertNotEqual(self.check().returncode, 0)

    def test_low_impact_reexec_preserves_selected_series(self):
        script = (ROOT / "scripts/build-pinned-ge.sh").read_text()
        arguments = script.split("REEXEC_ARGS=(", 1)[1].split("\n  )", 1)[0]
        self.assertIn('--series "$PATCH_SERIES"', arguments)

    def test_preparation_offset_backup_regression(self):
        """Old invocation leaves the exact untracked file that blocked P14."""
        script = (ROOT / 'scripts/prepare-pinned-ge-source.sh').read_text()
        line = next(line for line in script.splitlines()
                    if line.startswith('text = text.replace(patch_call,'))
        invocation = ast.parse(line).body[0].value.args[1].value
        self.assertTrue(invocation.endswith(' <'))
        patch = '--- a/item.c\n+++ b/item.c\n@@ -1,3 +1,3 @@\n one\n-before\n+after\n three\n'
        before = 'prefix\none\nbefore\nthree\n'
        after = 'prefix\none\nafter\nthree\n'
        for name, command, backup in [
            ('old', ['patch', '-Np1', '--batch'], True),
            ('fixed', shlex.split(invocation[:-2]), False),
        ]:
            with self.subTest(name=name):
                directory = self.base / name
                directory.mkdir()
                target = directory / 'item.c'
                target.write_text(before)
                result = subprocess.run(command, input=patch, text=True, cwd=directory,
                                        capture_output=True, env={**os.environ, 'LC_ALL': 'C'})
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('offset 1 line', result.stdout)
                self.assertEqual(target.read_text(), after)
                self.assertEqual((directory / 'item.c.orig').exists(), backup)
                if backup:
                    self.assertEqual((directory / 'item.c.orig').read_text(), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
