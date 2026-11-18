#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""Deterministic models and patch-scope checks for Patches 14 through 16."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SERIES = ROOT / "patches/series"
NOTICE = ROOT / "NOTICE.md"
PATCH14_NAME = "experimental/0014-mfmediaengine-preserve-pending-start-position.patch"
SPLIT_PATCH15_NAME = (
    "experimental/0015-mf-subscribe-replacement-source-before-restart.patch"
)
SPLIT_PATCH16_NAME = (
    "experimental/0016-mf-stop-live-clock-before-replacement-start.patch"
)
COMBINED_PATCH15_NAME = "experimental/0015-mf-order-immediate-replacement-start.patch"
PATCH17_NAME = "experimental/0017-winedmo-propagate-terminal-network-read-errors.patch"
PATCH14 = SERIES.parent / PATCH14_NAME
PATCH15 = SERIES.parent / COMBINED_PATCH15_NAME
PATCH16 = PATCH15
ACTIVE_REPLACEMENT_WINDOW = (PATCH14_NAME, COMBINED_PATCH15_NAME, PATCH17_NAME)
SPLIT_PATCH_PRESENTATION = False
CONSOLIDATED_PRESENTATION = False
CONSOLIDATED_SESSION = "ge-proton11-9-se2-p20/0006-mf-retain-session-lifecycle-and-demand-accounting.patch"
CONSOLIDATED_ENGINE = "ge-proton11-9-se2-p20/0008-mfmediaengine-retain-control-intent-and-buffering-events.patch"
VT_EMPTY = "VT_EMPTY"
VT_I8 = "VT_I8"


@dataclass
class StartPosition:
    vt: str = VT_EMPTY
    value: int = 0


@dataclass
class Presentation:
    source: object | None = None
    descriptor: object | None = None
    start: StartPosition = field(default_factory=StartPosition)
    frame_sink: object | None = None


@dataclass
class Engine:
    generation: int = 0
    presentation: Presentation = field(default_factory=Presentation)

    def stage_source(self, generation: int) -> None:
        self.generation = generation
        self.presentation.start = StartPosition(VT_I8, 0)

    def set_pending_time(self, generation: int, seconds: float) -> None:
        if generation == self.generation:
            self.presentation.start = StartPosition(VT_I8, round(seconds * 10_000_000))


def legacy_clear(engine: Engine, during_shutdown=None) -> None:
    engine.presentation = Presentation()
    if during_shutdown:
        during_shutdown()


def patch14_clear(engine: Engine, during_shutdown=None) -> None:
    engine.presentation.source = None
    engine.presentation.descriptor = None
    engine.presentation.frame_sink = None
    if during_shutdown:
        during_shutdown()


def started_session_reaches_source_start(position: StartPosition) -> bool:
    if position.vt == VT_EMPTY:
        return False
    if position.vt != VT_I8:
        raise AssertionError(f"unexpected pending variant {position.vt}")
    return True


@dataclass
class SessionRestart:
    sources_subscribed: bool = False
    source_state: str = "stopped"
    session_state: str = "started"
    clock_started: bool = True
    command_state: str = "submitted"
    source_stop_events_emitted: int = 0
    source_stop_events_observed: int = 0
    source_starts: int = 0
    clock_only_starts: int = 0
    subscribe_attempts: int = 0
    physical_clock_state: str = "running"
    clock_state_queries: int = 0
    clock_stop_attempts: int = 0
    clock_stop_fails: bool = False
    start_completion_status: str | None = None
    outgoing_sinks_attached: int = 2
    sink_detach_attempts: int = 0
    expected_initial_clock_stops: set[str] = field(default_factory=set)

    def subscribe_sources(self) -> None:
        if self.sources_subscribed:
            return
        self.subscribe_attempts += 1
        self.sources_subscribed = True

    def stop_source(self) -> None:
        self.source_stop_events_emitted += 1
        if not self.sources_subscribed:
            return
        self.source_stop_events_observed += 1
        changed = self.source_state != "stopped"
        self.source_state = "stopped"
        if not changed:
            return
        self.command_state = "starting_sources"
        self.source_starts += 1


def start_session(session: SessionRestart, *, keep_position: bool,
                  route_stopped_presentation: bool,
                  synchronize_physical_clock: bool = False) -> None:
    sources_stopped = session.source_state == "stopped"
    if session.session_state == "started" and keep_position \
            and not (route_stopped_presentation and sources_stopped):
        session.clock_only_starts += 1
        session.command_state = "complete"
        return

    if session.session_state in {"started", "paused"}:
        if route_stopped_presentation and sources_stopped:
            if synchronize_physical_clock:
                session.clock_state_queries += 1
                if session.physical_clock_state not in {"invalid", "stopped"}:
                    session.clock_stop_attempts += 1
                    if session.clock_stop_fails:
                        session.command_state = "complete"
                        session.start_completion_status = "clock-stop-failed"
                        return
                    session.physical_clock_state = "stopped"
                if session.physical_clock_state != "invalid":
                    session.expected_initial_clock_stops = {"audio", "video"}
            session.session_state = "stopped"
            session.clock_started = False
        elif not keep_position:
            session.command_state = "restarting_sources"
            session.stop_source()
            return

    session.command_state = "starting_sources"
    if not session.sources_subscribed:
        session.subscribe_sources()
    session.source_starts += 1


