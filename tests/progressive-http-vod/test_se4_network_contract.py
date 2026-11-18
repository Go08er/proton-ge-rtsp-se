#!/usr/bin/env python3
"""SE4-P1 network-contract mode of the progressive-HTTP audit: positives and negatives.

Runs audit.py --se4-network-contract on an SE4-P1 patched Wine tree and on mutated copies of
its three winedmo sources. The default (SE3-era) mode is not exercised here; it is unchanged.
"""
import argparse
from pathlib import Path
import subprocess
import sys
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--wine-tree", type=Path, required=True)
args = parser.parse_args()
audit = Path(__file__).with_name("audit.py")
NAMES = ("media_source.c", "unix_demuxer.c", "unixlib.c")
WL = '#define HTTP_PROTOCOL_WHITELIST "http,https,tls,rtp,tcp,udp,crypto,httpproxy,data"'
CREATE = "if (FAILED(hr = media_source_create(context, (IMFMediaSource **)&object)))"
OPT = 'if (av_dict_set( &options, "protocol_whitelist", HTTP_PROTOCOL_WHITELIST, 0 ) < 0) goto failed;'
TLS = 'if (av_dict_set_int( &options, "tls_verify", 1, 0 ) < 0) goto failed;'

sources = {n: (args.wine_tree / "dlls/winedmo" / n).read_text() for n in NAMES}
for needle, name in ((WL, "unix_demuxer.c"), (OPT, "unix_demuxer.c"), (TLS, "unix_demuxer.c")):
    assert sources[name].count(needle) == 1, (name, needle)
# media_source.c has two creates (the scheme callback is the last one); edit the last occurrence there.
assert sources["media_source.c"].count(CREATE) >= 1


def run(mutate):
    with tempfile.TemporaryDirectory(prefix="rtsp-se4-contract-") as tmp:
        folder = Path(tmp) / "dlls/winedmo"
        folder.mkdir(parents=True)
        texts = dict(sources)
        mutate(texts)
        for name, text in texts.items():
            (folder / name).write_text(text)
        return subprocess.run([sys.executable, "-I", str(audit), "--wine-tree", tmp, "--se4-network-contract"],
                              capture_output=True, text=True)


def edit(name, old, new, count=1):
    def apply(texts):
        text = texts[name]
        assert text.count(old) >= 1, old
        if name == "media_source.c":
            at = text.rindex(old)
            texts[name] = text[:at] + new + text[at + len(old):]
        else:
            texts[name] = text.replace(old, new, count)
    return apply


cases = [
    ("original SE4 tree", lambda t: None, True),
    # A fallback reintroduced.
    ("callback regains the BAD_NETWORK_PATH branch", edit("media_source.c", CREATE,
        CREATE + " {} if (hr == HRESULT_FROM_NT(STATUS_BAD_NETWORK_PATH)) hr = E_FAIL; if (0)"), False),
    ("callback regains urlmon marker", edit("media_source.c", CREATE, "/* urlmon */ " + CREATE), False),
    ("cache_http_url returns", edit("media_source.c", CREATE, "/* cache_http_url */ " + CREATE), False),
    ("URLOpenBlockingStreamW returns", edit("media_source.c", CREATE, "/* URLOpenBlockingStreamW */ " + CREATE), False),
    ("callback creates the source twice", edit("media_source.c", CREATE, CREATE + " {} media_source_create(context, NULL); if (0)"), False),
    ("callback swallows the failure", edit("media_source.c", "IMFAsyncResult_SetStatus(context->result, hr);",
        "hr = S_OK; IMFAsyncResult_SetStatus(context->result, hr);"), False),
    ("fallback signal returns to the demuxer", edit("unix_demuxer.c", WL, WL + "\n/* http_open_allows_urlmon_fallback STATUS_BAD_NETWORK_PATH */"), False),
    # Old whitelist elements and a loosened list.
    ("old HTTPS whitelist define", edit("unix_demuxer.c", WL, WL + '\n#define HTTPS_PROTOCOL_WHITELIST "https,httpproxy,tcp,tls"'), False),
    ("old HLS whitelist define", edit("unix_demuxer.c", WL, WL + '\n#define HTTP_HLS_PROTOCOL_WHITELIST "http,https,httpproxy,tcp,tls,crypto"'), False),
    ("old HTTPS HLS whitelist define", edit("unix_demuxer.c", WL, WL + '\n#define HTTPS_HLS_PROTOCOL_WHITELIST "https,httpproxy,tcp,tls,crypto"'), False),
    ("file in the list", edit("unix_demuxer.c", WL, WL.replace('"http,', '"file,http,')), False),
    ("GE list altered", edit("unix_demuxer.c", WL, WL.replace(",data", "")), False),
    ("second whitelist define", edit("unix_demuxer.c", WL, WL + '\n' + WL), False),
    ("an open uses a different whitelist", edit("unix_demuxer.c", OPT,
        'if (av_dict_set( &options, "protocol_whitelist", "http,https,file", 0 ) < 0) goto failed;'), False),
    # TLS verification and the hooks.
    ("HTTP tls_verify missing", edit("unix_demuxer.c", TLS, "/* no tls_verify */"), False),
    ("RTSPS tls_verify missing", edit("unix_demuxer.c", 'DIRECT_NETWORK_RTSPS_TCP &&\n            av_dict_set_int( &options, "tls_verify", 1, 0 ) < 0',
        'DIRECT_NETWORK_RTSPS_TCP &&\n            av_dict_set_int( &options, "tls_verify", 0, 0 ) < 0'), False),
    ("io_open hook returns", edit("unix_demuxer.c", WL, WL + "\n/* demuxer_io_open */"), False),
    ("seg_max_retry returns", edit("unix_demuxer.c", WL, WL + "\n/* seg_max_retry */"), False),
    ("top-level reconnect options missing", edit("unix_demuxer.c", "if (set_http_reconnect_options( &options, reconnect ) < 0) goto failed;", ""), False),
]
failed = 0
for name, mutate, expect_pass in cases:
    proc = run(mutate)
    ok = (proc.returncode == 0) == expect_pass
    print(("PASS " if ok else "FAIL ") + name + ("" if proc.returncode == 0 else "  [" + proc.stdout.strip().splitlines()[-1][:110] + "]" if proc.stdout.strip() else "  [" + (proc.stderr.strip().splitlines() or ["?"])[-1][:110] + "]"))
    failed += not ok
raise SystemExit(1 if failed else 0)
