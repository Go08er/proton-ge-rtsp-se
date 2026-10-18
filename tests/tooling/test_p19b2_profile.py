#!/usr/bin/env python3
"""The header-registration repair cannot alter the frozen P19b payload."""
from pathlib import Path
import tempfile
import unittest

from test_preparation_profile import ROOT, check
from test_p18_profile import entries


class P19b2ProfileTests(unittest.TestCase):
    def test_pin_delta_and_profiles(self):
        def fields(name):
            return dict(line.split('=', 1) for line in
                        (ROOT / f'config/ge-proton11-7-se2-{name}.env').read_text().splitlines()
                        if line and not line.startswith('#'))
        old, new = fields('p19b'), fields('p19b2')
        self.assertEqual(set(old), set(new))
        self.assertEqual({key for key in old if old[key] != new[key]},
                         {'PIN_ID', 'PIN_BUILD_NAME'})
        for name in ('p19b', 'p19b2'):
            result = check(ROOT / f'config/ge-proton11-7-se2-{name}.env',
                           ROOT / f'patches/series-ge-proton11-7-se2-{name}')
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_only_appended_registration(self):
        old, new = entries('p19b'), entries('p19b2')
        self.assertEqual(new[:-1], old)
        self.assertEqual(len(new), 70)
        patch = (ROOT / 'patches' / new[-1]).read_text().splitlines()
        self.assertEqual([line for line in patch if line.startswith('+') and not line.startswith('+++')],
                         ['+\twine/mforigin.h \\'])
        self.assertEqual([line for line in patch if line.startswith('-') and not line.startswith('---')], [])

    def test_wrong_series_rejected(self):
        good = entries('p19b2')
        pin = ROOT / 'config/ge-proton11-7-se2-p19b2.env'
        with tempfile.TemporaryDirectory(prefix='rtsp-p19b2-profile-') as directory:
            path = Path(directory) / 'series'
            for rows in (good[:-1], good[1:], good[:-2] + good[-2:][::-1], good + [good[-1]]):
                path.write_text('\n'.join(rows) + '\n')
                self.assertNotEqual(check(pin, path).returncode, 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