def clear_presentation(session: SessionRestart, *, detach_outgoing_sinks: bool) -> None:
    if detach_outgoing_sinks:
        session.sink_detach_attempts += session.outgoing_sinks_attached
        session.outgoing_sinks_attached = 0


@dataclass
class SinkTransition:
    audio: str = "stopped"
    video: str = "stopped"
    command_state: str = "prerolling_sinks"
    physical_clock_starts: int = 0
    session_started_events: int = 0
    stale_sink_starts: int = 0

    def event(self, sink: str, state: str) -> None:
        setattr(self, sink, state)
        if self.command_state == "prerolling_sinks" \
                and self.audio == self.video == "prerolled":
            self.physical_clock_starts += 1
            self.command_state = "starting_sinks"
        if self.command_state == "starting_sinks" \
                and self.audio == self.video == "started":
            self.session_started_events += 1
            self.command_state = "complete"


def deliver_sink_event(session: SessionRestart, transition: SinkTransition,
                       sink: str, state: str) -> None:
    if sink in session.expected_initial_clock_stops:
        if state == "stopped":
            session.expected_initial_clock_stops.remove(sink)
            return
        if state == "started":
            session.expected_initial_clock_stops.remove(sink)
    transition.event(sink, state)


def drive_replacement_sinks(session: SessionRestart) -> SinkTransition:
    transition = SinkTransition()
    if session.physical_clock_state == "running":
        # Exact A3.10 trace order: video inherited the live-clock Start before
        # audio's preroll acknowledgement, then audio inherited Start.
        transition.video = "prerolled"  # non-preroll sink marker
        transition.event("video", "started")
        transition.event("audio", "prerolled")
        transition.event("audio", "started")
        return transition

    # A stopped clock cannot synthesize Start during attachment, but its
    # asynchronous current-state Stop can arrive after the non-preroll video
    # sink was marked PREROLLED. Reproduce that adverse ordering explicitly.
    transition.video = "prerolled"
    deliver_sink_event(session, transition, "video", "stopped")
    transition.event("audio", "prerolled")
    if transition.physical_clock_starts == 0:
        return transition

    transition.stale_sink_starts += session.outgoing_sinks_attached
    deliver_sink_event(session, transition, "audio", "stopped")
    deliver_sink_event(session, transition, "audio", "started")
    deliver_sink_event(session, transition, "video", "started")
    return transition


def added_lines(patch: str) -> str:
    return "\n".join(
        line[1:]
        for line in patch.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    )


