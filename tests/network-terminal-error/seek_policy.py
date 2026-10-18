#!/usr/bin/env python3
"""Source ownership checks for historical interrupt/reuse and serialized seeks.

These are structural checks, not a runtime race or responsiveness oracle.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import re


def region(text: str, first: str, last: str) -> str:
    begin = text.index(first)
    return text[begin:text.index(last, begin)]


def ordered(text: str, *terms: str) -> None:
    position = 0
    for term in terms:
        found = text.find(term, position)
        if found < 0:
            raise ValueError(f"missing/out-of-order seek ownership term: {term}")
        position = found + len(term)


def check_seek_ownership(source: str, demuxer: str) -> str:
    """Check source-side ownership and classify its AVIO policy.

    Full historical partial-packet/EXIT-repair checks remain in the
    progressive-HTTP auditor; this helper does not replace those checks.
    """
    shutdown = region(source, "static HRESULT WINAPI media_source_Shutdown",
                      "static const IMFMediaSourceVtbl")
    create = region(source, "static HRESULT media_source_create",
                    "static HRESULT result_entry_create")
    for body, owner in ((shutdown, "source"), (create, "object")):
        ordered(body, f"winedmo_demuxer_set_cancelled({owner}->demuxer, TRUE)",
                f"WaitForSingleObject({owner}->demux_thread, INFINITE)",
                f"winedmo_demuxer_destroy(&{owner}->demuxer)")

    start = region(source, "static HRESULT media_source_start",
                   "static HRESULT media_source_pause")
    if "winedmo_demuxer_set_cancelled(" in start:
        ordered(start, "winedmo_demuxer_set_cancelled(source->demuxer, TRUE)",
                "EnterCriticalSection(&source->demuxer_cs)",
                "winedmo_demuxer_set_cancelled(source->demuxer, FALSE)",
                "winedmo_demuxer_seek(source->demuxer, position->hVal.QuadPart)")
        if "BOOL cancelled_read_pending_recovery;" not in demuxer:
            raise ValueError("interrupt/reuse seek lost its AVIO recovery state")
        # P23: the first read after a seek that followed a cancelled read
        # reopens HTTP instead of short-seeking on the interrupted transport.
        if "demuxer->ctx->pb->direct = 1;" in demuxer:
            return "interrupt-fresh"
        return "interrupt-reuse"

    # Shutdown/failed construction may still cancel contexts they will destroy.
    # A serialized ordinary seek must neither cancel nor reset those contexts.
    calls = re.findall(r"winedmo_demuxer_set_cancelled\s*\([^;]+;", source)
    expected = [f"winedmo_demuxer_set_cancelled({owner}->demuxer, TRUE);"
                for owner in ("source", "object")]
    if sorted(calls) != sorted(expected):
        raise ValueError("serialized seek has cancellation outside the two teardown owners")
    ordered(start,
            "source->demux_seek_pending = true;",
            "LeaveCriticalSection(&source->cs);",
            "EnterCriticalSection(&source->demuxer_cs);",
            "EnterCriticalSection(&source->cs);",
            "if (FAILED(seek_error = media_source_get_demux_error(source)))",
            "status = STATUS_SUCCESS;",
            "else if (source->state == SOURCE_SHUTDOWN || source->demux_thread_shutdown)",
            "status = STATUS_CANCELLED;",
            "else\n        {",
            "LeaveCriticalSection(&source->cs);",
            "status = winedmo_demuxer_seek(source->demuxer, position->hVal.QuadPart);",
            "EnterCriticalSection(&source->cs);",
            "if (!status && (source->state == SOURCE_SHUTDOWN",
            "|| source->demux_thread_shutdown))",
            "status = STATUS_CANCELLED;",
            "source->demux_seek_pending = false;",
            "WakeAllConditionVariable(&source->work_cv);",
            "LeaveCriticalSection(&source->demuxer_cs);")
    pending = region(start, "source->demux_seek_pending = true;",
                     "LeaveCriticalSection(&source->demuxer_cs);")
    if re.search(r"\b(?:return|goto)\b", pending):
        raise ValueError("pending seek can bypass its common clear/wake/unlock")
    if "cancelled_read_pending_recovery" in demuxer:
        raise ValueError("serialized seek retains unreachable reusable-cancel recovery")
    if re.search(r"->(?:error|eof_reached)\s*=\s*0\s*;", demuxer):
        raise ValueError("serialized seek clears an AVIO error/EOF instead of preserving failure")
    return "serialized"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wine-tree", type=Path, required=True)
    args = parser.parse_args()
    try:
        directory = args.wine_tree / "dlls/winedmo"
        policy = check_seek_ownership(
            (directory / "media_source.c").read_text(encoding="utf-8"),
            (directory / "unix_demuxer.c").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"FAIL: seek ownership: {exc}") from exc
    print(f"PASS: seek ownership ({policy}); structural evidence only")


if __name__ == "__main__":
    main()
