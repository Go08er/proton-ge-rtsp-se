#!/usr/bin/env python3
"""A3.22 source contracts; runtime red/green is run_http_user_agent.py."""
import argparse
from pathlib import Path
import unittest

SOURCE = None
FORMATS = 'hls,mpegts,mov,aac,ac3,eac3,mp3,webvtt'


class HlsSegmentPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = SOURCE.read_text()
        create = cls.text.split('NTSTATUS demuxer_create( void *arg )', 1)[1]
        cls.combined = '\n    if (is_http_url( params->url ))' in create
        if cls.combined:
            rest = create.split('\n    if (is_http_url( params->url ))', 1)[1]
            cls.hls, cls.other = rest.split('else if ((rtsp_kind = get_rtsp_url_kind( params->url )))', 1)
            formats = FORMATS.removeprefix('hls,')
            if f'format_whitelist={formats},wav,flac,ogg,matroska"' in cls.hls:
                formats += ',wav,flac,ogg,matroska'
            cls.format_call = ('if (av_dict_set( &options, "seg_format_options",\n'
                               f'                        "format_whitelist={formats}", 0 ) < 0) goto failed;')
        else:
            cls.hls, cls.other = create.split('else if (is_http_url( params->url ))', 1)
            cls.format_call = f'if (av_dict_set( &options, "format_whitelist", "{FORMATS}", 0 ) < 0) goto failed;'

    def test_content_policy_is_checked_before_open(self):
        for call in ('if (av_dict_set_int( &options, "extension_picky", 0, 0 ) < 0) goto failed;',
                     self.format_call):
            self.assertIn(call, self.hls)
            self.assertLess(self.hls.index(call), self.hls.index('avformat_open_input'))

    def test_format_restriction_is_not_just_removed(self):
        self.assertIn(self.format_call, self.hls)
        self.assertNotIn('"ALL"', self.hls)
        self.assertNotIn('"allowed_extensions"', self.hls)
        self.assertNotIn('"allowed_segment_extensions"', self.hls)

    def test_policy_is_hls_only(self):
        if self.combined:
            # Options are offered before probing, but only HLS consumes them.
            # Progressive formats must not inherit a root format restriction.
            detected, progressive = self.hls.split('        else\n        {', 1)
            for option in ('extension_picky', 'seg_format_options'):
                cleanup = f'av_dict_set( &options, "{option}", NULL, 0 );'
                self.assertNotIn(cleanup, detected)
                self.assertIn(cleanup, progressive)
                self.assertLess(progressive.index(cleanup), progressive.index('if (av_dict_count( options ))'))
                self.assertNotIn(f'"{option}"', self.other)
            self.assertNotIn('"format_whitelist",', self.hls)
            if 'direct_url, hint, &options' in self.hls:
                self.assertIn('direct_url = strdup( params->url )', self.hls)
                self.assertIn("for (p = direct_url; *p && *p != ':'; ++p) *p = av_tolower( *p );", self.hls)
            else:
                self.assertIn('params->url, hint, &options', self.hls)
            self.assertIn('hls_hint ? av_find_input_format( "hls" ) : NULL', self.hls)
            self.assertNotIn('vr-m', self.hls)
            return
        for option in ('"extension_picky"', '"format_whitelist"'):
            self.assertEqual(self.text.count(option), 1)
            self.assertNotIn(option, self.other)
        self.assertIn('params->url, hls, &options', self.hls)
        self.assertNotIn('vr-m', self.hls)

    def test_existing_boundaries_remain(self):
        for marker in ('"protocol_whitelist", protocol_whitelist',
                       'av_dict_set_int( &options, "tls_verify", 1, 0 )',
                       'demuxer->ctx->interrupt_callback.callback = demuxer_interrupt_callback',
                       ('demuxer_set_deadline( demuxer, HTTP_OPEN_TIMEOUT_US )' if self.combined
                        else 'demuxer_set_deadline( demuxer, HLS_IO_TIMEOUT_US )'),
                       'if (av_dict_count( options ))'):
            self.assertIn(marker, self.hls)
        if self.combined:
            self.assertIn('detected_hls = !strcmp( demuxer->ctx->iformat->name, "hls" );', self.hls)
            self.assertIn('demuxer->io_timeout = HLS_IO_TIMEOUT_US;', self.hls)
        self.assertNotIn('"reconnect', self.hls)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--wine-tree', type=Path)
    source.add_argument('--source-file', type=Path)
    args, rest = parser.parse_known_args()
    SOURCE = args.source_file if args.source_file else args.wine_tree / 'dlls/winedmo/unix_demuxer.c'
    unittest.main(argv=[__file__, *rest])