def configure_patch_contract(series: Path) -> None:
    global PATCH14_NAME, PATCH17_NAME, COMBINED_PATCH15_NAME
    global ACTIVE_REPLACEMENT_WINDOW
    global NOTICE
    global PATCH14
    global PATCH15
    global PATCH16
    global SERIES
    global SPLIT_PATCH_PRESENTATION
    global CONSOLIDATED_PRESENTATION
    global CONSOLIDATED_SESSION, CONSOLIDATED_ENGINE

    SERIES = series.resolve()
    if not SERIES.is_file():
        raise SystemExit(f"replacement model series is not a file: {SERIES}")
    entries = tuple(
        line
        for raw in SERIES.read_text(encoding="utf-8").splitlines()
        if (line := raw.strip()) and not line.startswith("#")
    )
    CONSOLIDATED_PRESENTATION = False
    consolidated = {entry.split("/", 1)[0] for entry in entries
                    if entry.startswith(("ge-proton11-9-se2-p20/", "ge-proton11-9-se2-p21/",
                                         "ge-proton11-9-se2-p22/",
                                         "ge-proton11-9-se2-p23/",
                                         "ge-proton11-9-se2-p24/",
                                         "ge-proton11-11-se3-p1/",
                                         "ge-proton11-11-se3-p2/",
                                         "ge-proton11-11-se3-p3/",
                                         "ge-proton11-11-se3-p4/",
                                         "ge-proton11-11-se3-p5/",
                                         "ge-proton11-11-se3-p6/",
                                         "ge-proton11-11-se3-p7/",
                                         "ge-proton11-11-se3-p8/",
                                         "ge-proton11-11-se3-p9/",
                                         "ge-proton11-12-se4-p1/",
                                         "ge-proton11-12-se4-p2/",
                                         "ge-proton11-12-se4-p3/",
                                         "ge-proton11-12-se4-p4/",
                                         "ge-proton11-12-se4-p6/"))}
    if consolidated:
        if len(consolidated) != 1:
            raise SystemExit("replacement model cannot mix immutable GE11-9 candidates")
        prefix = consolidated.pop()
        CONSOLIDATED_SESSION = prefix + "/0006-mf-retain-session-lifecycle-and-demand-accounting.patch"
        CONSOLIDATED_ENGINE = prefix + "/0008-mfmediaengine-retain-control-intent-and-buffering-events.patch"
        # GE11-9 groups residuals by component rather than historical patch number.
        # Keep the models below unchanged and check their actual replacement
        # ownership/clock statements in the two consolidated patches instead.
        if (entries.count(CONSOLIDATED_SESSION) != 1
                or entries.count(CONSOLIDATED_ENGINE) != 1
                or entries.index(CONSOLIDATED_SESSION) >= entries.index(CONSOLIDATED_ENGINE)
                or any(Path(entry).name.startswith(("0014-", "0015-", "0016-", "0017-"))
                       for entry in entries)):
            raise SystemExit("replacement model requires ordered, unique GE11-9 lifecycle components without legacy mixing")
        PATCH14_NAME, COMBINED_PATCH15_NAME = CONSOLIDATED_ENGINE, CONSOLIDATED_SESSION
        PATCH14 = SERIES.parent / CONSOLIDATED_ENGINE
        PATCH15 = PATCH16 = SERIES.parent / CONSOLIDATED_SESSION
        NOTICE = SERIES.parent.parent / "NOTICE.md"
        ACTIVE_REPLACEMENT_WINDOW = (CONSOLIDATED_SESSION, CONSOLIDATED_ENGINE)
        SPLIT_PATCH_PRESENTATION = False
        CONSOLIDATED_PRESENTATION = True
        return
    # Same lifecycle contract, two immutable source-base presentations.
    prefix = "ge-proton11-6" if any(
        entry.startswith("ge-proton11-6/") for entry in entries
    ) else "experimental"
    PATCH14_NAME = prefix + "/0014-mfmediaengine-preserve-pending-start-position.patch"
    combined_basename = "0015-mf-order-immediate-replacement-start.patch"
    combined_entries = [entry for entry in entries if Path(entry).name == combined_basename]
    if len(combined_entries) > 1:
        raise SystemExit("replacement model series declares duplicate combined-0015 basenames")
    # New candidates may amend our combined patch in their own directory while
    # retained series keep the original bytes. The surrounding window is fixed.
    COMBINED_PATCH15_NAME = combined_entries[0] if combined_entries else prefix + "/" + combined_basename
    PATCH17_NAME = prefix + "/0017-winedmo-propagate-terminal-network-read-errors.patch"
    a320_terminal = "ge-proton11-6-a320/0017-winedmo-propagate-terminal-network-read-errors.patch"
    if a320_terminal in entries:
        if PATCH17_NAME in entries:
            raise SystemExit("replacement model series declares two terminal-error patches")
        PATCH17_NAME = a320_terminal
    split_window = (
        PATCH14_NAME,
        SPLIT_PATCH15_NAME,
        SPLIT_PATCH16_NAME,
        PATCH17_NAME,
    )
    combined_window = (PATCH14_NAME, COMBINED_PATCH15_NAME, PATCH17_NAME)

    def window_count(window: tuple[str, ...]) -> int:
        return sum(
            entries[index:index + len(window)] == window
            for index in range(len(entries) - len(window) + 1)
        )

    split_count = window_count(split_window)
    combined_count = window_count(combined_window)
    if (split_count, combined_count) not in ((1, 0), (0, 1)):
        raise SystemExit(
            "replacement model series must declare exactly one supported "
            "Patch 14-to-17 presentation"
        )
    expected_counts = {
        PATCH14_NAME: 1,
        SPLIT_PATCH15_NAME: int(split_count == 1),
        SPLIT_PATCH16_NAME: int(split_count == 1),
        COMBINED_PATCH15_NAME: int(combined_count == 1),
        PATCH17_NAME: 1,
    }
    if any(entries.count(name) != count for name, count in expected_counts.items()):
        raise SystemExit(
            "replacement model series contains a duplicate, mixed, or partial "
            "Patch 14-to-17 presentation"
        )

    patch_root = SERIES.parent
    NOTICE = patch_root.parent / "NOTICE.md"
    PATCH14 = patch_root / PATCH14_NAME
    SPLIT_PATCH_PRESENTATION = split_count == 1
    if SPLIT_PATCH_PRESENTATION:
        PATCH15 = patch_root / SPLIT_PATCH15_NAME
        PATCH16 = patch_root / SPLIT_PATCH16_NAME
        ACTIVE_REPLACEMENT_WINDOW = split_window
    else:
        PATCH15 = patch_root / COMBINED_PATCH15_NAME
        PATCH16 = PATCH15
        ACTIVE_REPLACEMENT_WINDOW = combined_window


