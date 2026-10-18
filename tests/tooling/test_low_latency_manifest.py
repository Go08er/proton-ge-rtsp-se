#!/usr/bin/env python3
"""Reproduce GE's absolute-path packaging defect without a build or Vulkan."""
import json
from pathlib import Path
import runpy
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
MODULE = runpy.run_path(str(ROOT / 'scripts/normalize-ge-low-latency-manifest.py'))
LIBRARY, MANIFEST, normalize = (MODULE[key] for key in ('LIBRARY', 'MANIFEST', 'normalize'))


class LowLatencyManifest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='rtsp-layer-manifest-')
        self.addCleanup(temp.cleanup)
        self.tool = Path(temp.name)
        self.path = self.tool / MANIFEST
        self.path.parent.mkdir(parents=True)
        self.layer = {'name': 'VK_LAYER_KORTHOS_low_latency',
                      'library_path': '/tmp/old-build/dst-layer/lib/' + LIBRARY,
                      'enable_environment': {'LOW_LATENCY_LAYER': '1'}}
        self.path.write_text(json.dumps({'layer': self.layer}, indent=4) + '\n')
        self.library = self.tool / 'files/lib/x86_64-linux-gnu' / LIBRARY
        self.library.parent.mkdir(parents=True)
        self.library.touch()

    def test_old_manifest_fails_then_relocatable_manifest_passes(self):
        before = self.path.read_text()
        with self.assertRaisesRegex(ValueError, 'non-relocatable'):
            normalize(self.tool, check=True)
        self.assertEqual(self.path.read_text(), before)
        normalize(self.tool)
        normalize(self.tool, check=True)
        self.assertEqual(self.path.read_text(), before.replace(
            json.dumps(self.layer['library_path']), json.dumps(LIBRARY)))
        once = self.path.read_bytes()
        normalize(self.tool)
        self.assertEqual(self.path.read_bytes(), once)

    def test_missing_library_is_not_hidden_by_rewrite(self):
        self.library.unlink()
        with self.assertRaisesRegex(ValueError, 'library is missing'):
            normalize(self.tool)

    def test_unexpected_library_is_not_rewritten(self):
        self.layer['library_path'] = '/tmp/other.so'
        self.path.write_text(json.dumps({'layer': self.layer}))
        before = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'unexpected'):
            normalize(self.tool)
        self.assertEqual(self.path.read_bytes(), before)

    def test_build_and_artifact_verification_use_the_helper(self):
        for filename in ('build-pinned-ge.sh', 'verify-pinned-ge-artifact.sh'):
            script = (ROOT / 'scripts' / filename).read_text()
            self.assertIn('normalize-ge-low-latency-manifest.py', script)
            self.assertIn('"$PIN_WITHOUT_VKLAYERS" == 0', script)


if __name__ == '__main__':
    unittest.main(verbosity=2)
