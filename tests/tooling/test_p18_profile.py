#!/usr/bin/env python3
"""P18 is exactly P17 + 0062; historical profiles remain immutable."""
from pathlib import Path
import tempfile
import unittest
from test_preparation_profile import ROOT, check


def entries(name):
    return [line for line in (ROOT/f'patches/series-ge-proton11-7-se2-{name}').read_text().splitlines()
            if line and not line.startswith('#')]


class P18ProfileTests(unittest.TestCase):
    def test_profiles_and_exact_single_patch_delta(self):
        for name in ('p16', 'p17', 'p18'):
            result = check(ROOT/f'config/ge-proton11-7-se2-{name}.env',
                           ROOT/f'patches/series-ge-proton11-7-se2-{name}')
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(entries('p18')), 55)
        self.assertEqual(entries('p18'), entries('p17') +
            ['proposed/0062-winedmo-use-zero-based-parser-byte-position.patch'])

    def test_pin_only_changes_identity(self):
        def pin(name):
            return dict(line.split('=', 1) for line in
                (ROOT/f'config/ge-proton11-7-se2-{name}.env').read_text().splitlines()
                if line and not line.startswith('#'))
        old, new = pin('p17'), pin('p18')
        self.assertEqual(set(old), set(new))
        self.assertEqual({k for k in old if old[k] != new[k]},
                         {'PIN_ID', 'PIN_BUILD_NAME'})

    def test_missing_reordered_or_extra_patch_is_rejected(self):
        pin = ROOT/'config/ge-proton11-7-se2-p18.env'
        good = entries('p18')
        with tempfile.TemporaryDirectory(prefix='rtsp-p18-profile-') as directory:
            bad = Path(directory)/'series'
            for rows in (good[:-1], good[:-2] + good[-2:][::-1], good + [good[-1]]):
                bad.write_text('\n'.join(rows)+'\n')
                self.assertNotEqual(check(pin, bad).returncode, 0)
        self.assertNotEqual(check(ROOT/'config/ge-proton11-7-se2-p17.env',
                                 ROOT/'patches/series-ge-proton11-7-se2-p18').returncode, 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