class ReplacementLifecycleModelTests(unittest.TestCase):
    def populated_engine(self) -> Engine:
        engine = Engine()
        engine.stage_source(2)
        engine.presentation.source = object()
        engine.presentation.descriptor = object()
        engine.presentation.frame_sink = object()
        return engine

    def test_a38_whole_clear_reproduces_no_source_start(self) -> None:
        engine = self.populated_engine()
        legacy_clear(engine)
        self.assertEqual(engine.presentation.start.vt, VT_EMPTY)
        self.assertFalse(started_session_reaches_source_start(engine.presentation.start))

    def test_patch14_running_replacement_restarts_source_at_zero(self) -> None:
        engine = self.populated_engine()
        patch14_clear(engine)
        self.assertEqual(engine.presentation.start, StartPosition(VT_I8, 0))
        self.assertTrue(started_session_reaches_source_start(engine.presentation.start))
        self.assertIsNone(engine.presentation.source)
        self.assertIsNone(engine.presentation.descriptor)
        self.assertIsNone(engine.presentation.frame_sink)

    def test_same_generation_pre_ready_offset_survives(self) -> None:
        engine = self.populated_engine()
        engine.set_pending_time(2, 47.25)
        patch14_clear(engine)
        self.assertEqual(engine.presentation.start, StartPosition(VT_I8, 472_500_000))

    def test_reentrant_new_generation_update_is_not_overwritten(self) -> None:
        engine = self.populated_engine()

        def newer_request_during_shutdown() -> None:
            engine.stage_source(3)
            engine.set_pending_time(3, 91.5)

        patch14_clear(engine, newer_request_during_shutdown)
        self.assertEqual(engine.generation, 3)
        self.assertEqual(engine.presentation.start, StartPosition(VT_I8, 915_000_000))

    def test_a39_orphans_replacement_source_stop_event(self) -> None:
        session = SessionRestart()
        start_session(session, keep_position=False, route_stopped_presentation=False)
        self.assertEqual(session.source_stop_events_emitted, 1)
        self.assertEqual(session.source_stop_events_observed, 0)
        self.assertEqual(session.command_state, "restarting_sources")
        self.assertEqual(session.source_starts, 0)

    def test_patch15_routes_stopped_replacement_through_fresh_start(self) -> None:
        session = SessionRestart()
        start_session(session, keep_position=False, route_stopped_presentation=True)
        self.assertTrue(session.sources_subscribed)
        self.assertEqual(session.subscribe_attempts, 1)
        self.assertEqual(session.source_stop_events_emitted, 0)
        self.assertEqual(session.session_state, "stopped")
        self.assertFalse(session.clock_started)
        self.assertEqual(session.command_state, "starting_sources")
        self.assertEqual(session.source_starts, 1)
        self.assertEqual(session.physical_clock_state, "running")

    def test_a310_live_clock_reproduces_preroll_deadlock(self) -> None:
        session = SessionRestart()
        start_session(session, keep_position=False,
                      route_stopped_presentation=True)
        transition = drive_replacement_sinks(session)
        self.assertEqual(transition.command_state, "prerolling_sinks")
        self.assertEqual(transition.session_started_events, 0)
        self.assertEqual(transition.physical_clock_starts, 0)

    def test_patch16_stops_physical_clock_before_sink_attachment(self) -> None:
        session = SessionRestart()
        clear_presentation(session, detach_outgoing_sinks=True)
        start_session(session, keep_position=False,
                      route_stopped_presentation=True,
                      synchronize_physical_clock=True)
        self.assertEqual(session.clock_state_queries, 1)
        self.assertEqual(session.clock_stop_attempts, 1)
        self.assertEqual(session.physical_clock_state, "stopped")
        self.assertEqual(session.sink_detach_attempts, 2)
        self.assertEqual(session.expected_initial_clock_stops, {"audio", "video"})
        transition = drive_replacement_sinks(session)
        self.assertEqual(transition.physical_clock_starts, 1)
        self.assertEqual(transition.session_started_events, 1)
        self.assertEqual(transition.command_state, "complete")
        self.assertEqual(transition.stale_sink_starts, 0)
        self.assertEqual(session.expected_initial_clock_stops, set())

    def test_stopped_clock_without_stale_stop_filter_reproduces_preroll_deadlock(self) -> None:
        session = SessionRestart()
        clear_presentation(session, detach_outgoing_sinks=True)
        start_session(session, keep_position=False,
                      route_stopped_presentation=True,
                      synchronize_physical_clock=True)
        session.expected_initial_clock_stops.clear()
        transition = drive_replacement_sinks(session)
        self.assertEqual(transition.video, "stopped")
        self.assertEqual(transition.audio, "prerolled")
        self.assertEqual(transition.physical_clock_starts, 0)
        self.assertEqual(transition.command_state, "prerolling_sinks")

    def test_one_shot_filter_preserves_real_later_stop_transition(self) -> None:
        session = SessionRestart(expected_initial_clock_stops=set())
        transition = SinkTransition(audio="started", video="started",
                                    command_state="stopping_sinks")
        deliver_sink_event(session, transition, "audio", "stopped")
        self.assertEqual(transition.audio, "stopped")

    def test_clock_stop_without_sink_detach_restarts_obsolete_renderers(self) -> None:
        session = SessionRestart()
        clear_presentation(session, detach_outgoing_sinks=False)
        start_session(session, keep_position=False,
                      route_stopped_presentation=True,
                      synchronize_physical_clock=True)
        transition = drive_replacement_sinks(session)
        self.assertEqual(transition.session_started_events, 1)
        self.assertEqual(transition.stale_sink_starts, 2)

    def test_patch16_propagates_clock_stop_failure_without_false_state(self) -> None:
        session = SessionRestart(clock_stop_fails=True)
        start_session(session, keep_position=False,
                      route_stopped_presentation=True,
                      synchronize_physical_clock=True)
        self.assertEqual(session.start_completion_status, "clock-stop-failed")
        self.assertEqual(session.session_state, "started")
        self.assertTrue(session.clock_started)
        self.assertEqual(session.source_starts, 0)

    def test_patch16_skips_stop_for_an_invalid_or_stopped_clock(self) -> None:
        for state in ("invalid", "stopped"):
            with self.subTest(state=state):
                session = SessionRestart(physical_clock_state=state)
                start_session(session, keep_position=False,
                              route_stopped_presentation=True,
                              synchronize_physical_clock=True)
                self.assertEqual(session.clock_state_queries, 1)
                self.assertEqual(session.clock_stop_attempts, 0)
                self.assertEqual(session.source_starts, 1)

    def test_patch15_is_noop_for_an_ordinary_subscribed_seek(self) -> None:
        session = SessionRestart(sources_subscribed=True, source_state="started")
        start_session(session, keep_position=False, route_stopped_presentation=True)
        self.assertEqual(session.subscribe_attempts, 0)
        self.assertEqual(session.source_stop_events_observed, 1)
        self.assertEqual(session.command_state, "starting_sources")
        self.assertEqual(session.source_starts, 1)

    def test_patch15_does_not_clock_only_start_a_stopped_replacement(self) -> None:
        session = SessionRestart()
        start_session(session, keep_position=True, route_stopped_presentation=True)
        self.assertEqual(session.clock_only_starts, 0)
        self.assertEqual(session.source_starts, 1)
        self.assertFalse(session.clock_started)

    def test_existing_started_keep_position_remains_clock_only(self) -> None:
        session = SessionRestart(sources_subscribed=True, source_state="started")
        start_session(session, keep_position=True, route_stopped_presentation=True)
        self.assertEqual(session.clock_only_starts, 1)
        self.assertEqual(session.source_starts, 0)


