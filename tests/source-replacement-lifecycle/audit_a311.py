#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""Audit A3.11's physical-clock synchronization before replacement start."""

from __future__ import annotations

from pathlib import Path
import re
import sys


def fail(message: str) -> None:
    raise SystemExit(f"A3.11 replacement-clock audit failed: {message}")


def region(text: str, start: str, end: str) -> str:
    try:
        begin = text.index(start)
        finish = text.index(end, begin)
    except ValueError as exc:
        fail(f"could not isolate source region: {exc}")
    return text[begin:finish]


def require_order(body: str, *needles: str) -> None:
    position = -1
    for needle in needles:
        position = body.find(needle, position + 1)
        if position < 0:
            fail(f"required ordering term is absent: {needle}")


def braced_body(text: str, condition: str) -> str:
    """Isolate a braced arm in this known source layout, not a general C parser."""
    try:
        tail = text[text.index(condition) + len(condition):].lstrip()
    except ValueError:
        fail(f"missing guarded block: {condition}")
    if not tail.startswith("{"):
        fail(f"condition does not own a braced body: {condition}")
    depth = 0
    for index, char in enumerate(tail):
        depth += (char == "{") - (char == "}")
        if depth == 0:
            return tail[1:index]
    fail(f"unterminated guarded block: {condition}")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(f"usage: {Path(sys.argv[0]).name} /path/to/src-wine")

    session_path = Path(sys.argv[1]).resolve() / "dlls" / "mf" / "session.c"
    if not session_path.is_file():
        fail("prepared MediaSession source is missing")

    session = session_path.read_text(encoding="utf-8")
    clear_presentation = region(
        session,
        "static void session_clear_presentation(",
        "static struct topo_node *session_get_topo_node(",
    )
    session_start = region(
        session,
        "static void session_start(",
        "static void session_set_started(",
    )
    session_stop = region(
        session,
        "static void session_stop(",
        "static HRESULT session_finalize_sinks(",
    )
    sink_state = region(
        session,
        "static void session_set_sink_stream_state(",
        "static HRESULT transform_get_external_output_sample(",
    )
    state_helper = region(
        session,
        "static enum object_state session_get_object_state_for_event(",
        "static HRESULT session_start_clock(",
    )
    state_call = "session_get_object_state_for_event(event_type)"
    if ("session_get_object_state_for_event(struct media_session *session, MediaEventType event)"
            in state_helper):
        # New GE also ignores attachment-induced Stop notifications while sinks
        # start. This complements, rather than replaces, our one-shot barrier.
        stopped = region(state_helper, "case MEStreamSinkStopped:",
                         "case MEStreamSinkPrerolled:")
        stopped = re.sub(r"/\*.*?\*/", "", stopped, flags=re.S)
        expected = """
            case MEStreamSinkStopped:
                if (session->command_state == COMMAND_STATE_PREROLLING_SINKS || session->command_state == COMMAND_STATE_STARTING_SINKS)
                    return OBJ_STATE_INVALID;
            case MESourceStopped:
            case MEStreamStopped:
                return OBJ_STATE_STOPPED;
        """
        if " ".join(stopped.split()) != " ".join(expected.split()):
            fail("sink Stop filtering must be limited to prerolling/starting sinks")
        state_call = "session_get_object_state_for_event(session, event_type)"
        require_order(
            sink_state,
            f"if ((state = {state_call}) == OBJ_STATE_INVALID)",
            "return;",
            "session_set_node_object_state(session, (IUnknown *)stream, MF_TOPOLOGY_OUTPUT_NODE, state)",
        )
    elif "session_get_object_state_for_event(MediaEventType event)" not in state_helper:
        fail("unrecognized event-state helper signature")
    legacy_arm = "topo_node->flags |= TOPO_NODE_EXPECT_INITIAL_CLOCK_STOP;"
    legacy_terms = (
        "LIST_FOR_EACH_ENTRY(topo_node, &session->presentation.nodes, struct topo_node, entry)",
        "topo_node->type == MF_TOPOLOGY_OUTPUT_NODE",
        legacy_arm,
    ) if legacy_arm in session_start else ()
    require_order(
        session_start,
        "sources_stopped = session_is_source_nodes_state(session, OBJ_STATE_STOPPED);",
        "if (sources_stopped)",
        "IMFPresentationClock_GetState(session->clock, 0, &clock_state)",
        'WARN("Failed to get replacement presentation clock state %p, hr %#lx.\\n", session, hr);',
        "session_command_complete_with_event(session, MESessionStarted, hr, NULL);",
        "return;",
        "if (clock_state != MFCLOCK_STATE_INVALID)",
        "if (clock_state != MFCLOCK_STATE_STOPPED",
        "IMFPresentationClock_Stop(session->clock)",
        'WARN("Failed to stop replacement presentation clock %p, hr %#lx.\\n", session, hr);',
        "session_command_complete_with_event(session, MESessionStarted, hr, NULL);",
        "return;",
        *legacy_terms,
        "session->state = SESSION_STATE_STOPPED;",
        "session->clock_started = FALSE;",
        "case SESSION_STATE_STOPPED:",
        "session->command_state = COMMAND_STATE_STARTING_SOURCES;",
        "session_subscribe_sources(session)",
        "IMFMediaSource_Start(source->source, source->pd, &GUID_NULL, start_position)",
    )
    if session_start.count("IMFPresentationClock_Stop(session->clock)") != 1:
        fail("replacement branch must own exactly one physical-clock stop")
    if len(re.findall(r"\bflags\s*\|=\s*\(*\s*TOPO_NODE_EXPECT_INITIAL_CLOCK_STOP\b", session)) != 1:
        fail("initial clock-Stop expectation must have exactly one arming owner")
    if not legacy_terms:
        # Updated candidates arm at actual first attachment, including a new
        # source after MESessionEnded. Retained pins keep their historical audit.
        attachment = region(session, "static void session_set_presentation_clock(",
                            "static void session_set_rate(")
        attachment = braced_body(attachment,
            "if (!(session->presentation.flags & SESSION_FLAG_PRESENTATION_CLOCK_SET))")
        arming = braced_body(attachment,
            "if (SUCCEEDED(IMFPresentationClock_GetState(session->clock, 0, &clock_state))\n"
            "                && clock_state == MFCLOCK_STATE_STOPPED)")
        expected = """
            LIST_FOR_EACH_ENTRY(node, &session->presentation.nodes, struct topo_node, entry)
            {
                if (node->type == MF_TOPOLOGY_OUTPUT_NODE)
                    node->flags |= TOPO_NODE_EXPECT_INITIAL_CLOCK_STOP;
            }
        """
        if " ".join(arming.split()) != " ".join(expected.split()):
            fail("stopped-clock arming must be exactly the guarded output-node loop")
        require_order(
            attachment,
            "IMFPresentationClock_SetTimeSource(session->clock,",
            "if (SUCCEEDED(IMFPresentationClock_GetState(session->clock, 0, &clock_state))",
            "&& clock_state == MFCLOCK_STATE_STOPPED)",
            "LIST_FOR_EACH_ENTRY(node, &session->presentation.nodes, struct topo_node, entry)",
            "if (node->type == MF_TOPOLOGY_OUTPUT_NODE)",
            "node->flags |= TOPO_NODE_EXPECT_INITIAL_CLOCK_STOP;",
            "IMFMediaSink_SetPresentationClock(sink->sink, session->clock)",
            "session->presentation.flags |= SESSION_FLAG_PRESENTATION_CLOCK_SET;",
        )
    require_order(
        clear_presentation,
        "LIST_FOR_EACH_ENTRY_SAFE(sink, sink2, &session->presentation.sinks",
        "list_remove(&sink->entry);",
        "IMFMediaSink_SetPresentationClock(sink->sink, NULL)",
        "IMFMediaSink_Release(sink->sink);",
    )
    require_order(
        sink_state,
        "session_get_node_object(session, (IUnknown *)stream, MF_TOPOLOGY_OUTPUT_NODE)",
        "node->flags & TOPO_NODE_EXPECT_INITIAL_CLOCK_STOP",
        "event_type == MEStreamSinkStopped",
        "node->flags &= ~TOPO_NODE_EXPECT_INITIAL_CLOCK_STOP;",
        'TRACE("Ignoring initial sink Stop for replacement session %p.\\n", session);',
        "return;",
        "event_type == MEStreamSinkStarted",
        "node->flags &= ~TOPO_NODE_EXPECT_INITIAL_CLOCK_STOP;",
        state_call,
    )
    if session.count("TOPO_NODE_EXPECT_INITIAL_CLOCK_STOP = 0x10") != 1:
        fail("one-shot initial-Stop node flag is absent or duplicated")
    require_order(
        session_stop,
        "IMFPresentationClock_Stop(session->clock)",
        "session->clock_started = FALSE;",
        "session->command_state = COMMAND_STATE_STOPPING_SINKS;",
    )
    print("A3.11 replacement-clock source audit passed")


if __name__ == "__main__":
    main()
