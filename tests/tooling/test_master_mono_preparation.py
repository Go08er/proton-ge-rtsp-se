#!/usr/bin/env python3
"""Master's archive-backed Mono preparation, without fetching or compiling."""

from pathlib import Path
import hashlib
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class MasterPreparationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="rtsp-ge-mono-test.")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.repo = self.base / "source"
        self.repo.mkdir()
        self.git("init", "-q")
        (self.repo / ".gitignore").write_text("/wine-mono/\n")
        scripts = self.repo / "patches/wine-mono"
        scripts.mkdir(parents=True)
        (scripts / "prepare.sh").write_text("# fixture, never executed\n")
        (scripts / "source.conf").write_text("WINEMONO_VER=11.2.0\n")
        self.git("add", ".")
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@invalid",
                 "commit", "-qm", "master source fixture")
        self.commit = self.git("rev-parse", "HEAD").strip()
        self.archive = self.repo / "contrib/wine-mono-11.2.0-src.tar.xz"
        self.archive.parent.mkdir()
        self.archive.write_bytes(b"declared input fixture\n")
        self.archive.chmod(0o644)
        digest = hashlib.sha256(self.archive.read_bytes()).hexdigest()
        self.manifest = self.base / "contrib.tsv"
        self.manifest.write_text(
            f"build_contrib_manifest_version\t2\nsource_commit\t{self.commit}\n"
            f"entry\t{self.archive.relative_to(self.repo)}\t0644\t"
            f"{self.archive.stat().st_size}\t{digest}\n")
        self.mono = self.repo / "wine-mono"
        self.mono.mkdir()
        (self.mono / ".proton-prepared").touch()
        (self.mono / "source.c").write_text("prepared source\n")
        self.state = self.base / "prepared-source.tsv"

    def git(self, *args):
        return subprocess.check_output(
            ["git", "-C", str(self.repo), *args], text=True,
            env={**os.environ, "GIT_NO_LAZY_FETCH": "1", "GIT_ALLOW_PROTOCOL": "file"})

    def helper(self, command):
        return subprocess.run(
            ["bash", "-c", 'set -euo pipefail; source "$1/scripts/pinned-ge-common.sh"; '
             'source "$1/scripts/pinned-ge-source-inputs.sh"; '
             'PIN_SOURCE_COMMIT="$2"; ' + command, "fixture", str(ROOT),
             self.commit, str(self.repo), str(self.manifest), str(self.state)],
            text=True, capture_output=True,
            env={**os.environ, "GIT_NO_LAZY_FETCH": "1", "GIT_ALLOW_PROTOCOL": "file"})

    def inputs(self):
        return self.helper('pinned_ge_require_pristine_with_contrib "$3" "$4"')

    def digest(self):
        result = self.helper('pinned_ge_mono_source_digest "$3"')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(result.stdout, r"^[0-9a-f]{64}\n$")
        return result.stdout.strip()

    def seal(self):
        self.state.write_text(f"wine_mono_source_sha256\t{self.digest()}\n")

    def verify(self):
        return self.helper('pinned_ge_require_mono_source_state "$3" "$5"')

    def test_declared_prefetched_input_is_accepted(self):
        # Old preparation's pristine-status condition rejected this real case.
        self.assertIn("?? contrib/", self.git("status", "--porcelain", "--untracked-files=all"))
        result = self.inputs()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_archive_is_rejected(self):
        self.archive.unlink()
        self.assertNotEqual(self.inputs().returncode, 0)

    def test_changed_archive_is_rejected(self):
        self.archive.write_bytes(b"changed input\n")
        self.assertNotEqual(self.inputs().returncode, 0)

    def test_archive_mode_mismatch_is_rejected(self):
        self.archive.chmod(0o600)
        self.assertNotEqual(self.inputs().returncode, 0)

    def test_undeclared_mono_archive_is_rejected(self):
        self.manifest.write_text(self.manifest.read_text().replace(
            "wine-mono-11.2.0-src.tar.xz", "other-input.tar.xz"))
        self.archive.rename(self.archive.with_name("other-input.tar.xz"))
        result = self.inputs()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must be declared and prefetched", result.stderr)

    def test_unrelated_untracked_input_is_rejected(self):
        (self.repo / "contrib/extra.zip").write_bytes(b"extra")
        result = self.inputs()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not pristine outside declared contrib", result.stderr)

    def test_tracked_change_is_rejected(self):
        (self.repo / "patches/wine-mono/prepare.sh").write_text("changed\n")
        self.assertNotEqual(self.inputs().returncode, 0)

    def test_staged_change_is_rejected(self):
        (self.repo / "patches/wine-mono/prepare.sh").write_text("changed\n")
        self.git("add", "patches/wine-mono/prepare.sh")
        self.git("restore", "--source=HEAD", "--worktree", "patches/wine-mono/prepare.sh")
        self.assertNotEqual(self.inputs().returncode, 0)

    def test_ignored_mono_change_is_caught_where_old_root_digest_misses_it(self):
        self.seal()
        before = self.helper('pinned_ge_repo_state_digest "$3" "$4"')
        self.assertEqual(before.returncode, 0, before.stderr)
        self.assertEqual(self.verify().returncode, 0)
        (self.mono / "source.c").write_text("unexpected change\n")
        after = self.helper('pinned_ge_repo_state_digest "$3" "$4"')
        self.assertEqual(after.returncode, 0, after.stderr)
        self.assertEqual(before.stdout, after.stdout, "old Git-only digest must miss ignored Mono")
        result = self.verify()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("differs from its recorded digest", result.stderr)

    def test_mono_modes_are_sealed_but_timestamps_are_not(self):
        self.seal()
        source = self.mono / "source.c"
        os.utime(source, (1000, 1000))
        self.assertEqual(self.verify().returncode, 0)
        source.chmod(0o755)
        self.assertNotEqual(self.verify().returncode, 0)

    def test_missing_or_symlinked_mono_stamp_is_rejected(self):
        self.seal()
        stamp = self.mono / ".proton-prepared"
        stamp.unlink()
        self.assertNotEqual(self.verify().returncode, 0)
        stamp.symlink_to("source.c")
        self.assertNotEqual(self.verify().returncode, 0)

    def test_missing_seal_is_rejected(self):
        self.state.write_text("prepared_source_version\t2\n")
        self.assertNotEqual(self.verify().returncode, 0)

    def test_tree_hash_failure_propagates_through_conditional_caller(self):
        (self.mono / "bad\tname.c").write_text("unrepresentable TSV path\n")
        result = self.helper(
            'if digest="$(pinned_ge_mono_source_digest "$3")"; then '
            'echo ACCEPTED; exit 1; else echo REJECTED; fi')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "REJECTED\n")
        self.assertIn("path cannot be represented safely in TSV", result.stderr)

    def test_old_pin_does_not_require_new_mono_state(self):
        self.git("rm", "-q", "patches/wine-mono/prepare.sh")
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@invalid",
                 "commit", "-qm", "old-style source")
        self.commit = self.git("rev-parse", "HEAD").strip()
        self.assertEqual(self.verify().returncode, 0)

    def test_build_checks_mono_before_lock_and_uses_exact_component_validator(self):
        script = (ROOT / "scripts/build-pinned-ge.sh").read_text()
        self.assertLess(script.index('pinned_ge_require_mono_source_state "$SOURCE_DIR"'),
                        script.index('BUILD_LOCK='))
        arm = script.split("    vklayers/low_latency_layer)", 1)[1].split(";;", 1)[0]
        self.assertIn("pinned_ge_require_upstream_component_patch_state", arm)
        self.assertIn('"$SOURCE_DIR/$path" "$SOURCE_DIR/patches/low_latency_layer"', arm)
        self.assertIn("low_latency_args+=(--check)", script)


if __name__ == "__main__":
    unittest.main(verbosity=2)