class Patch14ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if CONSOLIDATED_PRESENTATION:
            raise unittest.SkipTest("consolidated component layout uses ConsolidatedContractTests")
        cls.patch = PATCH14.read_text(encoding="utf-8")
        cls.added = added_lines(cls.patch)

    def test_patch14_through_patch17_are_ordered_and_patch14_is_single_file(self) -> None:
        entries = [line for line in SERIES.read_text(encoding="utf-8").splitlines()
                   if line and not line.startswith("#")]
        start = entries.index(PATCH14_NAME)
        self.assertEqual(tuple(entries[start:start + len(ACTIVE_REPLACEMENT_WINDOW)]),
                         ACTIVE_REPLACEMENT_WINDOW)
        targets = re.findall(r"^diff --git a/(\S+) b/(\S+)$", self.patch, re.MULTILINE)
        self.assertEqual(targets, [("dlls/mfmediaengine/main.c", "dlls/mfmediaengine/main.c")])

    def test_patch14_preserves_project_authorship_and_wine_license_boundary(self) -> None:
        self.assertIn("From: RTSP-on-GE design <rtsp-on-ge@example.invalid>", self.patch)
        notice = NOTICE.read_text(encoding="utf-8")
        self.assertRegex(notice, r"Patch\s+14 is a project-authored change")
        self.assertIn("Wine LGPL-2.1-or-later licensing boundary", notice)

    def test_patch14_detaches_exact_refcounted_fields(self) -> None:
        for statement in (
            "engine->presentation.source = NULL;",
            "engine->presentation.pd = NULL;",
            "engine->presentation.frame_sink = NULL;",
        ):
            self.assertEqual(self.added.count(statement), 1)
        self.assertNotIn("memset(&engine->presentation", self.added)
        self.assertNotIn("engine->presentation.start_position =", self.added)
        self.assertNotIn("engine->presentation.start_position.vt =", self.added)

    def test_pending_variant_ownership_is_explicit(self) -> None:
        self.assertIn("always VT_EMPTY or VT_I8", self.added)
        self.assertIn("media_engine_start_playback() consumes it", self.added)


