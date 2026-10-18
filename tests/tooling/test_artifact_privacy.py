#!/usr/bin/env python3
"""Exercise the real embedded artifact scan, without a build or network.

Small synthetic DLL fixtures substitute ONLY the expected DLL hash in the
extracted scanner. The production scanner retains the observed upstream hash.
"""
import hashlib
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (ROOT / "scripts/verify-pinned-ge-artifact.sh").read_text()
START = 'if ! python3 - "$TOOL_DIR" "${HOME:-}" <<\'PY\'\n'
SCAN = SCRIPT.split(START, 1)[1].split("\nPY\nthen\n", 1)[0]
DLL = "files/share/xalia/Superpower.dll"
REAL_SHA = "2637bcd7f165e1e88e139672e023d264638bb4555627e373429ca47b99ee467e"
# Construct intentional private-path fixtures without putting literal home
# paths in project-facing text (the repository's existing privacy rule).
UNIX_HOME = "/" + "home" + "/"
MAC_HOME = "/" + "Users" + "/"
RUNNER_HOME = UNIX_HOME + "runner"
PDB = (RUNNER_HOME + "/work/superpower/superpower/src/Superpower/obj/Release/netstandard2.0/Superpower.pdb").encode()
GOOD = b"synthetic-public-dependency\0" + PDB + b"\0"


class ArtifactPrivacyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="rtsp-artifact-privacy-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def write(self, relative, payload):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return path

    def scan(self, okay, *, home=UNIX_HOME + "local-builder", known=GOOD, source=SCAN):
        # This substitution enables tiny portable fixtures, not a production
        # escape hatch. No environment variable can override the real hash.
        source = source.replace(REAL_SHA, hashlib.sha256(known).hexdigest())
        result = subprocess.run([sys.executable, "-I", "-c", source, str(self.root), home],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode == 0, okay, result.stdout + result.stderr)
        return result

    def test_old_scan_reproduces_false_positive_fixed_scan_accepts_exact_identity(self):
        self.write(DLL, GOOD)
        old = SCAN.replace("allow_xalia = (rel == XALIA_SUPERPOWER_FILE",
                           "allow_xalia = (False and rel == XALIA_SUPERPOWER_FILE")
        result = self.scan(False, source=old)
        self.assertIn("absolute Unix home path", result.stderr)
        self.scan(True)
        self.scan(True, home=RUNNER_HOME)

    def test_correct_public_path_wrong_file_or_hash_still_fails(self):
        path = self.write("files/share/xalia/other.dll", GOOD)
        self.scan(False)
        path.unlink()
        self.write(DLL, GOOD + b"changed")
        self.scan(False)

    def test_whole_file_identity_does_not_allow_other_home_paths(self):
        for extra in [(UNIX_HOME + "private-person/key\0").encode(),
                      (MAC_HOME + "private-person/key\0").encode(),
                      b"C:\\Users\\private-person\\key\0", b"/root/.ssh/key\0",
                      (RUNNER_HOME + "/work/another-project/file\0").encode()]:
            with self.subTest(extra=extra):
                payload = GOOD + extra
                self.write(DLL, payload)
                self.scan(False, known=payload)

    def test_full_pdb_path_not_a_prefix_allowlist(self):
        for path in [PDB + b"/private", PDB + b".changed", PDB.replace(b"Release", b"Debug"),
                     RUNNER_HOME.encode(), (RUNNER_HOME + "/work/superpower/private").encode()]:
            with self.subTest(path=path):
                payload = path + b"\0"
                self.write(DLL, payload)
                self.scan(False, known=payload)

    def test_personal_paths_in_other_files_and_wide_encodings_remain_rejected(self):
        self.write(DLL, GOOD)
        for encoding in ["ascii", "utf-16-le", "utf-16-be"]:
            for path in [UNIX_HOME + "private-person/data", MAC_HOME + "private-person/data",
                         "C:\\Users\\private-person\\data"]:
                with self.subTest(encoding=encoding, path=path):
                    self.write("files/.hidden/data.bin", path.encode(encoding))
                    self.scan(False)

    def test_exact_nonstandard_builder_home_is_still_rejected(self):
        self.write(DLL, GOOD)
        self.write("files/other", b"/srv/private-build-home/source\0")
        result = self.scan(False, home="/srv/private-build-home")
        self.assertIn("exact builder HOME", result.stderr)

    def test_existing_ci_and_generic_profile_allowances_are_unchanged(self):
        self.write("files/other", (RUNNER_HOME + "/work/llvm-mingw/llvm/source.c\0").encode()
                   + b"C:\\users\\steamuser\\data\0C:\\users\\Public\\data\0")
        self.scan(True)
        self.scan(True, home=RUNNER_HOME)

    def test_fixture_source_respects_existing_project_text_rule(self):
        preparation = (ROOT / "scripts/verify-preparation.sh").read_text()
        pattern = next(line.split("'", 2)[1] for line in preparation.splitlines()
                       if line.startswith("PROJECT_HOME_PATTERN="))
        self.assertIsNone(re.search(pattern, Path(__file__).read_text(), re.IGNORECASE))

    def test_absolute_symlinks_still_fail(self):
        self.write(DLL, GOOD)
        (self.root / "outside").symlink_to("/tmp")
        self.scan(False)


if __name__ == "__main__":
    unittest.main(verbosity=2)
