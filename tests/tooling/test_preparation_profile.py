#!/usr/bin/env python3
"""Exercise the real preparation pin/series checks without a source tree or build.

The two extracted shell blocks are the checks used by verify-preparation.sh;
only unrelated fixture execution is omitted. Temporary malformed pins/series
must fail, and immutable historical selections must continue to pass.
"""

from pathlib import Path
import re
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
VERIFY = (ROOT / "scripts/verify-preparation.sh").read_text()
PIN_CHECK = VERIFY.split("\npinned_ge_load_config\n", 1)[1].split("\ndefault_schedule=", 1)[0]
SERIES_CHECK = VERIFY.split('\nseries_entries="', 1)[1].split("\ncurrent_series_digest=", 1)[0]
SERIES_CHECK = 'series_entries="' + SERIES_CHECK


def check(config, series):
    script = ('ROOT_DIR="$1"; PINNED_GE_CONFIG="$2"; PATCH_SERIES="$3"\n'
              'source "$ROOT_DIR/scripts/pinned-ge-common.sh"\n'
              'fail() { printf "ERROR: %s\\n" "$*" >&2; exit 1; }\n'
              'pinned_ge_load_config\n' + PIN_CHECK + "\n" + SERIES_CHECK)
    return subprocess.run(["bash", "-eu", "-c", script, "profile-test", str(ROOT),
                           str(config), str(series)], text=True, capture_output=True)