class Patch15ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if CONSOLIDATED_PRESENTATION:
            raise unittest.SkipTest("consolidated component layout uses ConsolidatedContractTests")
        cls.patch = PATCH15.read_text(encoding="utf-8")
        cls.added = added_lines(cls.patch)

    def test_patch15_changes_only_media_session(self) -> None:
        targets = re.findall(r"^diff --git a/(\S+) b/(\S+)$", self.patch, re.MULTILINE)
        self.assertEqual(targets, [("dlls/mf/session.c", "dlls/mf/session.c")])

    def test_patch15_routes_only_an_already_stopped_presentation(self) -> None:
        self.assertIn("sources_stopped = session_is_source_nodes_state", self.added)
        self.assertIn("if (sources_stopped)", self.added)
        self.assertIn("session->state = SESSION_STATE_STOPPED;", self.added)
        self.assertIn("session->clock_started = FALSE;", self.added)
        self.assertIn("else if (!keep_position)", self.added)

    def test_patch15_does_not_directly_stop_clock_or_touch_mediaengine(self) -> None:
        if SPLIT_PATCH_PRESENTATION:
            self.assertNotIn("IMFPresentationClock_Stop", self.added)
        else:
            self.assertEqual(self.added.count("IMFPresentationClock_Stop"), 1)
        self.assertNotIn("mfmediaengine", self.added)
        self.assertNotIn("session_set_source_object_state", self.patch)


class Patch16ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if CONSOLIDATED_PRESENTATION:
            raise unittest.SkipTest("consolidated component layout uses ConsolidatedContractTests")
        cls.patch = PATCH16.read_text(encoding="utf-8")
        cls.added = added_lines(cls.patch)

    def test_patch16_precedes_patch17_and_changes_only_media_session(self) -> None:
        entries = [line for line in SERIES.read_text(encoding="utf-8").splitlines()
                   if line and not line.startswith("#")]
        start = entries.index(PATCH14_NAME)
        self.assertEqual(tuple(entries[start:start + len(ACTIVE_REPLACEMENT_WINDOW)]),
                         ACTIVE_REPLACEMENT_WINDOW)
        targets = re.findall(r"^diff --git a/(\S+) b/(\S+)$", self.patch, re.MULTILINE)
        self.assertEqual(targets, [("dlls/mf/session.c", "dlls/mf/session.c")])

    def test_patch16_checks_and_stops_the_physical_clock(self) -> None:
        self.assertIn("IMFPresentationClock_GetState", self.added)
        self.assertIn("MFCLOCK_STATE_INVALID", self.added)
        self.assertIn("MFCLOCK_STATE_STOPPED", self.added)
        self.assertEqual(self.added.count("IMFPresentationClock_Stop"), 1)
        self.assertIn("session_command_complete_with_event", self.added)
        self.assertIn("IMFMediaSink_SetPresentationClock(sink->sink, NULL)", self.added)
        self.assertIn("TOPO_NODE_EXPECT_INITIAL_CLOCK_STOP", self.added)
        self.assertIn("event_type == MEStreamSinkStopped", self.added)
        self.assertIn("event_type == MEStreamSinkStarted", self.added)

    def test_patch16_does_not_change_transport_or_sink_implementations(self) -> None:
        self.assertNotIn("mfmediaengine", self.patch)
        self.assertNotIn("winedmo", self.patch)
        self.assertNotIn("dlls/mf/sar.c", self.patch)
        self.assertNotIn("video_frame_sink.c", self.patch)


