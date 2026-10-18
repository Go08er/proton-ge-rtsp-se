#!/usr/bin/env python3
"""Machine-only P19a is exactly P18 plus the seven accepted, frozen fixes."""
import hashlib
from pathlib import Path
import tempfile
import unittest
from test_preparation_profile import ROOT, check
from test_p18_profile import entries

ACCEPTED = (
    ('0063-sr5-terminal-reader-errors.patch', '22a186770d6a8d8282a53aca8f00b61ab1047d692a69f0dc852f574522d21a21'),
    ('0064-sr3-propagate-output-layout.patch', 'b6a2099ec8d3b607f71e1fb66d33b6c60db80e2ff6477f82538d477a19eaff79'),
    ('0065-sr1-preserve-source-timestamps.patch', 'a6cc6ef8f110c9b61d46bd7d08b7ed39bcdbeffb079bba02326ddb3596554137'),
    ('0066-sr4-forward-reconnect-events.patch', '1a9502b60389ff7c811dc49afe55e0b935dfdf693469aa5b27d1b46a57daa13d'),
    ('0067-sr6-complete-prestart-flush.patch', '1edc621679fad20bb7c33478f753d442bf3b37738b19b4d0e4a844037d28ba43'),
    ('0068-sr2-preserve-leading-mp4-audio.patch', 'f9226466443cd30299b7cc6163a7ef5bfd094ab00ada3a7cedd54f84e8a84934'),
    ('0069-session-retain-stopped-sink-demand.patch', '943724acd5868761593a814c7ba800467c55d53ca07bf0c3cdffd75bfa4180b1'),
)


class P19aProfileTests(unittest.TestCase):
    def test_exact_accepted_delta_and_bytes(self):
        self.assertEqual(entries('p19a'), entries('p18') +
                         ['ge-proton11-7-se2-p19a/' + name for name, _ in ACCEPTED])
        for name, digest in ACCEPTED:
            self.assertEqual(hashlib.sha256((ROOT/'patches/ge-proton11-7-se2-p19a'/name).read_bytes()).hexdigest(), digest)
        for name in ('p18', 'p19a'):
            result = check(ROOT/f'config/ge-proton11-7-se2-{name}.env',
                           ROOT/f'patches/series-ge-proton11-7-se2-{name}')
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_only_pin_identity_changes(self):
        def pin(name):
            return dict(line.split('=', 1) for line in
                        (ROOT/f'config/ge-proton11-7-se2-{name}.env').read_text().splitlines()
                        if line and not line.startswith('#'))
        old, new = pin('p18'), pin('p19a')
        self.assertEqual(set(old), set(new))
        self.assertEqual({k for k in old if old[k] != new[k]}, {'PIN_ID', 'PIN_BUILD_NAME'})
        self.assertEqual(new['PIN_PACKAGE_RELEASE'], '0')

    def test_missing_reordered_extra_or_historical_series_rejected(self):
        pin = ROOT/'config/ge-proton11-7-se2-p19a.env'
        good = entries('p19a')
        with tempfile.TemporaryDirectory(prefix='rtsp-p19a-profile-') as directory:
            bad = Path(directory)/'series'
            variants = [good[:i] + good[i+1:] for i in range(55, 62)]
            variants += [good[:-2] + good[-2:][::-1], good + [good[-1]], entries('p18')]
            for rows in variants:
                bad.write_text('\n'.join(rows)+'\n')
                self.assertNotEqual(check(pin, bad).returncode, 0)
        self.assertNotEqual(check(ROOT/'config/ge-proton11-7-se2-p18.env',
                                 ROOT/'patches/series-ge-proton11-7-se2-p19a').returncode, 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