class PreparationProfiles(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="rtsp-preparation-profile-")
        self.addCleanup(temp.cleanup)
        self.temp = Path(temp.name)
        self.pin = ROOT / "config/ge-proton11-6-se2-p1.env"
        self.series = ROOT / "patches/series-ge-proton11-6-se2-p1"

    def changed_pin(self, field, value):
        path = self.temp / "candidate.env"
        lines = self.pin.read_text().splitlines()
        self.assertTrue(any(line.startswith(field + "=") for line in lines))
        path.write_text("\n".join(field + "=" + value if line.startswith(field + "=")
                                  else line for line in lines) + "\n")
        return path

    def test_p1_exact_profile_passes(self):
        result = check(self.pin, self.series)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_p2_exact_profile_and_module_boundaries(self):
        pin = ROOT / 'config/ge-proton11-6-se2-p2.env'
        series = ROOT / 'patches/series-ge-proton11-6-se2-p2'
        result = check(pin, series)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotEqual(check(self.pin, series).returncode, 0)
        self.assertNotEqual(check(pin, self.series).returncode, 0)
        entries = [line for line in series.read_text().splitlines()
                   if line and not line.startswith('#')]
        for lines in (entries[:-1], entries[:-2] + entries[-2:][::-1],
                      entries[:-1] + [entries[-2]]):
            malformed = self.temp / 'p2-series'
            malformed.write_text('\n'.join(lines) + '\n')
            self.assertNotEqual(check(pin, malformed).returncode, 0)

    def test_historical_profiles_still_pass(self):
        pin = ROOT / 'config/ge-proton11-6-se2-p3.env'
        series = ROOT / 'patches/series-ge-proton11-6-se2-p3'
        self.assertEqual(check(pin, series).returncode, 0)
        self.assertNotEqual(check(pin, ROOT / 'patches/series-ge-proton11-6-se2-p2').returncode, 0)
        self.assertNotEqual(check(ROOT / 'config/ge-proton11-6-se2-p2.env', series).returncode, 0)
        for name, series in (
                ("ge-master-snapshot-20260723-a312", "series-ge-proton11-3"),
                ("ge-proton11-6-se1", "series-ge-proton11-6-se1"),
                ("ge-proton11-6-a323", "series-ge-proton11-6-a323"),
                ("ge-proton11-3-a316", "series-ge-proton11-3")):
            with self.subTest(pin=name):
                result = check(ROOT / "config" / (name + ".env"), ROOT / "patches" / series)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_p4_requires_only_its_additional_topology_fix(self):
        pin = ROOT / 'config/ge-proton11-6-se2-p4.env'
        series = ROOT / 'patches/series-ge-proton11-6-se2-p4'
        result = check(pin, series)
        self.assertEqual(result.returncode, 0, result.stderr)
        p3_pin = ROOT / 'config/ge-proton11-6-se2-p3.env'
        p3_series = ROOT / 'patches/series-ge-proton11-6-se2-p3'
        self.assertNotEqual(check(pin, p3_series).returncode, 0)
        self.assertNotEqual(check(p3_pin, series).returncode, 0)

    def test_full_ge_counts_and_flags_are_not_optional(self):
        for field, value in (("PIN_WITHOUT_NVIDIA_LIBS", "1"),
                             ("PIN_WITHOUT_VKLAYERS", "1"),
                             ("PIN_REGISTERED_SUBMODULE_COUNT", "32"),
                             ("PIN_GITLINK_COUNT", "41"),
                             ("PIN_UNMAPPED_OPTIONAL_GITLINK_COUNT", "10")):
            with self.subTest(field=field):
                result = check(self.changed_pin(field, value), self.series)
                self.assertNotEqual(result.returncode, 0)

    def test_p5_exact_union_and_companion_are_required(self):
        self.pin = ROOT / 'config/ge-proton11-6-se2-p5.env'
        series = ROOT / 'patches/series-ge-proton11-6-se2-p5'
        result = check(self.pin, series)
        self.assertEqual(result.returncode, 0, result.stderr)
        p4_pin = ROOT / 'config/ge-proton11-6-se2-p4.env'
        p4_series = ROOT / 'patches/series-ge-proton11-6-se2-p4'
        self.assertNotEqual(check(self.pin, p4_series).returncode, 0)
        self.assertNotEqual(check(p4_pin, series).returncode, 0)
        for field, value in (('PIN_FFMPEG_RTSPS_PATCH_SHA256', ''),
                             ('PIN_FFMPEG_RTSPS_PATCH_SHA256', '0' * 64),
                             ('PIN_FFMPEG_RTSPS_RTSP_BLOB', ''),
                             ('PIN_FFMPEG_RTSPS_RTSP_BLOB', '0' * 40)):
            with self.subTest(field=field, value=value):
                self.assertNotEqual(check(self.changed_pin(field, value), series).returncode, 0)
        entries = [line for line in series.read_text().splitlines()
                   if line and not line.startswith('#')]
        for index in range(len(entries) - 7, len(entries)):
            missing = self.temp / 'missing-module'
            missing.write_text('\n'.join(entries[:index] + entries[index + 1:]) + '\n')
            self.assertNotEqual(check(self.pin, missing).returncode, 0)

    def test_p4_cannot_silently_gain_secure_rtsp_companion(self):
        pin = self.temp / 'p4-with-companion.env'
        text = (ROOT / 'config/ge-proton11-6-se2-p4.env').read_text()
        text += '\n'.join(line for line in
                         (ROOT / 'config/ge-proton11-6-se2-p5.env').read_text().splitlines()
                         if line.startswith('PIN_FFMPEG_RTSPS_')) + '\n'
        pin.write_text(text)
        result = check(pin, ROOT / 'patches/series-ge-proton11-6-se2-p4')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('historical SE2 subsets', result.stderr)

    def test_p6_requires_flac_and_http_seek_companion(self):
        self.pin = ROOT / 'config/ge-proton11-6-se2-p6.env'
        series = ROOT / 'patches/series-ge-proton11-6-se2-p6'
        result = check(self.pin, series)
        self.assertEqual(result.returncode, 0, result.stderr)
        p5_pin = ROOT / 'config/ge-proton11-6-se2-p5.env'
        p5_series = ROOT / 'patches/series-ge-proton11-6-se2-p5'
        self.assertNotEqual(check(self.pin, p5_series).returncode, 0)
        self.assertNotEqual(check(p5_pin, series).returncode, 0)
        for field, value in (('PIN_FFMPEG_HTTP_SEEK_PATCH_SHA256', ''),
                             ('PIN_FFMPEG_HTTP_SEEK_PATCH_SHA256', '0' * 64),
                             ('PIN_FFMPEG_HTTP_SEEK_HTTP_BLOB', ''),
                             ('PIN_FFMPEG_HTTP_SEEK_HTTP_BLOB', '0' * 40)):
            with self.subTest(field=field, value=value):
                self.assertNotEqual(check(self.changed_pin(field, value), series).returncode, 0)

    def test_p5_cannot_silently_gain_http_seek_companion(self):
        pin = self.temp / 'p5-with-http.env'
        text = (ROOT / 'config/ge-proton11-6-se2-p5.env').read_text()
        text += '\n'.join(line for line in
                         (ROOT / 'config/ge-proton11-6-se2-p6.env').read_text().splitlines()
                         if line.startswith('PIN_FFMPEG_HTTP_SEEK_')) + '\n'
        pin.write_text(text)
        result = check(pin, ROOT / 'patches/series-ge-proton11-6-se2-p5')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('historical SE2 subsets', result.stderr)

    def test_p7_requires_the_exact_three_lifecycle_repairs(self):
        self.pin = ROOT / 'config/ge-proton11-6-se2-p7.env'
        series = ROOT / 'patches/series-ge-proton11-6-se2-p7'
        p6_pin = ROOT / 'config/ge-proton11-6-se2-p6.env'
        p6_series = ROOT / 'patches/series-ge-proton11-6-se2-p6'
        self.assertEqual(check(self.pin, series).returncode, 0)
        self.assertEqual(check(p6_pin, p6_series).returncode, 0)
        self.assertNotEqual(check(self.pin, p6_series).returncode, 0)
        self.assertNotEqual(check(p6_pin, series).returncode, 0)
        entries = [line for line in series.read_text().splitlines()
                   if line and not line.startswith('#')]
        previous = [line for line in p6_series.read_text().splitlines()
                    if line and not line.startswith('#')]
        self.assertEqual(len(entries), 39)
        self.assertEqual(entries[:-3], previous)
        self.assertEqual(entries[-3:], [
            'proposed/0043-mf-rearm-audio-sample-demand-after-flush.patch',
            'proposed/0044-mf-initialize-sar-marker-entry-before-copy.patch',
            'proposed/0045-mf-reset-seek-eos-and-discriminate-sink-markers.patch',
        ])
        malformed = self.temp / 'p7-series'
        mutations = [entries[:i] + entries[i + 1:] for i in range(36, 39)]
        mutations += [entries[:-3] + entries[-3:][::-1],
                      entries[:-1] + [entries[-2]], entries + [entries[-1]]]
        for lines in mutations:
            malformed.write_text('\n'.join(lines) + '\n')
            self.assertNotEqual(check(self.pin, malformed).returncode, 0)

    def test_p7_retains_exact_companions_and_candidate_identity(self):
        self.pin = ROOT / 'config/ge-proton11-6-se2-p7.env'
        series = ROOT / 'patches/series-ge-proton11-6-se2-p7'
        for field, value in (
                ('PIN_FFMPEG_HTTP_SEEK_PATCH_SHA256', '0' * 64),
                ('PIN_FFMPEG_HTTP_SEEK_HTTP_BLOB', ''),
                ('PIN_FFMPEG_RTSPS_PATCH_SHA256', ''),
                ('PIN_FFMPEG_RTSPS_RTSP_BLOB', '0' * 40),
                ('PIN_FFMPEG_DAV1D_MAKEFILE_BLOB', '0' * 40),
                ('PIN_FFMPEG_CRYPTO_BUILD_MAKEFILE_BLOB', '0' * 40),
                ('PIN_WITHOUT_NVIDIA_LIBS', '1'),
                ('PIN_WITHOUT_VKLAYERS', '1'),
                ('PIN_SOURCE_COMMIT', '0' * 40),
                ('PIN_BUILD_NAME', 'proton-ge-11-6-rtsp-se2-p6'),
                ('PIN_PROTON_LAUNCHER_POLICY', 'scoped-xrizer')):
            with self.subTest(field=field):
                self.assertNotEqual(check(self.changed_pin(field, value), series).returncode, 0)

    def test_p8_requires_master_refresh_and_both_new_modules(self):
        self.pin = ROOT / 'config/ge-master-20260913-se2-p8.env'
        series = ROOT / 'patches/series-ge-master-20260913-se2-p8'
        result = check(self.pin, series)
        self.assertEqual(result.returncode, 0, result.stderr)
        p7_pin = ROOT / 'config/ge-proton11-6-se2-p7.env'
        p7_series = ROOT / 'patches/series-ge-proton11-6-se2-p7'
        self.assertEqual(check(p7_pin, p7_series).returncode, 0)
        self.assertNotEqual(check(self.pin, p7_series).returncode, 0)
        self.assertNotEqual(check(p7_pin, series).returncode, 0)
        entries = [line for line in series.read_text().splitlines()
                   if line and not line.startswith('#')]
        previous = [line for line in p7_series.read_text().splitlines()
                    if line and not line.startswith('#')]
        self.assertEqual(len(entries), 41)
        refresh = '0032-winedmo-classify-http-media-after-probing.patch'
        index = previous.index('proposed/' + refresh)
        previous[index] = 'ge-master-20260913-se2-p8/' + refresh
        self.assertEqual(entries[:-2], previous)
        self.assertEqual(entries[-2:], [
            'ge-master-20260913-se2-p8/0046-mf-tests-preserve-held-marker-context.patch',
            'ge-master-20260913-se2-p8/0047-winedmo-expose-ac3-and-eac3-audio-decoding.patch',
        ])
        mutations = [entries[:i] + entries[i + 1:] for i in (index, 39, 40)]
        mutations += [entries[:-2] + entries[-2:][::-1], entries + [entries[-1]],
                      entries[:index] + ['proposed/' + refresh] + entries[index + 1:]]
        malformed = self.temp / 'p8-series'
        for lines in mutations:
            malformed.write_text('\n'.join(lines) + '\n')
            self.assertNotEqual(check(self.pin, malformed).returncode, 0)

    def test_p8_identity_postimages_and_full_ge_companions_are_exact(self):
        self.pin = ROOT / 'config/ge-master-20260913-se2-p8.env'
        series = ROOT / 'patches/series-ge-master-20260913-se2-p8'
        for field, value in (
                ('PIN_SOURCE_REF', '0' * 40),
                ('PIN_SOURCE_COMMIT', '0' * 40),
                ('PIN_SOURCE_TREE', '0' * 40),
                ('PIN_WINE_COMMIT', '0' * 40),
                ('PIN_BUILD_NAME', 'proton-ge-11-6-rtsp-se2-p7'),
                ('PIN_PROTON_LAUNCHER_POLICY', 'scoped-xrizer'),
                ('PIN_FFMPEG_CRYPTO_BUILD_MAKEFILE_BLOB', '284157f8120d27f8bb7291acf662e799cddf717b'),
                ('PIN_FFMPEG_DAV1D_MAKEFILE_BLOB', 'b0363a2bc898363dbe368e966248cad3738d2acc'),
                ('PIN_FFMPEG_DAV1D_PATCH_SHA256', ''),
                ('PIN_FFMPEG_RTSPS_PATCH_SHA256', ''),
                ('PIN_FFMPEG_RTSPS_RTSP_BLOB', '0' * 40),
                ('PIN_FFMPEG_HTTP_SEEK_PATCH_SHA256', '0' * 64),
                ('PIN_FFMPEG_HTTP_SEEK_HTTP_BLOB', ''),
                ('PIN_WITHOUT_NVIDIA_LIBS', '1'),
                ('PIN_WITHOUT_VKLAYERS', '1'),
                ('PIN_REGISTERED_SUBMODULE_COUNT', '32'),
                ('PIN_GITLINK_COUNT', '41'),
                ('PIN_UNMAPPED_OPTIONAL_GITLINK_COUNT', '10'),
                ('PIN_STEAMRT_IMAGE_ID', '0' * 64)):
            with self.subTest(field=field):
                self.assertNotEqual(check(self.changed_pin(field, value), series).returncode, 0)

    def test_p8_source_gates_preserve_control_direction(self):
        selector = re.search(r'if \[\[ \( .*ge-master-20260913-se2-p8.* && -n "\$\{PREPARED_SOURCE:-\}" \]\]; then', VERIFY)
        self.assertIsNotNone(selector)
        for candidate in range(8, 14):
            self.assertIn(f'ge-master-20260913-se2-p{candidate}', selector[0])
        self.assertIn('ge-proton11-7-se2-p14', selector[0])
        gates = VERIFY[selector.end():]
        gates = gates.split('\nfi\nPYTHONDONTWRITEBYTECODE', 1)[0]
        self.assertIn('tests/progressive-http-vod/test_http_policy_audit.py', gates)
        self.assertIn('tests/session-seek-eos/test_master_controls.py', gates)
        self.assertIn('--cc "$master_test_cc"', gates)
        self.assertIn('PREPARATION_TEST_CC', gates)
        # These two suites expect pre-patch trees; calling either on the final
        # integrated source would turn their old-negative evidence into a sham.
        self.assertNotIn('tests/parity-dolby-audio/test_extracted.py', gates)
        self.assertNotIn('tests/session-seek-eos/test_held_marker_context.py', gates)

    def test_p14_repin_preserves_payload_and_recomputes_identity(self):
        self.pin = ROOT / 'config/ge-proton11-7-se2-p14.env'
        series = ROOT / 'patches/series-ge-proton11-7-se2-p14'
        result = check(self.pin, series)
        self.assertEqual(result.returncode, 0, result.stderr)
        def entries(path):
            return [line for line in path.read_text().splitlines() if line and not line.startswith('#')]
        self.assertEqual(entries(series), entries(ROOT / 'patches/series-ge-master-20260913-se2-p13'))
        self.assertEqual(len(entries(series)), 50)
        for field, value in (
                ('PIN_SOURCE_REF', 'refs/tags/GE-Proton11-6'),
                ('PIN_SOURCE_COMMIT', '0b8c4d30d76abb74cc5cc4efdbadb410db00455f'),
                ('PIN_SOURCE_TREE', '0' * 40),
                ('PIN_WINE_COMMIT', '00e639898e01f8dd6fbee3851bd4c1e412c5b875'),
                ('PIN_FFMPEG_CRYPTO_BUILD_MAKEFILE_BLOB', '50af7a37bc7f97c3d8ba6cb560f529f7ec148199'),
                ('PIN_FFMPEG_DAV1D_MAKEFILE_BLOB', 'd928598c149e70b3af85f4d83d0012f28f6104b6'),
                ('PIN_REGISTERED_SUBMODULE_COUNT', '42'),
                ('PIN_GITLINK_COUNT', '42'),
                ('PIN_WITHOUT_NVIDIA_LIBS', '1'),
                ('PIN_WITHOUT_VKLAYERS', '1')):
            with self.subTest(field=field):
                self.assertNotEqual(check(self.changed_pin(field, value), series).returncode, 0)
        malformed = self.temp / 'p14-series'
        malformed.write_text('\n'.join(entries(series)[:-1]) + '\n')
        self.assertNotEqual(check(self.pin, malformed).returncode, 0)

    def test_p9_keeps_p8_and_requires_its_new_codec_modules(self):
        self.pin = ROOT / 'config/ge-master-20260913-se2-p9.env'
        series = ROOT / 'patches/series-ge-master-20260913-se2-p9'
        old_pin = ROOT / 'config/ge-master-20260913-se2-p8.env'
        old_series = ROOT / 'patches/series-ge-master-20260913-se2-p8'
        result = check(self.pin, series)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(check(old_pin, old_series).returncode, 0)
        self.assertNotEqual(check(self.pin, old_series).returncode, 0)
        self.assertNotEqual(check(old_pin, series).returncode, 0)
        entries = [line for line in series.read_text().splitlines()
                   if line and not line.startswith('#')]
        previous = [line for line in old_series.read_text().splitlines()
                    if line and not line.startswith('#')]
        self.assertEqual(entries[:-3], previous)
        self.assertEqual(entries[-3:], [
            'proposed/0048-winedmo-expose-existing-dts-alac-and-g711-decoders.patch',
            'proposed/0049-winedmo-expose-existing-mpeg-layer-audio-decoder.patch',
            'proposed/0050-winedmo-expose-existing-mjpeg-video-decoder.patch',
        ])
        self.assertNotEqual(check(self.changed_pin('PIN_BUILD_NAME', 'proton-ge-master-0b8c4d30-rtsp-se2-p8'), series).returncode, 0)
        malformed = self.temp / 'p9-series'
        for mutation in (entries + entries[-1:], entries[:-2] + entries[-2:][::-1],
                         entries[:-1], entries[:-2] + entries[-1:], entries[:-3] + entries[-2:]):
            malformed.write_text('\n'.join(mutation) + '\n')
            self.assertNotEqual(check(self.pin, malformed).returncode, 0)

    def test_p10_keeps_p9_but_requires_narrow_mjpeg_patch(self):
        self.pin = ROOT / 'config/ge-master-20260913-se2-p10.env'
        series = ROOT / 'patches/series-ge-master-20260913-se2-p10'
        old_pin = ROOT / 'config/ge-master-20260913-se2-p9.env'
        old_series = ROOT / 'patches/series-ge-master-20260913-se2-p9'
        result = check(self.pin, series)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(check(old_pin, old_series).returncode, 0)
        self.assertNotEqual(check(self.pin, old_series).returncode, 0)
        self.assertNotEqual(check(old_pin, series).returncode, 0)
        entries = [line for line in series.read_text().splitlines() if line and not line.startswith('#')]
        previous = [line for line in old_series.read_text().splitlines() if line and not line.startswith('#')]
        self.assertEqual(entries[:-1], previous[:-1])
        self.assertEqual(entries[-1], 'ge-master-20260913-se2-p10/0050-winedmo-expose-existing-mjpeg-video-decoder.patch')
        malformed = self.temp / 'p10-series'
        for mutation in (entries[:-1], entries + entries[-1:], entries[:-2] + entries[-2:][::-1]):
            malformed.write_text('\n'.join(mutation) + '\n')
            self.assertNotEqual(check(self.pin, malformed).returncode, 0)

    def test_p11_requires_exact_existing_video_contract_fixes(self):
        self.pin = ROOT / 'config/ge-master-20260913-se2-p11.env'
        series = ROOT / 'patches/series-ge-master-20260913-se2-p11'
        old_pin = ROOT / 'config/ge-master-20260913-se2-p10.env'
        old_series = ROOT / 'patches/series-ge-master-20260913-se2-p10'
        result = check(self.pin, series)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(check(old_pin, old_series).returncode, 0)
        self.assertNotEqual(check(self.pin, old_series).returncode, 0)
        self.assertNotEqual(check(old_pin, series).returncode, 0)
        entries = [line for line in series.read_text().splitlines() if line and not line.startswith('#')]
        previous = [line for line in old_series.read_text().splitlines() if line and not line.startswith('#')]
        self.assertEqual(entries[:-3], previous)
        self.assertEqual(entries[-3:], [
            'proposed/0051-winedmo-expose-existing-mpeg-video-decoders.patch',
            'proposed/0052-winedmo-register-existing-mpeg4-video-aliases.patch',
            'proposed/0053-winedmo-map-exact-h264-es-subtype.patch',
        ])
        malformed = self.temp / 'p11-series'
        for mutation in (entries[:-1], entries + entries[-1:], entries[:-3] + entries[-3:][::-1]):
            malformed.write_text('\n'.join(mutation) + '\n')
            self.assertNotEqual(check(self.pin, malformed).returncode, 0)

    def test_p12_requires_correct_serialization_and_parser_drain(self):
        self.pin = ROOT / 'config/ge-master-20260913-se2-p12.env'
        series = ROOT / 'patches/series-ge-master-20260913-se2-p12'
        old_pin = ROOT / 'config/ge-master-20260913-se2-p11.env'
        old_series = ROOT / 'patches/series-ge-master-20260913-se2-p11'
        result = check(self.pin, series)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotEqual(check(self.pin, old_series).returncode, 0)
        self.assertNotEqual(check(old_pin, series).returncode, 0)
        entries = [line for line in series.read_text().splitlines() if line and not line.startswith('#')]
        previous = [line for line in old_series.read_text().splitlines() if line and not line.startswith('#')]
        self.assertEqual(entries[:-4], previous[:-3])
        self.assertEqual(entries[-4:], [
            'ge-master-20260913-se2-p12/0051-winedmo-expose-existing-mpeg-video-decoders.patch',
            'ge-master-20260913-se2-p12/0052-winedmo-register-existing-mpeg4-video-aliases.patch',
            'proposed/0053-winedmo-map-exact-h264-es-subtype.patch',
            'proposed/0054-winedmo-drain-parser-tail-before-decoder-eos.patch',
        ])
        malformed = self.temp / 'p12-series'
        for mutation in (entries[:-1], entries + entries[-1:], entries[:-4] + entries[-4:][::-1]):
            malformed.write_text('\n'.join(mutation) + '\n')
            self.assertNotEqual(check(self.pin, malformed).returncode, 0)

    def test_p13_requires_amended_0015_and_exact_two_ge_corrections(self):
        self.pin = ROOT / 'config/ge-master-20260913-se2-p13.env'
        series = ROOT / 'patches/series-ge-master-20260913-se2-p13'
        old_pin = ROOT / 'config/ge-master-20260913-se2-p12.env'
        old_series = ROOT / 'patches/series-ge-master-20260913-se2-p12'
        result = check(self.pin, series)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(check(old_pin, old_series).returncode, 0)
        self.assertNotEqual(check(self.pin, old_series).returncode, 0)
        self.assertNotEqual(check(old_pin, series).returncode, 0)
        entries = [line for line in series.read_text().splitlines() if line and not line.startswith('#')]
        previous = [line for line in old_series.read_text().splitlines() if line and not line.startswith('#')]
        amended = 'ge-master-20260913-se2-p13/0015-mf-order-immediate-replacement-start.patch'
        old_0015 = 'ge-proton11-6/0015-mf-order-immediate-replacement-start.patch'
        self.assertEqual(previous[12], old_0015)
        expected = previous[:12] + [amended] + previous[13:] + [
            'proposed/0055-mfmediaengine-wait-for-renderer-drain-before-ended.patch',
            'proposed/0056-winedmo-preserve-vc1-input-timestamp-origin.patch',
        ]
        self.assertEqual(entries, expected)
        self.assertEqual(len(entries), 50)
        self.assertNotEqual(check(self.changed_pin('PIN_BUILD_NAME',
            'proton-ge-master-0b8c4d30-rtsp-se2-p12'), series).returncode, 0)
        malformed = self.temp / 'p13-series'
        for mutation in (entries[:-1], entries[:-2] + entries[-1:],
                         entries[:-2] + entries[-2:][::-1],
                         entries[:12] + [old_0015] + entries[13:],
                         entries + [old_0015], entries + [amended],
                         entries[:12] + entries[12:14][::-1] + entries[14:]):
            malformed.write_text('\n'.join(mutation) + '\n')
            self.assertNotEqual(check(self.pin, malformed).returncode, 0)

    def test_p15_requires_each_separate_reviewed_addition(self):
        pin = ROOT / 'config/ge-proton11-7-se2-p15.env'
        series = ROOT / 'patches/series-ge-proton11-7-se2-p15'
        prior_pin = ROOT / 'config/ge-proton11-7-se2-p14.env'
        prior_series = ROOT / 'patches/series-ge-proton11-7-se2-p14'
        self.assertEqual(check(pin, series).returncode, 0)
        self.assertEqual(check(prior_pin, prior_series).returncode, 0)
        self.assertNotEqual(check(pin, prior_series).returncode, 0)
        self.assertNotEqual(check(prior_pin, series).returncode, 0)
        entries = [s for s in series.read_text().splitlines() if s and not s.startswith('#')]
        prior = [s for s in prior_series.read_text().splitlines() if s and not s.startswith('#')]
        self.assertEqual(entries[:-4], prior)
        self.assertEqual(len(entries), 54)
        malformed = self.temp / 'p15-series'
        for index in range(50, 54):
            malformed.write_text('\n'.join(entries[:index] + entries[index + 1:]) + '\n')
            self.assertNotEqual(check(pin, malformed).returncode, 0)
        malformed.write_text('\n'.join(entries[:-4] + entries[-4:][::-1]) + '\n')
        self.assertNotEqual(check(pin, malformed).returncode, 0)

    def test_p16_excludes_0059_and_requires_timestamp_fix_and_parser(self):
        self.pin = ROOT / 'config/ge-proton11-7-se2-p16.env'
        series = ROOT / 'patches/series-ge-proton11-7-se2-p16'
        result = check(self.pin, series)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotEqual(check(self.pin, ROOT / 'patches/series-ge-proton11-7-se2-p15').returncode, 0)
        entries = [s for s in series.read_text().splitlines() if s and not s.startswith('#')]
        self.assertEqual(len(entries), 54)
        self.assertFalse(any('0059-' in s for s in entries))
        malformed = self.temp / 'p16-series'
        for index in range(50,54):
            malformed.write_text('\n'.join(entries[:index]+entries[index+1:])+'\n')
            self.assertNotEqual(check(self.pin,malformed).returncode,0)
        for field,value in (('PIN_FFMPEG_MPEGVIDEO_PATCH_SHA256','0'*64),
                            ('PIN_FFMPEG_MPEGVIDEO_MAKEFILE_BLOB','0'*40),
                            ('PIN_DEFAULT_JOBS','16'),('PIN_DEFAULT_MAKE_JOBS','8')):
            self.assertNotEqual(check(self.changed_pin(field,value),series).returncode,0)

    def test_av1_and_crypto_postimages_are_distinct_and_exact(self):
        for field, value in (("PIN_FFMPEG_DAV1D_PATCH_SHA256", "0" * 64),
                             ("PIN_FFMPEG_DAV1D_MAKEFILE_BLOB", "0" * 40),
                             ("PIN_FFMPEG_CRYPTO_BUILD_MAKEFILE_BLOB", "0" * 40)):
            with self.subTest(field=field):
                self.assertNotEqual(check(self.changed_pin(field, value), self.series).returncode, 0)

    def test_source_identity_and_launcher_policy_still_bound(self):
        for field, value in (("PIN_SOURCE_COMMIT", "0" * 40),
                             ("PIN_BUILD_NAME", "proton-ge-11-6-rtsp-se1"),
                             ("PIN_PROTON_LAUNCHER_POLICY", "scoped-xrizer")):
            with self.subTest(field=field):
                self.assertNotEqual(check(self.changed_pin(field, value), self.series).returncode, 0)

    def test_module_omission_order_and_substitution_rejected(self):
        entries = [line for line in self.series.read_text().splitlines()
                   if line and not line.startswith("#")]
        for lines in (entries[:-1], entries[:-2] + entries[-2:][::-1],
                      entries[:-1] + [entries[-2]]):
            path = self.temp / "series"
            path.write_text("\n".join(lines) + "\n")
            self.assertNotEqual(check(self.pin, path).returncode, 0)

    def test_historical_se1_does_not_accept_p1_modules(self):
        result = check(ROOT / "config/ge-proton11-6-se1.env", self.series)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("reviewed 21-patch", result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
