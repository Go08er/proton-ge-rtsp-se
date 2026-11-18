#!/usr/bin/env python3
"""Audit prepared Wine source for A3.8 pause/scrub ordering."""

from __future__ import annotations

import argparse
from pathlib import Path
import re


def fail(message: str) -> None:
    raise SystemExit(f"media-engine pause/scrub audit failed: {message}")


def region(text: str, start: str, end: str) -> str:
    try:
        begin = text.index(start)
        finish = text.index(end, begin)
    except ValueError as exc:
        fail(f"could not isolate source region: {exc}")
    return text[begin:finish]


def require(body: str, needle: str, message: str) -> None:
    if needle not in body:
        fail(message)


def require_order(body: str, *needles: str) -> None:
    try:
        positions = [body.index(needle) for needle in needles]
    except ValueError as exc:
        fail(f"required ordering term is absent: {exc}")
    if positions != sorted(positions):
        fail(f"required order changed: {' -> '.join(needles)}")


def engine_lock_helpers(engine: str) -> bool:
    # SE4-P6 (2026-11-14): 0046 puts the engine lock behind helpers and delivers notifications outside it. Detected
    # from the tree (the helper definitions), as audit-patched-wine.sh does from the series; the two must agree.
    return ("static void media_engine_lock_common(" in engine
            and "static void media_engine_deliver_event(" in engine)


def require_order_alt(body: str, *needles) -> None:
    # Like require_order; a needle may be a tuple of alternatives, positioned at the earliest one that occurs.
    positions = []
    for needle in needles:
        alts = (needle,) if isinstance(needle, str) else needle
        found = [body.index(alt) for alt in alts if alt in body]
        if not found:
            fail(f"required ordering term is absent: {alts[0]}")
        positions.append(min(found))
    if positions != sorted(positions):
        fail(f"required order changed: {' -> '.join(n if isinstance(n, str) else n[0] for n in needles)}")


