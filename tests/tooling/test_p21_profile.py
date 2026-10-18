#!/usr/bin/env python3
"""P21 adoption identity controls, using the real extracted profile checks.

No source preparation, compilation, container, playback or network is run.
"""
import hashlib
from pathlib import Path
import tempfile
import unittest

from test_preparation_profile import ROOT, check


def entries(name):
    return [line for raw in (ROOT / f"patches/series-ge-proton11-9-se2-{name}").read_text().splitlines()
            if (line := raw.strip()) and not line.startswith("#")]


def fields(name):
    return dict(line.split("=", 1) for line in
                (ROOT / f"config/ge-proton11-9-se2-{name}.env").read_text().splitlines()
                if line and not line.startswith("#"))


class P21ProfileTests(unittest.TestCase):
    def test_both_immutable_profiles_pass_and_cross_selection_fails(self):
        for name in ("p20", "p21"):
            pin = ROOT / f"config/ge-proton11-9-se2-{name}.env"
            series = ROOT / f"patches/series-ge-proton11-9-se2-{name}"
            result = check(pin, series)
            self.assertEqual(result.returncode, 0, result.stderr)
            other = "p21" if name == "p20" else "p20"
            result = check(pin, ROOT / f"patches/series-ge-proton11-9-se2-{other}")
            self.assertNotEqual(result.returncode, 0, "cross-selected immutable series accepted")

    def test_pin_delta_keeps_exact_same_base_companions_and_half_cpu(self):
        old, new = fields("p20"), fields("p21")
        self.assertEqual(set(old), set(new))
        self.assertEqual({key for key in old if old[key] != new[key]}, {"PIN_ID", "PIN_BUILD_NAME"})
        for name, expected in (
                ("p20", "05f43b644f619e07b0d55de8a8d1169422c0dbd147f048837dda47dcc099e522"),
                ("p21", "7d7dcd9901bfdbfec2a4a848033396f49f6f197d5874eb569c9d0c8ef5b09151")):
            self.assertEqual(hashlib.sha256((ROOT / f"config/ge-proton11-9-se2-{name}.env").read_bytes()).hexdigest(), expected)
        self.assertEqual((new["PIN_DEFAULT_JOBS"], new["PIN_DEFAULT_MAKE_JOBS"],
                          new["PIN_DEFAULT_NINJA_JOBS"], new["PIN_PACKAGE_RELEASE"]),
                         ("8", "4", "2", "0"))

    def test_only_first_two_components_change(self):
        old, new = entries("p20"), entries("p21")
        self.assertEqual(len(old), 13)
        self.assertEqual([row.replace("-p21/", "-p20/") for row in new], old)
        for index, (before, after) in enumerate(zip(old, new)):
            old_bytes, new_bytes = ((ROOT / "patches" / entry).read_bytes() for entry in (before, after))
            self.assertEqual(old_bytes == new_bytes, index >= 2, after)
        self.assertEqual([hashlib.sha256((ROOT / "patches" / row).read_bytes()).hexdigest()
                          for row in new[:2]], [
            "60435fb8c59ab7c6e50d3cf1c42f8f9580bc263829507c24aaa26947202ab918",
            "1b615a317fb6d1405385fb1df7dcd83ad1886398506ab282af071718b3e749d1"])

    def test_missing_duplicate_reordered_and_mixed_components_rejected(self):
        good = entries("p21")
        pin = ROOT / "config/ge-proton11-9-se2-p21.env"
        variants = [good[:i] + good[i + 1:] for i in range(len(good))]
        variants += [good + [good[-1]], good[:-2] + good[-2:][::-1],
                     [good[0].replace("-p21/", "-p20/")] + good[1:]]
        with tempfile.TemporaryDirectory(prefix="rtsp-p21-profile-") as directory:
            series = Path(directory) / "series"
            for rows in variants:
                series.write_text("\n".join(rows) + "\n")
                result = check(pin, series)
                self.assertNotEqual(result.returncode, 0, rows)

    def test_changed_pin_cannot_fall_back_to_old_profile(self):
        pin = ROOT / "config/ge-proton11-9-se2-p21.env"
        series = ROOT / "patches/series-ge-proton11-9-se2-p21"
        with tempfile.TemporaryDirectory(prefix="rtsp-p21-pin-") as directory:
            changed = Path(directory) / "candidate.env"
            for old, new in (("PIN_ID=ge-proton11-9-se2-p21", "PIN_ID=ge-proton11-9-se2-p20"),
                             ("PIN_BUILD_NAME=proton-ge-11-9-rtsp-se2-p21", "PIN_BUILD_NAME=proton-ge-11-9-rtsp-se2-p20"),
                             ("PIN_WITHOUT_NVIDIA_LIBS=0", "PIN_WITHOUT_NVIDIA_LIBS=1"),
                             ("PIN_PACKAGE_RELEASE=0", "PIN_PACKAGE_RELEASE=1"),
                             ("PIN_DEFAULT_MAKE_JOBS=4", "PIN_DEFAULT_MAKE_JOBS=8")):
                original = pin.read_text()
                self.assertEqual(original.count(old), 1)
                changed.write_text(original.replace(old, new))
                self.assertNotEqual(check(changed, series).returncode, 0, old)


if __name__ == "__main__":
    unittest.main(verbosity=2)
