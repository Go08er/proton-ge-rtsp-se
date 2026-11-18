#!/usr/bin/env python3
"""The combined HTTP path audits active policy, not obsolete unused macros."""
import argparse
from pathlib import Path
import subprocess
import sys
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--wine-tree", type=Path, required=True)
args = parser.parse_args()
audit = Path(__file__).with_name("audit.py")
with tempfile.TemporaryDirectory(prefix="rtsp-http-policy-audit-") as temporary:
    tree = Path(temporary)
    folder = tree / "dlls/winedmo"
    folder.mkdir(parents=True)
    for name in ("media_source.c", "unix_demuxer.c", "unixlib.c"):
        (folder / name).write_bytes((args.wine_tree / "dlls/winedmo" / name).read_bytes())
    path = folder / "unix_demuxer.c"
    text = path.read_text()
    assert '\n    if (is_http_url( params->url ))' in text
    simplified = "\n".join(line for line in text.split("\n") if not line.startswith(
        ("#define HTTP_PROTOCOL_WHITELIST ", "#define HTTPS_PROTOCOL_WHITELIST ")))
    cases = [("original source", text, True), ("unused macros removed", simplified, True)]
    assert "av_bsf_flush( demuxer->streams[i].filter );" in simplified
    cases.append(("seek filter flush removed", simplified.replace(
        "av_bsf_flush( demuxer->streams[i].filter );", "/* missing flush */"), False))
    if "BOOL cancelled_read_pending_recovery;" in simplified:
        partial_guard = "if (demuxer->cancelled_read_pending_recovery) return STATUS_CANCELLED;"
        assert partial_guard in simplified
        cases.append(("legacy read recovery guard removed", simplified.replace(partial_guard, ""), False))
    if "avformat_open_input( &demuxer->ctx, direct_url, hint, &options )" in text:
        cases += [
            ("URL ownership removed", simplified.replace(
                "direct_url = strdup( params->url )", "direct_url = params->url"), False),
            ("URL path lowercased", simplified.replace(
                "*p && *p != ':'", "*p"), False),
        ]
    for name, before, after in [
        ("HTTPS downgrade", '#define HTTPS_HLS_PROTOCOL_WHITELIST "https,', '#define HTTPS_HLS_PROTOCOL_WHITELIST "http,https,'),
        ("HTTP local-file access", '#define HTTP_HLS_PROTOCOL_WHITELIST "http,', '#define HTTP_HLS_PROTOCOL_WHITELIST "file,http,'),
        ("TLS verification removed", 'av_dict_set_int( &options, "tls_verify", 1, 0 )', 'av_dict_set_int( &options, "tls_verify", 0, 0 )'),
    ]:
        assert before in simplified
        cases.append((name, simplified.replace(before, after), False))
    for name, content, expected in cases:
        path.write_text(content)
        result = subprocess.run([sys.executable, str(audit), "--wine-tree", str(tree)],
                                text=True, capture_output=True, timeout=10)
        assert (result.returncode == 0) == expected, name + "\n" + result.stdout + result.stderr
        print("PASS", name, "accepted" if expected else "rejected")
