#!/usr/bin/env python3
"""Exercise real manifest staging and rsync preservation without a GE build.

No network, generator execution, cpp, compiler, container or source mutation.
Fixtures demonstrate both the old missing-header problem and why pre-seeding
without an rsync exclusion is insufficient. Temporary files are removed.
"""

import hashlib
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
BUILD_SCRIPT = (ROOT / "scripts/build-pinned-ge.sh").read_text()
HEADER = "nvml_610.43.02.h"
INPUT = "contrib/nvidia-libs/wine-nvml/" + HEADER
CONTENT = b"/* synthetic NVML input, not NVIDIA source */\n"


def shell_function(name):
    start = BUILD_SCRIPT.index(name + "() {\n")
    return BUILD_SCRIPT[start:BUILD_SCRIPT.index("\n}", start) + 2]


class NvmlBuildInput(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="rtsp-nvml-input-")
        self.addCleanup(temporary.cleanup)
        self.temp = Path(temporary.name)
        self.source = self.temp / "source"
        self.build = self.temp / "build"
        self.origin = self.source / "nvidia-libs/wine-nvml"
        (self.origin / "src").mkdir(parents=True)
        self.generator = self.origin / "src/make_nvml"
        self.generator.write_text('#!/bin/sh\nversion="${1:-610.43.02}"\n')
        self.input = self.source / INPUT
        self.input.parent.mkdir(parents=True)
        self.input.write_bytes(CONTENT)
        self.input.chmod(0o644)
        self.manifest = self.temp / "contrib.tsv"
        self.manifest.write_text(
            "build_contrib_manifest_version\t3\nsource_commit\t" + "0" * 40 + "\n"
            f"entry\t{INPUT}\t0644\t{len(CONTENT)}\t{hashlib.sha256(CONTENT).hexdigest()}\n"
            f"fetch\t{INPUT}\thttps://fixtures.invalid/nvml.h\n")

    def seed(self, enabled=True):
        # Import only the three functions under test, never the build script's
        # top-level flow (which can acquire a lock or invoke a container).
        script = 'source "$1/scripts/pinned-ge-common.sh"\n'
        script += "\n".join(shell_function(name) for name in (
            "manifest_build_input_record", "stage_manifest_build_input", "seed_nvml_build_contrib"))
        script += '\nSOURCE_DIR="$2"; BUILD_DIR="$3"; CONTRIB_MANIFEST="$4"\n'
        script += 'PIN_WITHOUT_NVIDIA_LIBS="$5"; PIN_SOURCE_COMMIT=' + "0" * 40 + '\nseed_nvml_build_contrib\n'
        return subprocess.run(["bash", "-eu", "-c", script, "nvml-input-test", str(ROOT), str(self.source),
                               str(self.build), str(self.manifest), "0" if enabled else "1"],
                              capture_output=True, text=True, timeout=15)

    def sync(self, component, protected):
        destination = self.build / ("src-" + component)
        destination.mkdir(parents=True, exist_ok=True)
        args = ["rsync", "--filter=:C", "--exclude", "*~", "--exclude", ".git",
                "--exclude", "compile_commands.json", "-Oarx", "--delete"]
        if protected:
            key = "NVML_SO_SOURCE_ARGS" if component == "nvml_so" else "NVML_DLL_SOURCE_ARGS"
            value = re.search(r'"' + key + r'=([^"\n]+)"', BUILD_SCRIPT).group(1)
            self.assertEqual(value, "--exclude=/src/" + HEADER)
            args.append(value)
        subprocess.run(args + [str(self.origin) + "/", str(destination)], check=True, capture_output=True, timeout=15)
        return destination / "src" / HEADER

    def test_old_source_copy_has_no_header(self):
        for component in ("nvml_so", "nvml_dll"):
            self.assertFalse(self.sync(component, protected=False).exists())

    def test_preseed_without_exclusion_is_deleted(self):
        result = self.seed()
        self.assertEqual(result.returncode, 0, result.stderr)
        for component in ("nvml_so", "nvml_dll"):
            self.assertFalse(self.sync(component, protected=False).exists())

    def test_exact_exclusion_preserves_both_headers_across_resync(self):
        for attempt in range(2):
            result = self.seed()
            self.assertEqual(result.returncode, 0, result.stderr)
            if attempt:
                self.assertEqual(result.stdout.count("Using seeded NVML header"), 2)
            for component in ("nvml_so", "nvml_dll"):
                stale = self.build / ("src-" + component) / "src/stale-generated.c"
                stale.write_text("must still be removed by normal source reconciliation\n")
                target = self.sync(component, protected=True)
                self.assertEqual(target.read_bytes(), CONTENT)
                self.assertEqual(target.stat().st_mode & 0o777, 0o644)
                self.assertEqual((target.parent / "make_nvml").read_text(), self.generator.read_text())
                self.assertFalse(stale.exists())
        self.assertFalse((self.origin / "src" / HEADER).exists())

    def test_reduced_pin_needs_no_nvml_input(self):
        self.input.unlink()
        self.generator.unlink()
        result = self.seed(enabled=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.build.exists())

    def test_changed_generator_and_mismatched_header_fail(self):
        self.generator.write_text('version="${1:-999.0}"\n')
        result = self.seed()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("NVML generator version changed", result.stderr)
        self.generator.write_text('version="${1:-610.43.02}"\n')
        self.input.write_bytes(b"wrong header\n")
        result = self.seed()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("source differs from its manifest", result.stderr)

    def test_missing_declaration_fails(self):
        contents = self.manifest.read_text().replace(INPUT, "contrib/unrelated.h")
        self.manifest.write_text(contents)
        result = self.seed()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("build input is not declared by the selected pin", result.stderr)

    def test_invocation_seeds_before_make_and_no_source_patch(self):
        run = shell_function("run_build")
        self.assertLess(run.index("  seed_nvml_build_contrib\n"), run.index('make "${make_args[@]}"'))
        self.assertIn('if [[ "$PIN_WITHOUT_NVIDIA_LIBS" == 0 ]]; then\n    make_args+=(', run)
        self.assertNotIn("src/make_nvml", run)
        self.assertIn("--network=none", run)


if __name__ == "__main__":
    unittest.main(verbosity=2)
