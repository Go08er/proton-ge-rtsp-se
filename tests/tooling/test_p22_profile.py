#!/usr/bin/env python3
"""Bind P22's one-module change without weakening immutable older profiles.

Exercises the actual preparation profile checks, without preparing or building.
"""
import hashlib
from pathlib import Path
import tempfile
import unittest

from test_preparation_profile import ROOT, check
from test_p21_profile import entries, fields


class P22ProfileTests(unittest.TestCase):
    def test_exact_profiles_pass_and_all_cross_selections_fail(self):
        for name in ("p20", "p21", "p22"):
            pin = ROOT / f"config/ge-proton11-9-se2-{name}.env"
            for selected in ("p20", "p21", "p22"):
                result = check(pin, ROOT / f"patches/series-ge-proton11-9-se2-{selected}")
                self.assertEqual(result.returncode == 0, name == selected,
                                 (name, selected, result.stderr))

    def test_exact_pin_preserves_base_companions_full_payload_and_half_cpu(self):
        old, new = fields("p21"), fields("p22")
        self.assertEqual(set(old), set(new))
        self.assertEqual({key for key in old if old[key] != new[key]},
                         {"PIN_ID", "PIN_BUILD_NAME"})
        pin = ROOT / "config/ge-proton11-9-se2-p22.env"
        self.assertEqual(hashlib.sha256(pin.read_bytes()).hexdigest(),
                         "75990d9bd53b136a352ac7000ae8f963f014f0f3991fe074016336fcbeff0edb")
        self.assertEqual(tuple(new[key] for key in (
            "PIN_DEFAULT_JOBS", "PIN_DEFAULT_MAKE_JOBS", "PIN_DEFAULT_NINJA_JOBS",
            "PIN_PACKAGE_RELEASE", "PIN_WITHOUT_NVIDIA_LIBS", "PIN_WITHOUT_VKLAYERS",
            "PIN_PROTON_LAUNCHER_POLICY")), ("8", "4", "2", "0", "0", "0", "upstream"))

    def test_only_video_frame_sink_component_changes(self):
        old, new = entries("p21"), entries("p22")
        self.assertEqual(len(old), 13)
        self.assertEqual([row.replace("-p22/", "-p21/") for row in new], old)
        for index, (before, after) in enumerate(zip(old, new)):
            before_bytes, after_bytes = ((ROOT / "patches" / entry).read_bytes()
                                        for entry in (before, after))
            self.assertEqual(before_bytes == after_bytes, index != 8, after)
        changed = (ROOT / "patches" / new[8]).read_bytes()
        self.assertEqual(hashlib.sha256(changed).hexdigest(),
                         "d9bbd7e6064203309354f179dcdc8af6e8799610567acb1cef659b410f8d2067")
        self.assertEqual([line for line in changed.decode().splitlines()
                          if line.startswith("diff --git ")], [
            "diff --git a/dlls/mfmediaengine/video_frame_sink.c b/dlls/mfmediaengine/video_frame_sink.c"])

    def test_missing_duplicate_reordered_and_mixed_components_fail(self):
        good = entries("p22")
        pin = ROOT / "config/ge-proton11-9-se2-p22.env"
        variants = [good[:i] + good[i + 1:] for i in range(len(good))]
        variants += [good + [good[-1]], good[:-2] + good[-2:][::-1],
                     good[:8] + [good[8].replace("-p22/", "-p21/")] + good[9:]]
        with tempfile.TemporaryDirectory(prefix="rtsp-p22-series-") as directory:
            series = Path(directory) / "series"
            for rows in variants:
                series.write_text("\n".join(rows) + "\n")
                self.assertNotEqual(check(pin, series).returncode, 0, rows)

    def test_changed_pin_cannot_inherit_an_older_profile(self):
        pin = ROOT / "config/ge-proton11-9-se2-p22.env"
        series = ROOT / "patches/series-ge-proton11-9-se2-p22"
        with tempfile.TemporaryDirectory(prefix="rtsp-p22-pin-") as directory:
            changed = Path(directory) / "candidate.env"
            for old, new in (("PIN_ID=ge-proton11-9-se2-p22", "PIN_ID=ge-proton11-9-se2-p21"),
                             ("PIN_BUILD_NAME=proton-ge-11-9-rtsp-se2-p22", "PIN_BUILD_NAME=proton-ge-11-9-rtsp-se2-p21"),
                             ("PIN_WITHOUT_NVIDIA_LIBS=0", "PIN_WITHOUT_NVIDIA_LIBS=1"),
                             ("PIN_PACKAGE_RELEASE=0", "PIN_PACKAGE_RELEASE=1"),
                             ("PIN_DEFAULT_MAKE_JOBS=4", "PIN_DEFAULT_MAKE_JOBS=8")):
                original = pin.read_text()
                self.assertEqual(original.count(old), 1)
                changed.write_text(original.replace(old, new))
                self.assertNotEqual(check(changed, series).returncode, 0, old)


if __name__ == "__main__":
    unittest.main(verbosity=2)
