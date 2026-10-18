#!/usr/bin/env python3
"""Structural guardrails for experimental progressive-HTTP Alpha patch 5."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "network-terminal-error"))
from seek_policy import check_seek_ownership


def require(text: str, needle: str, message: str) -> None:
    if needle not in text:
        raise SystemExit(f"FAIL: {message}")


def require_order(text: str, needles: list[str], message: str) -> None:
    position = -1
    for needle in needles:
        next_position = text.find(needle, position + 1)
        if next_position < 0:
            raise SystemExit(f"FAIL: {message}: missing {needle!r}")
        if next_position <= position:
            raise SystemExit(f"FAIL: {message}: {needle!r} is out of order")
        position = next_position


def function_body(text: str, start: str, end: str) -> str:
    begin = text.find(start)
    finish = text.find(end, begin + len(start))
    if begin < 0 or finish < 0:
        raise SystemExit(f"FAIL: could not isolate {start}")
    return text[begin:finish]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wine-tree", required=True, type=Path)
    args = parser.parse_args()

    media_path = args.wine_tree / "dlls/winedmo/media_source.c"
    demuxer_path = args.wine_tree / "dlls/winedmo/unix_demuxer.c"
    unixlib_path = args.wine_tree / "dlls/winedmo/unixlib.c"
    media = media_path.read_text(encoding="utf-8")
    demuxer = demuxer_path.read_text(encoding="utf-8")
    unixlib = unixlib_path.read_text(encoding="utf-8")
    try:
        seek_policy = check_seek_ownership(media, demuxer)
    except ValueError as exc:
        raise SystemExit(f"FAIL: seek ownership: {exc}") from exc
    # 0032 merges direct HTTP/HLS opens. Recognize that explicit source shape;
    # its HLS detection/child-policy/seek split is checked below, not skipped.
    combined_http = "\n    if (is_http_url( params->url ))" in demuxer

    callback = function_body(
        media,
        "static HRESULT WINAPI scheme_handler_callback_Invoke",
        "static const IMFAsyncCallbackVtbl scheme_handler_callback_vtbl",
    )
    require_order(
        callback,
        [
            "media_source_create(context",
            "hr == HRESULT_FROM_NT(STATUS_BAD_NETWORK_PATH)",
            "cache_http_url(context)",
            "get_http_bytestream_url_hint(url)",
            "media_source_create(context",
            "context->url = url",
        ],
        "direct-first/fallback-once routing changed",
    )
    require(callback, "!is_http_hls_url(context->url)", "HLS is not excluded from URLMon fallback")
    require(callback, 'WARN("media-route=urlmon-cache-fallback reason=direct-open-failure',
            "fallback begin marker is absent or may expose a URL")
    require(callback, 'TRACE("media-route=urlmon-cache-fallback-opened',
            "fallback ready marker is absent or may expose a URL")
    if callback.find("URLOpenBlockingStreamW") >= 0:
        raise SystemExit("FAIL: scheme callback downloads before selecting the fallback")

    cache = function_body(media, "static HRESULT cache_http_url", "static HRESULT WINAPI scheme_handler_callback_Invoke")
    if cache.count("URLOpenBlockingStreamW") != 1:
        raise SystemExit("FAIL: fallback must perform exactly one URLMon open")
    require(cache, "context->file_size = -1", "fallback leaves a stale direct-stream length")
    require(cache, "MFBYTESTREAM_IS_SEEKABLE", "fallback does not re-read cached-stream capabilities")

    require_order(
        demuxer,
        (["if (is_http_url( params->url ))", "BOOL hls_hint = is_http_hls_url( params->url )",
          "else if ((rtsp_kind = get_rtsp_url_kind( params->url )))"] if combined_http else [
            "if (is_http_hls_url( params->url ))",
            "else if (is_http_url( params->url ))",
            "else if ((rtsp_kind = get_rtsp_url_kind( params->url )))",
        ]),
        "direct HTTP/HLS route or explicit HLS hint changed",
    )
    if not combined_http:
        require(demuxer, '#define HTTP_PROTOCOL_WHITELIST "http,https,httpproxy,tcp,tls"',
                "HTTP protocol allowlist broadened or removed")
        require(demuxer, '#define HTTPS_PROTOCOL_WHITELIST "https,httpproxy,tcp,tls"',
                "HTTPS downgrade protection is absent or broadened")
    require(demuxer, '#define HTTP_HLS_PROTOCOL_WHITELIST "http,https,httpproxy,tcp,tls,crypto"',
            "HTTP-root HLS AES wrapper or protocol boundary changed")
    require(demuxer, '#define HTTPS_HLS_PROTOCOL_WHITELIST "https,httpproxy,tcp,tls,crypto"',
            "HTTPS-root HLS AES wrapper or downgrade protection changed")
    if not combined_http:
        whitelist_selector = function_body(
            demuxer,
            "static const char *http_protocol_whitelist",
            "static const char *hls_protocol_whitelist",
        )
        require_order(
            whitelist_selector,
            [
                '!strncasecmp( url, "https://", 8 )',
                "? HTTPS_PROTOCOL_WHITELIST : HTTP_PROTOCOL_WHITELIST",
            ],
            "generic HTTP scheme-specific protocol selection changed",
        )
    hls_whitelist_selector = function_body(
        demuxer,
        "static const char *hls_protocol_whitelist",
        "static BOOL http_open_allows_urlmon_fallback",
    )
    require_order(
        hls_whitelist_selector,
        [
            '!strncasecmp( url, "https://", 8 )',
            "? HTTPS_HLS_PROTOCOL_WHITELIST : HTTP_HLS_PROTOCOL_WHITELIST",
        ],
        "HLS root scheme no longer constrains its AES wrapper and nested URL",
    )
    fallback_gate = function_body(
        demuxer,
        "static BOOL http_open_allows_urlmon_fallback",
        "static BOOL is_http_hls_url",
    )
    require_order(
        fallback_gate,
        [
            '!strncasecmp( url, "http://", 7 )',
            "ret == AVERROR_INVALIDDATA",
        ],
        "URLMon fallback is not restricted to plain-HTTP media validation",
    )
    if '"https://' in fallback_gate:
        raise SystemExit("FAIL: HTTPS can enter the URLMon compatibility fallback")
    if demuxer.count("STATUS_BAD_NETWORK_PATH") != 1:
        raise SystemExit("FAIL: direct-open fallback status must have one narrow producer")
    require(demuxer, "*cursor != '?' && *cursor != '#'", "HLS classifier still scans query or fragment")
    require(media, "*cursor != '?' && *cursor != '#'", "Windows HLS classifier still scans query or fragment")
    require(demuxer, "while (*cursor && *cursor != '/'", "Unix HLS classifier still scans the URL authority")
    require(media, "while (*cursor && *cursor != '/'", "Windows HLS classifier still scans the URL authority")
    http_branch = function_body(
        demuxer,
        ("\n    if (is_http_url( params->url ))" if combined_http
         else "else if (is_http_url( params->url ))"),
        "else if ((rtsp_kind = get_rtsp_url_kind( params->url )))",
    )
    http_url = "params->url"
    if "avformat_open_input( &demuxer->ctx, direct_url, hint, &options )" in http_branch:
        # GE11-9 canonicalizes only the scheme on an owned copy. Validate that
        # spelling's ownership and transformation, not an arbitrary URL alias.
        require_order(http_branch, [
            "if (!(direct_url = strdup( params->url ))) goto failed;",
            "for (p = direct_url; *p && *p != ':'; ++p) *p = av_tolower( *p );",
            "avformat_open_input( &demuxer->ctx, direct_url, hint, &options )",
            "free( direct_url );", "direct_url = NULL;"],
            "canonical HTTP scheme must preserve an owned copy and release it")
        require(demuxer[demuxer.rfind("failed:"):], "free( direct_url );",
                "failed HTTP open leaks its owned canonical URL")
        http_url = "direct_url"
    require_order(
        http_branch,
        [
            ("protocol_whitelist = hls_protocol_whitelist( params->url )" if combined_http
             else "protocol_whitelist = http_protocol_whitelist( params->url )"),
            'av_dict_set( &options, "protocol_whitelist", protocol_whitelist, 0 )',
            'av_dict_set_int( &options, "tls_verify", 1, 0 )',
            "demuxer->ctx->interrupt_callback.callback = demuxer_interrupt_callback",
            "demuxer_set_deadline( demuxer, HTTP_OPEN_TIMEOUT_US )",
            (f"avformat_open_input( &demuxer->ctx, {http_url}, hint, &options )" if combined_http
             else "avformat_open_input( &demuxer->ctx, params->url, NULL, &options )"),
            "interrupted = demuxer_interrupt_callback( demuxer )",
            ("if (!hls_hint && !interrupted && http_open_allows_urlmon_fallback( params->url, ret ))"
             if combined_http else "if (!interrupted && http_open_allows_urlmon_fallback( params->url, ret ))"),
            "failure_status = STATUS_BAD_NETWORK_PATH",
            'TRACE( "media-route=direct-http-progressive-opened',
            'av_dict_set( &options, "tls_verify", NULL, 0 )',
            "if (av_dict_count( options ))",
        ],
        "direct HTTP open or its fallback signal changed",
    )
    require(http_branch, "demuxer->io_timeout = HTTP_IO_TIMEOUT_US", "HTTP read/seek/close timeout is absent")
    require(http_branch, "demuxer->require_avio_seek = TRUE", "direct HTTP does not fail closed on missing AVIO")
    require(http_branch, ('TRACE( "media-route=direct-http-probe' if combined_http
                          else 'TRACE( "media-route=direct-http-progressive'),
            "direct HTTP begin marker is absent or may expose a URL")
    require(demuxer, 'if (!demuxer->direct_url && strstr( format->name, "mp4" ))',
            "direct HTTP may pass FFmpeg network AVIO opaque to the custom MP4 parser")

    duration = function_body(demuxer, "static INT64 get_context_duration", "NTSTATUS demuxer_check")
    require_order(
        duration,
        [
            "if (ctx->duration_estimation_method == AVFMT_DURATION_FROM_BITRATE)",
            "if (!custom_io) return AV_NOPTS_VALUE",
            "get_asf_header_duration",
            "get_raw_mpegvideo_duration",
        ],
        "direct URLs may reach custom-stream duration scanners",
    )
    raw_seek = function_body(demuxer, "static NTSTATUS raw_mpegvideo_seek", "static void fixup_asf_vc1_timestamps")
    require_order(
        raw_seek,
        ["if (demuxer->direct_url) return STATUS_NOT_SUPPORTED", "read_stream_at"],
        "direct URLs may reach the custom-stream raw MPEG seek scanner",
    )

    hls_branch = http_branch if combined_http else function_body(
        demuxer, "if (is_http_hls_url( params->url ))", "else if (is_http_url( params->url ))")
    require_order(
        hls_branch,
        [
            "protocol_whitelist = hls_protocol_whitelist( params->url )",
            'av_dict_set( &options, "protocol_whitelist", protocol_whitelist, 0 )',
            'av_dict_set_int( &options, "tls_verify", 1, 0 )',
            "demuxer->ctx->interrupt_callback.callback = demuxer_interrupt_callback",
            (f"avformat_open_input( &demuxer->ctx, {http_url}, hint, &options )" if combined_http
             else "avformat_open_input( &demuxer->ctx, params->url, hls, &options )"),
            'av_dict_set( &options, "tls_verify", NULL, 0 )',
            "if (av_dict_count( options ))",
            "av_dict_free( &options )",
        ],
        "direct HLS root trust or required-option checks changed",
    )
    require(hls_branch, 'TRACE( "media-route=direct-hls', "direct HLS begin marker is absent")
    if combined_http:
        child_formats = 'mpegts,mov,aac,ac3,eac3,mp3,webvtt'
        # 0041 admits four experimentally decoded containers. Both immutable
        # source shapes are valid; do not accept an arbitrary new demuxer list.
        if f'format_whitelist={child_formats},wav,flac,ogg,matroska"' in http_branch:
            child_formats += ',wav,flac,ogg,matroska'
        for name, value in (("HTTP_OPEN_TIMEOUT_US", "30000000"),
                            ("HTTP_IO_TIMEOUT_US", "15000000"),
                            ("HLS_IO_TIMEOUT_US", "30000000")):
            if not re.search(r"^#define " + name + r"\s+INT64_C\(" + value + r"\)$", demuxer, re.M):
                raise SystemExit("FAIL: unified HTTP/HLS time budget changed: " + name)
        require_order(http_branch, [
            'hls_hint ? av_find_input_format( "hls" ) : NULL',
            "if (hls_hint && !hint) goto failed;",
            'av_dict_set_int( &options, "extension_picky", 0, 0 )',
            'av_dict_set( &options, "seg_format_options",',
            f'"format_whitelist={child_formats}", 0 ) < 0) goto failed;',
            "avformat_open_input", 'detected_hls = !strcmp( demuxer->ctx->iformat->name, "hls" );',
            "if (detected_hls)", "demuxer->require_avio_seek = FALSE;",
            "demuxer->io_timeout = HLS_IO_TIMEOUT_US;", "        else\n        {",
            'av_dict_set( &options, "extension_picky", NULL, 0 );',
            'av_dict_set( &options, "seg_format_options", NULL, 0 );',
            "if (av_dict_count( options ))", "av_dict_free( &options );",
        ], "probed HLS must retain child policy, capability/budget split, and required-option checks")
        if '"format_whitelist",' in http_branch:
            raise SystemExit("FAIL: HLS child whitelist restricts unrelated progressive root formats")
        opens = http_branch.count("avformat_open_input")
        retry_guard = "if (ret == AVERROR_HTTP_FORBIDDEN && !interrupted)"
        if opens == 2 and retry_guard in http_branch:
            # GE11-9's single 403 retry (maintainer policy 2026-10-17): it must be
            # the only extra open and must share the original open deadline.
            tail = http_branch[http_branch.index(retry_guard):]
            if tail.count("avformat_open_input") != 1 or "demuxer_set_deadline" in tail.split("avformat_open_input", 1)[0]:
                raise SystemExit("FAIL: the GE 403 retry must be the only extra open and share the open deadline")
        elif opens != 1:
            raise SystemExit("FAIL: unified HTTP route performs more than one input open")
        require_order(http_branch, ["demuxer->require_avio_seek = TRUE;",
                                   "demuxer->io_timeout = HTTP_IO_TIMEOUT_US;", "avformat_open_input"],
                      "progressive HTTP must retain Range capability and its read budget before probing")

    source_start = function_body(
        media,
        "static HRESULT media_source_start",
        "static HRESULT media_source_pause",
    )
    seek_transition = source_start[source_start.index("winedmo_demuxer_seek"):]
    success_marker = (
        "\n        else\n"
        "        {\n"
        "            source->flushing = FALSE;"
    )
    if "if (FAILED(seek_error) || status)" in seek_transition:
        require_order(
            seek_transition,
            [
                "winedmo_demuxer_seek",
                "if (FAILED(seek_error) || status)",
                "media_source_queue_demux_error(source, error)",
                success_marker,
                "source->read_flushing = FALSE",
                "media_source_end_demux_transition(source)",
            ],
            "failed seeks may resume or retry a damaged demux timeline",
        )
        terminal_start = seek_transition.index("if (FAILED(seek_error) || status)")
    else:
        if "media_source_set_demux_error(source, media_source_error_from_demux_status(status))" in seek_transition:
            terminal_error_store = (
                "media_source_set_demux_error(source, "
                "media_source_error_from_demux_status(status))"
            )
        else:
            terminal_error_store = "source->demux_terminal_error = HRESULT_FROM_NT(status)"
        require_order(
            seek_transition,
            [
                "winedmo_demuxer_seek",
                "if (status)",
                "source->demux_thread_shutdown = true",
                terminal_error_store,
                success_marker,
                "source->read_flushing = FALSE",
                "media_source_end_demux_transition(source)",
            ],
            "failed seeks may resume or retry a damaged demux timeline",
        )
        terminal_start = seek_transition.index("if (status)")
    terminal_branch = seek_transition[
        terminal_start:seek_transition.index(success_marker)
    ]
    if "media_source_end_demux_transition" in terminal_branch:
        raise SystemExit("FAIL: a failed seek can return the transition epoch to readable state")
    if "cancel_transition_failed" in source_start:
        raise SystemExit("FAIL: demux seek failure is not included in the terminal transition path")

    seekable = function_body(demuxer, "static BOOL demuxer_is_seekable", "static INT64 get_user_time")
    require(seekable, "if (demuxer->require_avio_seek)", "direct HTTP seek policy is not isolated")
    require(seekable, "return demuxer->ctx->pb && (demuxer->ctx->pb->seekable & AVIO_SEEKABLE_NORMAL)",
            "direct HTTP does not require a range-seekable AVIO context")
    require(seekable, "if (!demuxer->direct_url && demuxer->ctx->pb",
            "legacy bytestream seek policy changed")

    free_context = function_body(demuxer, "static void demuxer_free_context", "NTSTATUS demuxer_create")
    read_packet = function_body(demuxer, "static NTSTATUS demuxer_filter_packet", "NTSTATUS demuxer_read")
    seek = function_body(demuxer, "NTSTATUS demuxer_seek", "NTSTATUS demuxer_stream_lang")
    for body, operation in ((free_context, "close"), (read_packet, "read"), (seek, "seek")):
        require(body, "demuxer_set_deadline( demuxer, demuxer->io_timeout )",
                f"direct HTTP {operation} deadline is absent")
        if operation == "close" and (
                "if (demuxer->direct_url && demuxer_interrupt_callback( demuxer )) goto failed;" in demuxer):
            # Single open/probe budget: cleanup must retain an existing expired
            # deadline so failure classification cannot renew it or fall back.
            require_order(body, [
                "if (demuxer->direct_url)",
                "if (demuxer->io_timeout && !__atomic_load_n( &demuxer->deadline, __ATOMIC_RELAXED ))",
                "demuxer_set_deadline( demuxer, demuxer->io_timeout )",
                "avformat_close_input( &demuxer->ctx )",
            ], "direct HTTP close renews an existing open/probe deadline")
            if body.count("demuxer_set_deadline") != 1:
                raise SystemExit("FAIL: direct HTTP close clears or replaces the retained deadline")
            continue
        require(body, "demuxer_set_deadline( demuxer, 0 )", f"direct HTTP {operation} deadline is not cleared")

    require_order(
        seek,
        ["avformat_seek_file", "if (ret < 0)", "av_bsf_flush",
         "av_packet_free( &demuxer->last_packet );", "demuxer->last_stream = NULL;"],
        "seek must flush old filter output before discarding/prefetching packets",
    )
    if seek_policy == "interrupt-reuse":
        # Historical candidates must still satisfy the complete old policy.
        # The serialized policy instead forbids ordinary-seek cancellation and
        # all reusable-cancel recovery/error clearing in check_seek_ownership.
        require(demuxer, "BOOL cancelled_read_pending_recovery;",
                "progressive cancellation recovery state is absent")
        require(read_packet, "if (demuxer->cancelled_read_pending_recovery) return STATUS_CANCELLED;",
                "a damaged progressive timeline can continue reading before recovery")
        read_after_av = read_packet[read_packet.index("ret = av_read_frame"):]
        partial_read_guard = read_after_av[:read_after_av.index("if (!ret)")]
        require_order(
            partial_read_guard,
            [
                "ret = av_read_frame",
                "demuxer_set_deadline( demuxer, 0 )",
                "demuxer->require_avio_seek",
                "__atomic_load_n( &demuxer->cancelled",
                "ret == AVERROR_EXIT",
                "demuxer->ctx->pb->error == AVERROR_EXIT",
                "demuxer->cancelled_read_pending_recovery = TRUE",
                "av_packet_free( packet )",
                "return STATUS_CANCELLED",
            ],
            "cancelled positive-partial packet is not discarded before the BSF",
        )
        cancellation_guard = partial_read_guard[
            partial_read_guard.index("if (demuxer->require_avio_seek"):]
        cancellation_condition = cancellation_guard[:cancellation_guard.index("{")]
        if "ret < 0" in cancellation_condition:
            raise SystemExit("FAIL: positive-partial cancellation recovery is gated on a negative read result")
        require_order(
            read_after_av,
            ["return STATUS_CANCELLED", "av_bsf_send_packet( stream->filter, (*packet) )"],
            "cancelled or corrupt packet can reach the bitstream filter",
        )
        require_order(
            seek,
            [
                "demuxer->require_avio_seek && demuxer->cancelled_read_pending_recovery",
                "if (pb->error == AVERROR_EXIT)",
                "pb->error = 0",
                "pb->eof_reached = 0",
                "avformat_seek_file",
                "if (ret < 0)",
                "demuxer->cancelled_read_pending_recovery = FALSE",
                "av_bsf_flush",
            ],
            "progressive AVIO cancellation recovery order changed",
        )
        if seek.count("pb->error = 0") != 1:
            raise SystemExit("FAIL: seek may erase an AVIO error other than deliberate AVERROR_EXIT")

    if seek_policy == "interrupt-fresh":
        # P23 (maintainer decision 2026-10-17): any failure, error or EOF of a
        # read deliberately cancelled for a seek is a cancellation, including a
        # positive partial read; the seek clears that AVIO state, and its first
        # read uses the underlying seek (a fresh HTTP request), never the
        # interrupted transport.
        require(demuxer, "BOOL cancelled_read_pending_recovery;",
                "progressive cancellation recovery state is absent")
        require(read_packet, "if (demuxer->cancelled_read_pending_recovery) return STATUS_CANCELLED;",
                "a damaged progressive timeline can continue reading before recovery")
        read_after_av = read_packet[read_packet.index("ret = av_read_frame"):]
        partial_read_guard = read_after_av[:read_after_av.index("if (!ret)")]
        require_order(
            partial_read_guard,
            [
                "ret = av_read_frame",
                "demuxer_set_deadline( demuxer, 0 )",
                "demuxer->require_avio_seek",
                "__atomic_load_n( &demuxer->cancelled",
                "ret < 0",
                "demuxer->ctx->pb->error",
                "demuxer->ctx->pb->eof_reached",
                "demuxer->cancelled_read_pending_recovery = TRUE",
                "av_packet_free( packet )",
                "return STATUS_CANCELLED",
            ],
            "cancelled read (negative, error/EOF or positive partial) is not discarded before the BSF",
        )
        require_order(
            read_after_av,
            ["return STATUS_CANCELLED", "av_bsf_send_packet( stream->filter, (*packet) )"],
            "cancelled or corrupt packet can reach the bitstream filter",
        )
        require_order(
            seek,
            [
                "fresh_connection = demuxer->require_avio_seek && demuxer->cancelled_read_pending_recovery",
                "demuxer->require_avio_seek && demuxer->cancelled_read_pending_recovery",
                "pb->error = 0",
                "pb->eof_reached = 0",
                "avformat_seek_file",
                "if (ret < 0)",
                "demuxer->cancelled_read_pending_recovery = FALSE",
                "av_bsf_flush",
                "if (fresh_connection && demuxer->ctx->pb)",
                "demuxer->ctx->pb->direct = 1",
                "demuxer_filter_packet( demuxer, &packet )",
                "demuxer->ctx->pb->direct = direct",
            ],
            "progressive cancellation recovery must clear AVIO state and reopen HTTP for its first read",
        )
        if seek.count("pb->error = 0") != 1:
            raise SystemExit("FAIL: seek may erase an AVIO error outside the cancelled-read recovery")

    vlog = function_body(unixlib, "static void vlog", "static const char *debugstr_version")
    require_order(
        vlog,
        ["if (level > av_log_get_level()) return;", "av_log_format_line"],
        "FFmpeg log levels are not filtered before formatting sensitive trace output",
    )

    print("PASS: progressive HTTP VOD structural contract")


if __name__ == "__main__":
    main()