class ConsolidatedContractTests(unittest.TestCase):
    """The same lifetime/clock policy, independent of historical patch names."""

    @classmethod
    def setUpClass(cls) -> None:
        if not CONSOLIDATED_PRESENTATION:
            raise unittest.SkipTest("historical layout retains its original Patch14/15/16 checks")
        cls.engine = PATCH14.read_text(encoding="utf-8")
        cls.session = PATCH15.read_text(encoding="utf-8")

    def test_component_scope_and_authorship_provenance(self) -> None:
        for text, target in ((self.engine, "dlls/mfmediaengine/main.c"),
                             (self.session, "dlls/mf/session.c")):
            self.assertEqual(re.findall(r"^diff --git a/(\S+) b/(\S+)$", text, re.M), [(target, target)])
        original = "ge-proton11-6/0014-mfmediaengine-preserve-pending-start-position.patch"
        self.assertIn(original, self.engine)
        self.assertIn("From: RTSP-on-GE design <rtsp-on-ge@example.invalid>",
                      (SERIES.parent / original).read_text())
        self.assertIn("0015-mf-order-immediate-replacement-start.patch", self.session)
        self.assertIn("Wine LGPL-2.1-or-later licensing boundary", NOTICE.read_text())

    def test_clear_preserves_pending_value_and_detaches_before_shutdown(self) -> None:
        postimage = "\n".join(line[1:] for line in self.engine.splitlines()
                              if line[:1] in (" ", "+") and not line.startswith("+++"))
        clear = re.search(r"static void media_engine_clear_presentation\([^{}]*\)\n\{.*?^}",
                          postimage, re.M | re.S)
        self.assertIsNotNone(clear, "complete replacement clear body missing from component")
        body = clear.group()
        for statement in ("engine->presentation.source = NULL;", "engine->presentation.pd = NULL;",
                          "engine->presentation.frame_sink = NULL;"):
            self.assertEqual(body.count(statement), 1)
            self.assertLess(body.index(statement), body.index("LeaveCriticalSection(&engine->cs)"))
        self.assertNotIn("memset(&engine->presentation", body)
        self.assertNotRegex(body, r"engine->presentation\.start_position[^;]*=")
        self.assertIn("always VT_EMPTY or VT_I8", postimage)
        self.assertIn("media_engine_start_playback() consumes it", body)

    def test_replacement_clock_and_one_shot_sink_stop_contract(self) -> None:
        added = added_lines(self.session)
        for statement in ("sources_stopped = session_is_source_nodes_state", "if (sources_stopped)",
                          "session->state = SESSION_STATE_STOPPED;", "session->clock_started = FALSE;",
                          "else if (!keep_position)", "IMFPresentationClock_GetState", "MFCLOCK_STATE_INVALID",
                          "MFCLOCK_STATE_STOPPED", "session_command_complete_with_event",
                          "IMFMediaSink_SetPresentationClock(sink->sink, NULL)",
                          "TOPO_NODE_EXPECT_INITIAL_CLOCK_STOP", "event_type == MEStreamSinkStopped",
                          "event_type == MEStreamSinkStarted"):
            self.assertIn(statement, added)
        # The component also includes the independent first-start clock repair;
        # count the replacement-specific guarded Stop, not every clock operation.
        self.assertEqual(added.count("FAILED(hr = IMFPresentationClock_Stop(session->clock))"), 1)

    def test_consolidated_contract_rejects_ownership_and_clock_mutations(self) -> None:
        for attribute, old, new, verify in (
                ("engine", "engine->presentation.source = NULL;", "/* source not detached */",
                 self.test_clear_preserves_pending_value_and_detaches_before_shutdown),
                ("engine", "engine->presentation.pd = NULL;", "/* descriptor not detached */",
                 self.test_clear_preserves_pending_value_and_detaches_before_shutdown),
                ("session", "TOPO_NODE_EXPECT_INITIAL_CLOCK_STOP", "TOPO_NODE_STOP_FILTER_REMOVED",
                 self.test_replacement_clock_and_one_shot_sink_stop_contract),
                ("session", "FAILED(hr = IMFPresentationClock_Stop(session->clock))", "FALSE",
                 self.test_replacement_clock_and_one_shot_sink_stop_contract)):
            original = getattr(self, attribute)
            self.assertIn(old, original)
            try:
                setattr(self, attribute, original.replace(old, new))
                with self.subTest(mutation=old), self.assertRaises(AssertionError):
                    verify()
            finally:
                setattr(self, attribute, original)