def audit_autoplay(autoplay: str, text: str) -> None:
    flag = "media_engine_set_flag(engine, FLAGS_ENGINE_AUTO_PLAY, autoplay);"
    require(autoplay, flag, "SetAutoPlay no longer stores the requested property")
    if "autoplay_armed" in text:
        fail("unreviewed pending-load autoplay intent was added")
    if "IMFMediaEngineEx_Play(iface)" not in autoplay:
        return  # Historical GE/A3.8/SE1 property-only setter remains accepted.

    # Optional module 0034 starts only an idle, live, not-already-requested
    # presentation. It must store the property before synchronous Play callbacks
    # so a nested setter is the latest intent, and propagate Play's HRESULT.
    guard = ("if (autoplay && !(engine->flags & FLAGS_ENGINE_SHUT_DOWN)\n"
             "            && engine->network_state == MF_MEDIA_ENGINE_NETWORK_IDLE\n"
             "            && !engine->playback_requested)\n"
             "        hr = IMFMediaEngineEx_Play(iface);")
    require(autoplay, "HRESULT hr = S_OK;", "ready-source autoplay has no success default")
    require(autoplay, guard, "ready-source autoplay lost its source/intent guards")
    if engine_lock_helpers(text):
        require_order_alt(autoplay, ("EnterCriticalSection(&engine->cs);", "media_engine_lock(engine, __func__);"),
                          flag, guard,
                          ("LeaveCriticalSection(&engine->cs);", "media_engine_unlock(engine);"), "return hr;")
    else:
        require_order(autoplay, "EnterCriticalSection(&engine->cs);", flag, guard,
                      "LeaveCriticalSection(&engine->cs);", "return hr;")
    if autoplay.count("media_engine_set_flag") != 1 or autoplay.count("IMFMediaEngineEx_Play") != 1:
        fail("ready-source autoplay repeats playback or overwrites a newer setter")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_root", type=Path)
    parser.add_argument(
        "--diagnostic-contract",
        choices=("present", "absent"),
        required=True,
    )
    args = parser.parse_args()

    source_root = args.source_root.resolve()
    source_path = source_root / "dlls" / "mfmediaengine" / "main.c"
    if not source_path.is_file():
        fail(f"missing source file: {source_path}")
    text = source_path.read_text(encoding="utf-8")

    events = region(text, "static HRESULT WINAPI media_engine_session_events_Invoke(",
                    "static const IMFAsyncCallbackVtbl media_engine_session_events_vtbl")
    rate = region(events, "case MESessionRateChanged:",
                  "case MESessionScrubSampleComplete:")
    paused = region(events, "case MESessionPaused:", "    }\n\nfailed:")
    play = region(text, "static HRESULT WINAPI media_engine_Play(",
                  "static HRESULT WINAPI media_engine_Pause(")
    pause = region(text, "static HRESULT WINAPI media_engine_Pause(",
                   "static BOOL WINAPI media_engine_GetMuted(")
    autoplay = region(text, "static HRESULT WINAPI media_engine_SetAutoPlay(",
                      "static BOOL WINAPI media_engine_GetLoop(")

    pending_clear = (
        "media_engine_set_flag(engine, "
        "FLAGS_ENGINE_PLAY_PENDING | FLAGS_ENGINE_WAITING, FALSE);"
    )

    require(pause, pending_clear,
            "Pause can leave stale waiting/play scheduling state")
    require_order(
        pause,
        "engine->playback_requested = FALSE;",
        pending_clear,
        "if (engine->flags & FLAGS_ENGINE_PAUSE_PENDING)",
    )
    require(paused, pending_clear,
            "pause completion can leave stale waiting/play scheduling state")
    require(rate, pending_clear,
            "rate completion can leave stale waiting/play scheduling state")
    require(paused, "scrubbing = !!(engine->flags & FLAGS_ENGINE_SCRUBBING);",
            "pause completion does not snapshot scrub ownership")
    require_order(
        paused,
        "if (scrubbing)",
        "if (engine->flags & FLAGS_ENGINE_PAUSE_PENDING)",
        "media_engine_set_flag(engine, FLAGS_ENGINE_PAUSE_PENDING, FALSE);",
        "if (!engine->playback_requested)",
    )
    if "else if (engine->flags & FLAGS_ENGINE_PAUSE_PENDING)" in paused:
        fail("pending pause is still skipped while scrubbing")
    require(paused, "else if (scrubbing)",
            "latest Play is not deferred to the scrub rate completion")
    require_order(
        paused,
        "else if (scrubbing)",
        "media_engine_set_flag(engine, FLAGS_ENGINE_PLAY_PENDING, TRUE);",
        "media_engine_set_flag(engine, FLAGS_ENGINE_PAUSED, FALSE);",
    )
    require(paused, "start_pending = TRUE;",
            "non-scrub Play-after-Pause cannot restart")

    require_order(
        rate,
        "media_engine_set_flag(engine, FLAGS_ENGINE_SCRUBBING, FALSE);",
        "if (!engine->playback_requested)",
        "else if (engine->flags & FLAGS_ENGINE_PAUSE_PENDING)",
        "else if (engine->flags & FLAGS_ENGINE_PLAY_PENDING)",
    )
    require(rate, "media_engine_start_playback(engine);",
            "rate completion has no guarded restart")
    q_clear = "media_engine_set_flag(engine, FLAGS_ENGINE_PAUSE_PENDING, FALSE);"
    if q_clear in rate:
        fail("rate completion clears a possibly newer pending pause")

    require(play, "engine->playback_requested = TRUE;",
            "Play does not record latest caller intent")
    audit_autoplay(autoplay, text)

    trace_markers = (
        "call Play",
        "call Pause",
        "call SetAutoPlay",
        "event MESessionPaused",
        "event MESessionRateChanged",
    )
    if args.diagnostic_contract == "present":
        for marker in trace_markers:
            require(text, marker, f"bounded A3.8 transition trace lacks {marker}")
    else:
        # SE4-P6: 0046's comments mention "call Play()"; with its helpers present the markers are looked for in the
        # code and string literals only, not in C comments (they are TRACE strings, never comment text).
        scanned = re.sub(r"/\*.*?\*/", "", text, flags=re.S) if engine_lock_helpers(text) else text
        for marker in (
            "WINE_DECLARE_DEBUG_CHANNEL(avprostate);",
            "TRACE_(avprostate)",
            *trace_markers,
        ):
            if marker in scanned:
                fail(f"diagnostic-free source retains {marker}")

    print("media-engine pause/scrub source audit passed")


if __name__ == "__main__":
    main()
