#!/usr/bin/env python3
"""The clean P19b composition has a fixed reviewed byte-and-order identity."""
from pathlib import Path
import tempfile
import unittest

from test_preparation_profile import ROOT, check
from test_p18_profile import entries


class P19bProfileTests(unittest.TestCase):
    pin = ROOT / 'config/ge-proton11-7-se2-p19b.env'
    series = ROOT / 'patches/series-ge-proton11-7-se2-p19b'

    def test_reviewed_profile_and_historical_control(self):
        for name in ('p19a', 'p19b'):
            result = check(ROOT / f'config/ge-proton11-7-se2-{name}.env',
                           ROOT / f'patches/series-ge-proton11-7-se2-{name}')
            self.assertEqual(result.returncode, 0, result.stderr)
        rows = entries('p19b')
        self.assertEqual(len(rows), 69)
        self.assertFalse(any(Path(row).name.startswith(('0019-', '0060-')) for row in rows))

    def test_missing_reordered_extra_and_old_series_rejected(self):
        good = entries('p19b')
        variants = [good[:i] + good[i + 1:] for i in range(len(good))]
        variants += [good[:-2] + good[-2:][::-1], good + [good[-1]], entries('p19a')]
        with tempfile.TemporaryDirectory(prefix='rtsp-p19b-profile-') as directory:
            series = Path(directory) / 'series'
            for rows in variants:
                series.write_text('\n'.join(rows) + '\n')
                self.assertNotEqual(check(self.pin, series).returncode, 0)
        self.assertNotEqual(check(ROOT / 'config/ge-proton11-7-se2-p19a.env',
                                 self.series).returncode, 0)

    def test_changed_or_absent_companions_rejected(self):
        original = self.pin.read_text().splitlines()
        with tempfile.TemporaryDirectory(prefix='rtsp-p19b-pin-') as directory:
            pin = Path(directory) / 'candidate.env'
            for field in ('PIN_FFMPEG_MPEGVIDEO_PATCH_SHA256',
                          'PIN_FFMPEG_MPEGVIDEO_MAKEFILE_BLOB',
                          'PIN_FFMPEG_HTTP_FILESIZE_PATCH_SHA256',
                          'PIN_FFMPEG_HTTP_FILESIZE_HTTP_BLOB',
                          'PIN_FFMPEG_HLS_EARLY_SEEK_PATCH_SHA256',
                          'PIN_FFMPEG_HLS_EARLY_SEEK_HLS_BLOB'):
                for value in ('', '0' * (64 if field.endswith('SHA256') else 40)):
                    pin.write_text('\n'.join(field + '=' + value if line.startswith(field + '=')
                                             else line for line in original) + '\n')
                    self.assertNotEqual(check(pin, self.series).returncode, 0, field)


if __name__ == '__main__':
    unittest.main(verbosity=2)
