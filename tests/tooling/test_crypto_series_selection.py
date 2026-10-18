#!/usr/bin/env python3
"""Release-specific crypto selection; no source checkout, build or network."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]
NEW = ROOT / 'config/ge-proton11-9-se2-p20.env'
OLD = ROOT / 'config/ge-proton11-7-se2-p19b2.env'


def shell(body, *args, pin=NEW):
    return subprocess.run(['bash', '-eu', '-c',
        'source "$1/scripts/pinned-ge-common.sh"; PINNED_GE_CONFIG="$2"; pinned_ge_load_config; ' + body,
        'crypto-selection-test', str(ROOT), str(pin), *map(str, args)],
        capture_output=True, text=True, timeout=10)


class CryptoSelection(unittest.TestCase):
    def test_new_and_historical_records_are_independent(self):
        for pin, expected in ((NEW, 'ge-proton11-9/0001-'), (OLD, '0001-')):
            result = shell('s="$(pinned_ge_ffmpeg_crypto_build_series)"; '
                'pinned_ge_ffmpeg_crypto_build_patch_record "$PINNED_GE_ROOT/patches/ffmpeg-build" "$s"', pin=pin)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(result.stdout.startswith(expected), result.stdout)

    def test_reloading_old_pin_clears_new_selection(self):
        result = shell('PINNED_GE_CONFIG="$3"; pinned_ge_load_config; '
            'test -z "${PIN_FFMPEG_CRYPTO_BUILD_SERIES:-}"; pinned_ge_ffmpeg_crypto_build_series', OLD)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), str(ROOT / 'patches/ffmpeg-build/series'))

    def test_unsafe_selection_is_rejected(self):
        for value in ('/tmp/series', '../series', 'patches/ffmpeg-build/series/../series',
                      'patches/ffmpeg-build/series-a/b', 'patches/ffmpeg-build/series-a b'):
            with self.subTest(value=value):
                self.assertNotEqual(shell('PIN_FFMPEG_CRYPTO_BUILD_SERIES="$3"; '
                    'pinned_ge_ffmpeg_crypto_build_series', value).returncode, 0)

    def test_selection_does_not_bypass_pinned_hash(self):
        result = shell('PIN_FFMPEG_CRYPTO_BUILD_SERIES_SHA256=' + '0' * 64 + '; '
            's="$(pinned_ge_ffmpeg_crypto_build_series)"; '
            'pinned_ge_ffmpeg_crypto_build_patch_record "$PINNED_GE_ROOT/patches/ffmpeg-build" "$s"')
        self.assertNotEqual(result.returncode, 0)

    def test_security_series_keeps_its_own_four_fixes(self):
        result = shell('pinned_ge_ffmpeg_security_series_records "$PINNED_GE_ROOT/patches/ffmpeg-security" '
            '"$PINNED_GE_ROOT/patches/ffmpeg-security/series"')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(result.stdout.splitlines()), 4)
        self.assertNotIn('enable-crypto', result.stdout)


if __name__ == '__main__':
    unittest.main(verbosity=2)