class PatchSelectionTests(unittest.TestCase):
    """Exercise selection only; synthetic series never create patch/source files."""

    def setUp(self) -> None:
        self.addCleanup(configure_patch_contract, SERIES)

    def configure(self, entries: tuple[str, ...]) -> None:
        with patch.object(Path, "read_text", return_value="\n".join(entries) + "\n"):
            configure_patch_contract(SERIES)

    def test_unique_combined_basename_selects_candidate_directory(self) -> None:
        candidate = "candidate-copy/0015-mf-order-immediate-replacement-start.patch"
        window = ("ge-proton11-6/0014-mfmediaengine-preserve-pending-start-position.patch",
                  candidate, "ge-proton11-6-a320/0017-winedmo-propagate-terminal-network-read-errors.patch")
        self.configure(window)
        self.assertEqual(COMBINED_PATCH15_NAME, candidate)
        self.assertEqual(PATCH15, SERIES.parent / candidate)
        self.assertEqual(PATCH16, PATCH15)
        self.assertEqual(ACTIVE_REPLACEMENT_WINDOW, window)
        self.assertFalse(SPLIT_PATCH_PRESENTATION)

    def test_consolidated_components_select_and_reject_missing_duplicate_or_mixed(self) -> None:
        good = (CONSOLIDATED_SESSION, "unrelated.patch", CONSOLIDATED_ENGINE)
        self.configure(good)
        self.assertTrue(CONSOLIDATED_PRESENTATION)
        self.assertEqual((PATCH14, PATCH15, PATCH16),
                         (SERIES.parent / CONSOLIDATED_ENGINE, SERIES.parent / CONSOLIDATED_SESSION,
                          SERIES.parent / CONSOLIDATED_SESSION))
        for bad in ((CONSOLIDATED_ENGINE,), good + (CONSOLIDATED_ENGINE,),
                    (CONSOLIDATED_ENGINE, CONSOLIDATED_SESSION),
                    good + ("experimental/0015-mf-order-immediate-replacement-start.patch",)):
            with self.subTest(entries=bad), self.assertRaises(SystemExit):
                self.configure(bad)

    def test_consolidated_p21_selects_without_mixing_p20(self) -> None:
        session = "ge-proton11-9-se2-p21/0006-mf-retain-session-lifecycle-and-demand-accounting.patch"
        engine = "ge-proton11-9-se2-p21/0008-mfmediaengine-retain-control-intent-and-buffering-events.patch"
        self.configure((session, engine))
        self.assertEqual((PATCH15, PATCH14), (SERIES.parent / session, SERIES.parent / engine))
        old_session = session.replace("-p21/", "-p20/")
        with self.assertRaises(SystemExit):
            self.configure((old_session, session, engine))

    def test_historical_combined_and_split_layouts_remain_selectable(self) -> None:
        for prefix in ("experimental", "ge-proton11-6"):
            window = (prefix + "/0014-mfmediaengine-preserve-pending-start-position.patch",
                      prefix + "/0015-mf-order-immediate-replacement-start.patch",
                      prefix + "/0017-winedmo-propagate-terminal-network-read-errors.patch")
            self.configure(window)
            self.assertEqual(ACTIVE_REPLACEMENT_WINDOW, window)
            self.assertFalse(SPLIT_PATCH_PRESENTATION)
        window = ("experimental/0014-mfmediaengine-preserve-pending-start-position.patch",
                  SPLIT_PATCH15_NAME, SPLIT_PATCH16_NAME,
                  "experimental/0017-winedmo-propagate-terminal-network-read-errors.patch")
        self.configure(window)
        self.assertEqual(ACTIVE_REPLACEMENT_WINDOW, window)
        self.assertTrue(SPLIT_PATCH_PRESENTATION)

    def test_duplicate_combined_basename_rejected_across_directories(self) -> None:
        candidate = "candidate-copy/0015-mf-order-immediate-replacement-start.patch"
        window = ("ge-proton11-6/0014-mfmediaengine-preserve-pending-start-position.patch",
                  candidate, "ge-proton11-6-a320/0017-winedmo-propagate-terminal-network-read-errors.patch")
        for duplicate in (candidate, "ge-proton11-6/0015-mf-order-immediate-replacement-start.patch",
                          "another-copy/0015-mf-order-immediate-replacement-start.patch"):
            with self.subTest(duplicate=duplicate), self.assertRaisesRegex(SystemExit, "duplicate combined-0015"):
                self.configure(window + (duplicate,))

    def test_missing_reordered_or_nonadjacent_window_rejected(self) -> None:
        first = "ge-proton11-6/0014-mfmediaengine-preserve-pending-start-position.patch"
        middle = "candidate-copy/0015-mf-order-immediate-replacement-start.patch"
        last = "ge-proton11-6-a320/0017-winedmo-propagate-terminal-network-read-errors.patch"
        for entries in ((first, last), (first, last, middle), (middle, first, last),
                        (first, middle, "unrelated.patch", last), (first, middle, last, first)):
            with self.subTest(entries=entries), self.assertRaises(SystemExit):
                self.configure(entries)

    def test_split_and_candidate_combined_layout_cannot_mix(self) -> None:
        first = "experimental/0014-mfmediaengine-preserve-pending-start-position.patch"
        middle = "candidate-copy/0015-mf-order-immediate-replacement-start.patch"
        last = "experimental/0017-winedmo-propagate-terminal-network-read-errors.patch"
        for entries in ((first, SPLIT_PATCH15_NAME, SPLIT_PATCH16_NAME, last, middle),
                        (first, middle, last, SPLIT_PATCH15_NAME),
                        (first, middle, last, SPLIT_PATCH16_NAME)):
            with self.subTest(entries=entries), self.assertRaises(SystemExit):
                self.configure(entries)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--series", type=Path, default=SERIES)
    args, unittest_args = parser.parse_known_args()
    configure_patch_contract(args.series)
    unittest.main(argv=[sys.argv[0], *unittest_args], verbosity=2)
