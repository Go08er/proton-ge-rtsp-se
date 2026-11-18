#!/usr/bin/env python3
"""Test the pinned NVIDIA Ninja bound without a Proton build.

Copies the actual upstream rule into a disposable Git fixture. GNU Make expands
its real macro with NINJA_JOBS=2; a recording-only Ninja stub handles Make's
recursive (+) recipe during the dry run. No container, compiler or real Ninja.
"""

import argparse
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SOURCE = None
MAKE = None
RULE = Path("make/rules-nvidia-libs.mk")


class NvidiaBuildRules(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="rtsp-nvidia-rules-")
        self.addCleanup(temp.cleanup)
        self.temp = Path(temp.name)
        self.source = self.temp / "source"
        self.rule = self.source / RULE
        self.rule.parent.mkdir(parents=True)
        self.original = subprocess.check_output(
            ["git", "-C", str(SOURCE), "show", "HEAD:" + str(RULE)],
            env={**os.environ, "GIT_NO_LAZY_FETCH": "1"}, timeout=15)
        self.rule.write_bytes(self.original)
        self.git("init", "-q")
        self.git("add", str(RULE))
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@invalid",
                 "-c", "commit.gpgsign=false", "commit", "-qm", "pinned fixture")
        self.commit = self.git("rev-parse", "HEAD").stdout.strip()

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.source), *args], check=True,
                              capture_output=True, text=True, timeout=15,
                              env={**os.environ, "GIT_NO_LAZY_FETCH": "1"})

    def rule_action(self, operation, enabled=True):
        script = 'source "$1/scripts/pinned-ge-common.sh"\n'
        script += 'PIN_SOURCE_COMMIT="$3"; PIN_WITHOUT_NVIDIA_LIBS="$5"\n'
        script += 'pinned_ge_nvidia_build_rules "$2" "$4"\n'
        return subprocess.run(["bash", "-eu", "-c", script, "nvidia-rule-test",
                               str(ROOT), str(self.source), self.commit, operation,
                               "0" if enabled else "1"], capture_output=True,
                              text=True, timeout=15)

    def dry_run(self):
        stub = self.temp / "bin/ninja"
        stub.parent.mkdir(exist_ok=True)
        args_file = self.temp / "ninja-args.txt"
        stub.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$NVML_TEST_ARGS"\n')
        stub.chmod(0o755)
        makefile = self.temp / "test.mk"
        makefile.write_text(
            f"OBJ := {self.temp}/objects\nSRC := {self.source}\n"
            "ARCHS := x86_64-windows\nHOST_ARCH := x86_64\n"
            f"NVML_DLL_SRC := {self.source}/nvidia-libs/wine-nvml\n"
            f"NVML_DLL_x86_64_OBJ := {self.temp}/obj-nvml\n"
            f"include {self.rule}\n"
            "$(eval $(call create-rules-nvidia-libs,nvml_dll,NVML_DLL,x86_64,windows))\n"
            ".PHONY: verify\nverify: $(OBJ)/.nvml_dll-x86_64-build\n")
        result = subprocess.run([MAKE, "--no-print-directory", "-n", "-f", str(makefile),
                                 "NINJA_JOBS=2", "verify"], capture_output=True,
                                text=True, timeout=15, env={**os.environ,
                                    "PATH": str(stub.parent) + os.pathsep + os.environ["PATH"],
                                    "NVML_TEST_ARGS": str(args_file),
                                    "MAKEFLAGS": "", "MFLAGS": "", "GNUMAKEFLAGS": ""})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(args_file.exists(), "Make's + recipe did not reach the recording stub")
        self.assertFalse((self.temp / "objects").exists(), "dry-run executed a real build step")
        return args_file.read_text().splitlines()

    def test_old_rule_lacks_explicit_bound_and_fails_check(self):
        self.assertEqual(self.dry_run(), ["-C", str(self.temp / "obj-nvml"), "install"])
        result = self.rule_action("check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("bounded NVIDIA Ninja rule differs", result.stderr)

    def test_normalized_real_macro_passes_exact_job_limit(self):
        result = self.rule_action("normalize")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.dry_run(), ["-j2", "-C", str(self.temp / "obj-nvml"), "install"])
        result = self.rule_action("check")
        self.assertEqual(result.returncode, 0, result.stderr)
        old = b'\tninja -C "$$($(2)_$(3)_OBJ)" install\n'
        new = b'\tninja -j"$$(NINJA_JOBS)" -C "$$($(2)_$(3)_OBJ)" install\n'
        self.assertEqual(self.rule.read_bytes(), self.original.replace(old, new, 1))

    def test_preexisting_mutation_not_overwritten(self):
        changed = self.original + b"# unexpected source mutation\n"
        self.rule.write_bytes(changed)
        result = self.rule_action("normalize")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refusing normalization", result.stderr)
        self.assertEqual(self.rule.read_bytes(), changed)

    def test_normalized_whole_file_mutation_is_rejected(self):
        self.assertEqual(self.rule_action("normalize").returncode, 0)
        self.rule.write_bytes(self.rule.read_bytes() + b"# unrelated alteration\n")
        result = self.rule_action("check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("pinned whole-file result", result.stderr)

    def test_changed_upstream_command_shape_requires_review(self):
        old = b'\tninja -C "$$($(2)_$(3)_OBJ)" install\n'
        for label, contents in (
                ("missing", self.original.replace(old, b"")),
                ("already changed", self.original.replace(old, old.replace(b"ninja -C", b"ninja -j3 -C"))),
                ("duplicated", self.original + old)):
            with self.subTest(label=label):
                self.rule.write_bytes(contents)
                self.git("add", str(RULE))
                self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@invalid",
                         "-c", "commit.gpgsign=false", "commit", "-qm", label)
                self.commit = self.git("rev-parse", "HEAD").stdout.strip()
                result = self.rule_action("normalize")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("expected exactly one", result.stderr)
                self.assertEqual(self.rule.read_bytes(), contents)

    def test_reduced_pins_are_unchanged_and_need_no_rule(self):
        for operation in ("normalize", "check"):
            self.assertEqual(self.rule_action(operation, enabled=False).returncode, 0)
            self.assertEqual(self.rule.read_bytes(), self.original)
        self.rule.unlink()
        self.assertEqual(self.rule_action("check", enabled=False).returncode, 0)

    def test_missing_pinned_object_and_symlink_are_rejected(self):
        self.commit = "0" * 40
        self.assertNotEqual(self.rule_action("normalize").returncode, 0)
        copy = self.temp / "copy.mk"
        copy.write_bytes(self.original)
        self.rule.unlink()
        self.rule.symlink_to(copy)
        result = self.rule_action("normalize")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("absent or unsafe", result.stderr)

    def test_prepare_and_build_use_the_shared_helper(self):
        prepare = (ROOT / "scripts/prepare-pinned-ge-source.sh").read_text()
        build = (ROOT / "scripts/build-pinned-ge.sh").read_text()
        self.assertLess(prepare.index('pinned_ge_nvidia_build_rules "$SOURCE_DIR" normalize'),
                        prepare.index('root_state_digest="$(pinned_ge_repo_state_digest'))
        self.assertIn('pinned_ge_nvidia_build_rules "$SOURCE_DIR" check', build)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="read-only GE source checkout")
    parser.add_argument("--make", required=True, help="already-installed GNU Make executable")
    args = parser.parse_args()
    SOURCE = args.source.resolve(strict=True)
    MAKE = args.make
    unittest.main(argv=[__file__], verbosity=2)
