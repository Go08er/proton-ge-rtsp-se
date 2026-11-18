#!/usr/bin/env python3
"""HLS origin source contracts; actual-MF offset/zero fixtures provide runtime proof."""
import argparse
from pathlib import Path
import unittest

SOURCE = None


class HlsTimelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = SOURCE.read_text()
        cls.create = cls.text.split('NTSTATUS demuxer_create( void *arg )', 1)[1]
        cls.seek = cls.text.split('NTSTATUS demuxer_seek( void *arg )', 1)[1]

    def assert_probe_budget(self, create):
        condition = create.split('format = demuxer->ctx->iformat;', 1)[1].split(
            'avformat_find_stream_info', 1)[0]
        self.assertIn('strstr( format->name, "hls" )', condition)
        final_check = 'if (demuxer->direct_url && demuxer_interrupt_callback( demuxer )) goto failed;'
        if final_check not in create:
            # Retained candidates gave probing a separate budget.
            self.assertIn('demuxer_set_deadline( demuxer, RTSP_OPEN_TIMEOUT_US )', condition)
            return
        # The approved single budget covers opening AND probing. Resetting it
        # here would silently allow a second full network timeout.
        http, rtsp = create.split('else if ((rtsp_kind = get_rtsp_url_kind( params->url )))', 1)
        for branch, timeout in ((http, 'HTTP'), (rtsp.split('\n    else\n', 1)[0], 'RTSP')):
            deadline = f'demuxer_set_deadline( demuxer, {timeout}_OPEN_TIMEOUT_US );'
            self.assertEqual(branch.count(deadline), 1)
            self.assertLess(branch.index(deadline), branch.index('avformat_open_input'))
        success = create.split('\nfailed:', 1)[0]
        publish = success.index('params->demuxer.handle = (UINT_PTR)demuxer;')
        common = success.split('format = demuxer->ctx->iformat;', 1)[1]
        self.assertLess(success.index(final_check), publish)
        self.assertNotIn('demuxer_set_deadline', common.split('params->demuxer.handle', 1)[0])
        clear = 'demuxer_set_deadline( demuxer, 0 );'
        self.assertEqual(success.count(clear), 1)
        self.assertLess(publish, success.index(clear))
        self.assertLess(success.index(clear), success.index('return STATUS_SUCCESS;'))

    def test_probe_hls_timing_before_publishing_source(self):
        self.assert_probe_budget(self.create)

    def test_single_budget_regressions_are_rejected(self):
        final_check = 'if (demuxer->direct_url && demuxer_interrupt_callback( demuxer )) goto failed;'
        if final_check not in self.create:
            self.skipTest('retained candidate predates the single opening budget')
        for old, new in (
            ('demuxer_set_deadline( demuxer, HTTP_OPEN_TIMEOUT_US );', ''),
            ('demuxer_set_deadline( demuxer, RTSP_OPEN_TIMEOUT_US );', ''),
            ('format = demuxer->ctx->iformat;',
             'format = demuxer->ctx->iformat; demuxer_set_deadline( demuxer, RTSP_OPEN_TIMEOUT_US );'),
            ('format = demuxer->ctx->iformat;',
             'format = demuxer->ctx->iformat; demuxer_set_deadline( demuxer, 0 );'),
            (final_check, ''),
        ):
            with self.subTest(regression=(old, new)):
                self.assertIn(old, self.create)
                with self.assertRaises(AssertionError):
                    self.assert_probe_budget(self.create.replace(old, new, 1))

    def test_common_origin_includes_finite_hls(self):
        anchor = ('if (demuxer->ctx->start_time != AV_NOPTS_VALUE &&\n'
                  '        strstr( format->name, "hls" ))')
        self.assertIn(anchor, self.create)
        self.assertIn('demuxer->hls_timestamp_base = AV_NOPTS_VALUE;', self.create)
        self.assertIn('demuxer->hls_timestamp_base = get_user_time( demuxer->ctx->start_time, AV_TIME_BASE_Q );',
                      self.create)

    def test_both_sample_times_use_the_same_origin(self):
        # Trees up to SE4-P2 call the two-argument form; 0044 (SE4-P3) also passes the stream.
        self.assertTrue(any(call in self.text for call in (
            'normalize_hls_timestamps( demuxer, sample );',
            'normalize_hls_timestamps( demuxer, demuxer_stream, sample );')))
        for field in ('pts', 'dts'):
            self.assertIn(f'if (sample->{field} != AV_NOPTS_VALUE)', self.text)
            self.assertIn(f'av_sat_sub64( sample->{field}, demuxer->hls_timestamp_base )', self.text)

    def test_seek_converts_back_without_advertising_new_seekability(self):
        guard = 'if (!demuxer_is_seekable( demuxer )) return STATUS_NOT_SUPPORTED;'
        translation = 'timestamp = av_sat_add64( timestamp, av_rescale( demuxer->hls_timestamp_base, AV_TIME_BASE, 10000000 ) );'
        self.assertIn(translation, self.seek)
        self.assertLess(self.seek.index(guard), self.seek.index(translation))
        self.assertLess(self.seek.index(translation), self.seek.index('ret = avformat_seek_file'))
        self.assertIn('if (demuxer->hls_timestamp_base != AV_NOPTS_VALUE)', self.seek)
        # GE11-9 adds a finite-resource nonseekable latch to the same early
        # rejection; neither form may bypass FFmpeg's UNSEEKABLE flag.
        guards = (
            'if (demuxer->ctx->ctx_flags & AVFMTCTX_UNSEEKABLE) return FALSE;',
            'if (demuxer->nonseekable || (demuxer->ctx->ctx_flags & AVFMTCTX_UNSEEKABLE)) return FALSE;',
        )
        self.assertTrue(any(guard in self.text for guard in guards))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--wine-tree', type=Path)
    source.add_argument('--source-file', type=Path)
    args, rest = parser.parse_known_args()
    SOURCE = args.source_file if args.source_file else args.wine_tree / 'dlls/winedmo/unix_demuxer.c'
    unittest.main(argv=[__file__, *rest])
