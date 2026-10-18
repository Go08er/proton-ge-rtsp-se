# Bounded RTSP drain diagnostics

Patch 0019 adds the normally inactive `rtspdrain` Wine debug channel at the
WineDMO compressed-packet boundary and the streaming audio renderer (SAR).
It is a diagnostic, not a timeout, reconnect, backoff, or queue-policy
change.

## Cooperative log monitor

`live_watch.py` preserves local raw log generations while printing short
numeric summaries. Keep the approved launch flags unchanged. Add the current
VRChat application log to a co-test invocation with:

```sh
python3 tests/rtsp-drain-diagnostics/live_watch.py \
  --proton-log "$HOME/Downloads/rtsp-se2-p3-logs/steam-438100.log" \
  --vrchat-log /absolute/path/to/current/output_log_TIMESTAMP.txt \
  --capture-dir /absolute/path/to/new-private-session/capture
```

Use the **actual current filename**, not the placeholder above. VRChat creates
a differently named application log on each launch; this option follows the
one specified file, not a directory. The co-test coordinator should select
the current file after launch and use a new capture directory for each session.
The existing `--mediamtx-log` and `--publisher-log` options remain available
when local fixture servers are used. No server log means no server evidence,
not a failed remote stream. This reader never writes into game compatdata.

The application log adds fixed `APP UDON_HALTED` and `APP VM_BUDGET` notices.
Existing Proton warnings add numeric `LOCK WAIT` and `HLS EXPIRED` notices;
no extra Wine channels are required. Each such incident stays visible, even
after earlier incidents. Neither an Udon halt nor a lock wait identifies the
responsible player/native component by itself, and an expired HLS segment is
not automatically a playback failure. `wall=` is the application log's local
wall time; `wine=` is Wine's timestamp. Do not subtract or merge these clocks
without an independently established mapping.

Routine warning counts print at 1, 2, 3 and powers of ten, with exact totals
at stop; raw warnings remain in the preserved file. This reduces display
chatter, **not** Wine logging overhead or raw-log size. Source counters apply
only to RTSP schemes, not all HTTP/HLS playback; absence of a `Bnn` record is
not proof that no backend exists. SAR correlation remains approximate.

No-game checks (including live piped output and private capture preservation):

```sh
python3 -m unittest discover -s tests/rtsp-drain-diagnostics -p 'test_*.py'
python3 tests/rtsp-drain-diagnostics/test_live_watch.py --demo
```

## Source diagnostic scope

The channel records only fixed labels and numeric aggregate state:

- process-local source and stream identifiers;
- per-stream queue high-water marks and sample request/dequeue/delivery counts;
- aggregate normal and emergency backpressure reasons;
- completed compressed-packet counts and bytes; and
- slow/terminal WineDMO read duration and numeric status.

For SAR, one terminal numeric summary records:

- presentation-clock start calls and successful returns;
- actual `IAudioClient_Start()` calls and successes;
- all `ProcessSample()` calls and the subset received before the first
  `OnClockStart()` call;
- render-callback count; and
- final, peak, and client-capacity frame counts, sample rate and frame size,
  final clock state, and whether an audio-client start remains pending.

The call and success fields are separate because SAR currently sets its
logical clock state to running even when `IAudioClient_Start()` fails.
`preclock_samples` means samples ordered before the first `OnClockStart()`
under SAR's existing critical section; it does not lump later pause or stop
states into that count.

Direct RTSP is an FFmpeg `AVFMT_NOFILE` demuxer. Its socket and transport-byte
counter are private to libavformat, so the Wine-only diagnostic deliberately
omits a transport-byte field. `packet_bytes_completed` must not be interpreted
as raw socket progress.

The diagnostic instruments at most the first 64 RTSP sources in a process.
Each instrumented source gets 16 live records, one reserved terminal-read
record, one unconditional source summary, and at most eight unconditional
stream summaries. The first 64 SAR objects each get exactly one guarded
summary on normal shutdown or final release. The hard process bound is
therefore 1,664 WineDMO records plus 64 SAR records: 1,728 `rtspdrain`
records. An early source cannot consume a later source's allowance, and a
late successful source or SAR object retains its own summary. Once a source
spends its live allowance, it takes a fast exhausted path instead of
repeatedly incrementing and rolling back a process-global counter.

SAR does not receive the WineDMO source identity. Correlate `sar_id` and
`source_id` only by process-local creation order and by the Wine timestamp;
the SAR summary's `lifetime_ms` permits its creation time to be reconstructed
from the terminal record. This is a temporal association, not an asserted
one-to-one mapping. Threading a media identifier through Media Session would
be a larger and behavior-adjacent diagnostic change.

In the A3.14 session, a diagnostic line was at most 324 bytes. At that observed
line size the 1,728-record hard bound is about 547 KiB. A SAR summary is also
a fixed-label numeric record; allowing 400 bytes per SAR line adds at most
25 KiB to the earlier WineDMO estimate. Eleven two-stream sources plus eleven
SAR objects would produce at most 220 records, about 67 KiB at the observed
line size, but the source/SAR count is not assumed to be one-to-one. These
are byte estimates; the exact invariant is the line count. Wine's separate
warning and error channels are not byte bounded. Normal runs do no timing,
counter, or log work unless the dedicated channel is selected.

Run the source and patch contracts with:

```sh
python3 tests/rtsp-drain-diagnostics/audit.py \
  --wine-tree <prepared-wine-tree>
python3 -m unittest -v \
  tests/rtsp-drain-diagnostics/test_model.py \
  tests/rtsp-drain-diagnostics/test_patch_contract.py
```

The contained runtime smoke is the existing loopback RTSP high-rate case with:

```sh
WINEDEBUG=-all,+timestamp,+pid,+tid,+rtspdrain,warn+dmo,err+dmo,warn+mfplat,err+mfplat
```

The `warn`/`err` classes restore the narrow failure records that the A3.14
line accidentally omitted. Disabling `trace+dmo`, `trace+mfplat`, and
`trace+process` does not guarantee low volume: the P3 session contained over
348,000 buffer-interface warnings. These classes have no mathematical byte
cap; retain the Proton log locally and watch its size. The monitor's display
collapse does not reduce those raw writes or their runtime overhead.
The smoke checks that the bounded source/stream and SAR summaries appear and
contain no fixture URL. A failing source with preclock samples and zero
clock-start calls identifies a clock callback which never arrived. A
successful audio-client start followed by stopped demand identifies a later
stage. It does not claim to reproduce AVPro frame consumption or the in-game
stall.
