#!/usr/bin/env python3
"""SE1 launcher selection; historical pins keep their exact policy."""
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
COMMON = ROOT / "scripts/pinned-ge-common.sh"
SE1 = ROOT / "config/ge-proton11-6-se1.env"
PRIOR = ROOT / "config/ge-proton11-6-a323.env"
DUAL = ROOT / "config/ge-proton11-12-se4-p7.env"
SE4_P6 = ROOT / "config/ge-proton11-12-se4-p6.env"


def shell(config, command, *args, **env):
    return subprocess.run(
        ["bash", "-c", 'set -e; source "$1"; PINNED_GE_CONFIG="$2"; '
         'shift 2; pinned_ge_load_config; ' + command,
         "launcher-test", str(COMMON), str(config), *map(str, args)],
        cwd=ROOT, env={**os.environ, **env}, text=True, capture_output=True,
        timeout=20,
    )


class LauncherPolicyTests(unittest.TestCase):
    def test_historical_pin_ignores_inherited_policy(self):
        result = shell(PRIOR, 'printf "%s" "$PIN_PROTON_LAUNCHER_POLICY"',
                       PIN_PROTON_LAUNCHER_POLICY="upstream")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "scoped-xrizer")

    def test_se1_has_no_patch(self):
        result = shell(SE1, 'pinned_ge_launcher_patch_record; pinned_ge_launcher_patch_sha256')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(),
                         ["none", hashlib.sha256(b"").hexdigest()])

    def test_old_patch_digest_is_unchanged(self):
        result = shell(PRIOR, 'pinned_ge_launcher_patch_sha256')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(),
                         "fb4fd665b84846e4c54d6e7d73ba7da327307d4b87005bcb9cf94eecad3048da")

    def test_repeated_load_does_not_leak_policy(self):
        result = shell(SE1, 'PINNED_GE_CONFIG="$1"; pinned_ge_load_config; '
                       'printf "%s" "$PIN_PROTON_LAUNCHER_POLICY"', PRIOR)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "scoped-xrizer")

    def test_unknown_policy_rejected(self):
        with tempfile.TemporaryDirectory(prefix="rtsp-launcher-test-") as tmp:
            config = Path(tmp) / "bad.env"
            config.write_text(SE1.read_text().replace(
                "PIN_PROTON_LAUNCHER_POLICY=upstream",
                "PIN_PROTON_LAUNCHER_POLICY=unknown"))
            result = shell(config, 'true')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unsupported Proton launcher policy", result.stderr)

    def test_verification_is_wired_to_selected_policy(self):
        # The scripts select the carried patch through the policy table
        # (pinned_ge_launcher_patch_file); upstream still uses the blob check.
        for path in ("scripts/prepare-pinned-ge-source.sh",
                     "scripts/build-pinned-ge.sh",
                     "scripts/verify-pinned-ge-artifact.sh"):
            code = (ROOT / path).read_text()
            self.assertIn("pinned_ge_launcher_patch_file", code)
            self.assertIn("pinned_ge_require_upstream_launcher", code)
            self.assertIn("pinned_ge_launcher_patch_sha256", code)
            self.assertNotIn("0001-launcher-add-scoped-xrizer-mode", code)
        code = (ROOT / "scripts/verify-pinned-ge-artifact.sh").read_text()
        self.assertIn("PIN_PROTON_LAUNCHER_POLICY", code)

    # Dual DXVK: the third policy value and its carried patch.
    def test_dxvk_legacy_policy_selects_its_own_patch(self):
        result = shell(DUAL, 'printf "%s\\n" "$PIN_PROTON_LAUNCHER_POLICY"; pinned_ge_launcher_patch_record; '
                       'pinned_ge_launcher_patch_sha256; sha256sum "$(pinned_ge_launcher_patch_file)"')
        self.assertEqual(result.returncode, 0, result.stderr)
        policy, record, digest, check = result.stdout.splitlines()
        self.assertEqual((policy, record), ("dxvk-legacy", "patches/proton/0002-launcher-add-dxvk-legacy-selection.patch"))
        self.assertEqual(check.split()[0], digest)
        self.assertEqual(digest, hashlib.sha256(
            (ROOT / record).read_bytes()).hexdigest())
        self.assertNotEqual(digest, "fb4fd665b84846e4c54d6e7d73ba7da327307d4b87005bcb9cf94eecad3048da")

    def test_policy_table_keeps_the_historical_values(self):
        for config, record in ((SE4_P6, "none"), (SE1, "none"),
                               (PRIOR, "patches/proton/0001-launcher-add-scoped-xrizer-mode.patch")):
            result = shell(config, 'pinned_ge_launcher_patch_record; printf "[%s]" "$(pinned_ge_launcher_patch_file)"')
            self.assertEqual(result.returncode, 0, result.stderr)
            expected_file = "" if record == "none" else str(ROOT / record)
            self.assertEqual(result.stdout.splitlines(), [record, "[%s]" % expected_file], config)

    def test_dxvk_legacy_policy_needs_its_keys_and_vice_versa(self):
        with tempfile.TemporaryDirectory(prefix="rtsp-launcher-test-") as tmp:
            lines = DUAL.read_text().splitlines()
            no_keys = Path(tmp) / "no-keys.env"
            no_keys.write_text("\n".join(l for l in lines if not l.startswith("PIN_DXVK_LEGACY_")) + "\n")
            result = shell(no_keys, 'true')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("dual DXVK requires launcher policy dxvk-legacy", result.stderr)
            keys_only = Path(tmp) / "keys-only.env"
            keys_only.write_text(SE4_P6.read_text() + "\n".join(
                l for l in lines if l.startswith("PIN_DXVK_LEGACY_")) + "\n")
            result = shell(keys_only, 'true')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("dual DXVK requires launcher policy dxvk-legacy", result.stderr)

    def test_historical_pin_ignores_inherited_dxvk_legacy_policy_and_keys(self):
        result = shell(PRIOR, 'printf "%s" "$PIN_PROTON_LAUNCHER_POLICY${PIN_DXVK_LEGACY_COMMIT:-}"',
                       PIN_PROTON_LAUNCHER_POLICY="dxvk-legacy",
                       PIN_DXVK_LEGACY_COMMIT="2cae043bdf767c8a7a2e0ee8d41537acfe773e8e")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "scoped-xrizer")
        result = shell(SE4_P6, 'printf "%s" "$PIN_PROTON_LAUNCHER_POLICY${PIN_DXVK_LEGACY_COMMIT:-}"',
                       PIN_PROTON_LAUNCHER_POLICY="dxvk-legacy",
                       PIN_DXVK_LEGACY_COMMIT="2cae043bdf767c8a7a2e0ee8d41537acfe773e8e")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "upstream")

    def test_repeated_load_does_not_leak_dxvk_legacy_keys(self):
        result = shell(DUAL, 'PINNED_GE_CONFIG="$1"; pinned_ge_load_config; '
                       'printf "[%s][%s]" "$PIN_PROTON_LAUNCHER_POLICY" "${PIN_DXVK_LEGACY_COMMIT:-}"', SE4_P6)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "[upstream][]")

    def test_real_launchers_when_local_sources_are_available(self):
        source = ROOT / "worktrees/ge-proton11-6-se1-rtsp"
        prior = ROOT / "worktrees/ge-proton11-6-a323-rtsp/proton"
        if not (source / "proton").is_file() or not prior.is_file():
            self.skipTest("local comparison sources not materialized")
        accepted = shell(SE1, 'pinned_ge_require_upstream_launcher "$1" "$2"',
                         source, source / "proton")
        rejected = shell(SE1, 'pinned_ge_require_upstream_launcher "$1" "$2"',
                         source, prior)
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("launcher differs", rejected.stderr)
        self.assertIn("PROTON_XR_MODE", prior.read_text())
        self.assertNotIn("PROTON_XR_MODE", (source / "proton").read_text())


if __name__ == "__main__":
    unittest.main(verbosity=2)
