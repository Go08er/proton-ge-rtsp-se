# Progressive HTTP VOD Alpha tests

## Control calls and explicit damaged-source recovery (SE2-P4 investigation)

The same probe/runner has two additional, mutually exclusive modes:

- `--case hls --control-stress`: 160 volume/mute/time operation groups on an
  MTA worker while the main thread transfers software frames. Each group
  must finish within one second, with clock/frame progress before and after.
  The parent timeout also bounds a native call which never returns. This
  uses static synthetic HLS and null audio, not a world's callbacks, rolling
  live HLS, endpoint reconfiguration or VR/DXGI. P3 passes; it is a negative
  reproduction attempt, not a vetted fix test.
- `--case file --filter-recovery-seek`: use the exact single-bad-NAL fixture
  described in `../media-edge-cases/README.md`. Require an observed DECODE
  error or ENDED, then call SetCurrentTime(8) and Play on the same source.
  P2 resumes; P3 fails to advance despite S_OK API returns. The observation
  counter is reset for recovery, not the actual MediaEngine error state.
  No automatic retry or SetSource hides the distinction. P4 intentionally
  retains this limitation; this case is not a passing P4 qualification gate.

Use the existing explicit `--tool`, `--probe`, `--fixtures`, `--output`,
`--runtime-lib`, `--pulseaudio` and fresh synthetic `--app-id` arguments.
Containment and the 75-second child/110-second outer deadlines remain.
The original `--filter-error` test still verifies defined error followed by
explicit clean-source reopen. It answers a different question.

## Focused MediaEngine HLS seek regression (A3.23)

`hls_clock_probe.c` consumes frames through `OnVideoStreamTick` and
`TransferVideoFrame` into a software bitmap. `run_hls_clock.py` supplies a
private null-audio server, loopback HTTP and fresh synthetic prefix. It
requires advancing clock and distinct-PTS frame transfers after initial
playback, forward seek to 25 seconds, and backward seek to 8 seconds.
It does not measure audible audio, A/V sync, DXGI or headset behavior.

The exact same continuous synthetic content as MP4 passes on A3.22-R2;
HLS (ordinary or web-like segment names) freezes after one target frame.
See [the A3.23 qualification record](../../docs/GE_PROTON11_6_A323_SEEK_EVALUATION.md)
for frozen inputs, commands, prior failures and candidate results. Do not
substitute this for the older SourceReader decode probe: they exercise
different parts of the MF pipeline.

To generate equivalent **new** synthetic inputs in an empty directory:

```sh
ffmpeg -hide_banner -loglevel error -nostdin \
  -f lavfi -i testsrc2=size=160x90:rate=30 \
  -f lavfi -i sine=frequency=440:sample_rate=48000 -t 40 \
  -c:v libx264 -threads 2 -preset ultrafast -g 60 -bf 2 -pix_fmt yuv420p \
  -c:a aac -b:a 64k -movflags +faststart fixture.mp4
ffmpeg -hide_banner -loglevel error -nostdin -i fixture.mp4 \
  -c copy -hls_time 2 -hls_list_size 0 -hls_playlist_type vod \
  -hls_segment_filename seg%03d.ts playlist.m3u8
```

Recheck both prior-failing HLS and prior-passing MP4 whenever the probe or
fixtures change. Regeneration is not assumed byte-identical across FFmpeg
versions. All logs remain local; the runner refuses AppID 438100.

For finite codec checks, `--case file --media-file fixture.mp4`,
`fixture.mkv`, or `fixture.webm` serves that file with its matching MIME type;
no HLS playlist is required. Keep the same 40-second, 160×90 synthetic A/V
content and the unchanged probe: initial playback, forward seek to 25 seconds,
and backward seek to 8 seconds must all advance with transferred frames.
Compare the identical encoded fixture on the prior and candidate tools.
Container support in the runner is not evidence that a codec works in Wine.

### SE2-P1 co-test seek replay (investigative, not a vetted HEVC reproducer)

The same small probe now accepts `--seek-stress` through the runner with
`--case file`. It consumes frames during 18 seconds of additional normal
playback, then replays three waves of ten fractional seek targets and delays
from the sanitized 2026-09-12 HEVC source log. Requests use the game fixture's
extensionless `/media` route, MIME type and 4 MiB/s pacing. The existing
clock/frame recovery oracle must pass after each wave. Existing byte/time
budgets, synthetic-AppID restrictions and containment remain in place.

Compile only the Windows test executable (not Proton), using the project's
Nix shell:

```sh
x86_64-w64-mingw32-gcc -Wall -Wextra -Werror -municode \
  tests/progressive-http-vod/hls_clock_probe.c -o /tmp/rtsp-seek-probe.exe \
  -lole32 -loleaut32 -lmfplat -lmf -lmfuuid -luuid -lwindowscodecs
```

Use explicit existing tool/fixture/runtime paths and a fresh result path and
synthetic AppID, as in `docs/SE2_P1_BUILD_20260912.md`, adding `--seek-stress`.
The no-flag initial/forward/backward test is unchanged. Never use the game
AppID or run the probe directly outside its contained runner.

`--seek-scrub` uses the same stress sequence with Pause, a 50-ms frame-consuming
interval, position change, another 50 ms, and Play for each request. It tests
another caller state; it is not asserted to be AVPro's exact call sequence.
It also passed on unchanged SE2-P1. The same byte/time budgets apply.

Four headless HEVC variants passed on unchanged SE2-P1, including the final
warm-up/paced replay: the game failure is **not yet reproduced** by this mode.
The updated probe still detects the established R2 HLS seek freeze, while
its R2 MP4 control passes. This checks the original recovery oracle, not
the new mode's sensitivity to the HEVC issue. The replay does not model
AVPro's exact caller state, DXGI, physical audio or VR load. See the
[investigation record](../../docs/SE2_P1_SEEK_INVESTIGATION_20260912.md).

## Existing source and policy checks

This directory tests experimental direct-HTTP Alpha patch 5 without contacting
the network or touching Steam.

Prepare the active eight-patch series, or apply patch 5 and then patch 6 after
the four-patch A2 source in a disposable Wine tree, then run:

```sh
python3 tests/progressive-http-vod/audit.py --wine-tree /path/to/patched/wine
python3 tests/progressive-http-vod/test_model.py
```

The audit checks routing order, the plain-HTTP/`AVERROR_INVALIDDATA`-only
fallback signal, scheme-specific progressive/HLS protocol allowlists, explicit
root TLS verification, range-derived seekability, and deadline coverage for
direct open, read, seek, and close. The model protects the behavioral decision
table, including verified HTTP-to-HTTPS upgrades, rejected HTTPS-to-HTTP
downgrades, terminal TLS/protocol errors, and the companion FFmpeg TLS-default
dependency for HLS children. It also requires `crypto` only in the HLS lists so
AES-128 segments remain usable without exposing that wrapper to generic media,
and models the separate requirement that the GE build actually enable the
protocol. These tests do not prove real certificate
validation, redirect/range handling, startup latency, cancellation, or VRChat
synchronization; those remain runtime gates.

The current model also covers patch 6's deliberate-cancellation recovery:
positive partial packets are rejected before bitstream filtering, only exact
`AVERROR_EXIT`/EOF state may be cleared before a following progressive-HTTP
Range seek, and HLS/RTSP routing is not given that custom-AVIO repair. A failed
seek after queue flush is terminal for that media source: it leaves the
transition epoch unreadable, stops the demux producer, emits one MF error, and
performs no post-failure read retries. This prevents a failed Range seek from
becoming a one-millisecond retry loop.

## Actual-binary HTTP identity comparison (A3.21)

`run_http_user_agent.py` executes a small public-MF source-open probe in the
selected built tool. Unlike the source/model audits above, this reaches Wine
and FFmpeg's actual HTTP implementation. It tests a synthetic server policy,
not the real service's unknown policy or decoded playback. An unrestricted
MP4 is the working control; identity-gated MP4, redirect and HLS opens should
fail on A3.20 and pass on A3.21. An always-denied source must still fail.

Inside the project's Nix shell, prepare synthetic inputs and the small probe
(these commands do not build Proton):

```sh
mkdir -p work/http-identity-inputs
x86_64-w64-mingw32-gcc -Wall -Wextra -Werror -municode \
  -o work/http-identity-inputs/http_open_probe.exe \
  tests/progressive-http-vod/http_open_probe.c \
  -lole32 -lmfplat -lmf -lmfuuid -luuid
ffmpeg -nostdin -n -v error -i tests/media/generated/synthetic-av.mkv \
  -c copy -movflags +faststart work/http-identity-inputs/fixture.mp4
ffmpeg -nostdin -n -v error -i tests/media/generated/synthetic-av.mkv \
  -c copy -f mpegts work/http-identity-inputs/segment.ts
python3 tests/progressive-http-vod/run_http_user_agent.py \
  --tool /path/to/complete/extracted/tool \
  --probe work/http-identity-inputs/http_open_probe.exe \
  --fixtures work/http-identity-inputs \
  --runtime-lib /nix/store/11ilpafpxyv798cwx7xfm537l94h1fa5-libvdpau-1.5/lib \
  --output work/http-identity-new-run --app-id 999324 --expect candidate-pass
```

The runtime-lib path is the locally verified libvdpau store output: FFmpeg
links it even for this headless probe, but this host's `steam-run` FHS omits
it. If absent on another host, supply its equivalent existing libvdpau store
directory. Do not interpret a loader failure with zero HTTP requests as a
reproduced media failure. Bubblewrap and `steam-run` must be available.

For the prior tool use `--expect old-failure`, another fresh output directory,
and a different synthetic AppID. Output directories may not exist already.
The runner uses private network/PID/mount namespaces, a fresh prefix,
`WINEDEBUG=-all`, no host graphics/audio, and at most 64 served requests,
a 16 MiB response-body budget, and a 150-second
outer deadline. Its only server is loopback. Result JSON records synthetic
paths, numeric outcomes, and classified identities, not arbitrary headers.
No Steam operation or AppID 438100 prefix is involved.

The separate six source checks are:

```sh
python3 tests/progressive-http-vod/test_http_user_agent.py \
  --wine-tree worktrees/ge-proton11-6-a321-build1-rtsp/wine
```

Their pass is not a substitute for the actual-binary comparison. HTTPS
certificate validation and live-world playback are separate gates.

### A3.22: service-style HLS segment names

The same runner's `--segment-probe` selects the prior-failing HLS case:
synthetic TS bytes under web-like segment suffixes, with normal-named media,
HTML, local-file and image controls. Use `--expect old-failure` for A3.21;
`passed: true` then means the expected failure was reproduced. After building
A3.22, use its actual tool with `--expect candidate-pass`, a fresh output
directory and synthetic AppID. The flags `--content-probe`, `--segment-probe`
and `--hls-format-probe` select separate concrete cases, not remote inputs.

`--native-hls-mode picky|relaxed|fenced` isolates options in the selected
tool's FFmpeg 62 library and is **not** a Wine candidate pass. The optional
`--hls-format-probe` additionally requires `fragmented.mp4` and `packed.aac`
in the fixture directory. The four new source contracts are reached by the
existing Wine auditor when the A3.22 series is selected:

```sh
python3 tests/progressive-http-vod/test_hls_segment_policy.py \
  --wine-tree worktrees/ge-proton11-6-a322-rtsp/wine
```

Exact tested inputs, outcomes and commands are in
[`GE_PROTON11_6_A322_CANDIDATE.md`](../../docs/GE_PROTON11_6_A322_CANDIDATE.md).

For a stronger headless check, compile `http_decode_probe.c` with the same
command as the open probe, adding `-lmfreadwrite`, and pass that executable
with `--segment-probe --decode-probe`. Use the H.264/AAC synthetic inputs,
not audio-only fixtures. The oracle additionally requires decoded PCM audio
and NV12 video buffers spanning at least two seconds on every expected-good
source. The normal-name control must decode on the prior tool before treating
its web-name rejection as a regression reproduction. No display, audio device,
render clock, account, or remote service is involved; this is not an A/V sync
or in-game playback claim. Existing request/byte/time limits remain in force.

`--seek-probe` additionally flushes pending reads, seeks finite HLS to four
seconds and requires decoded A/V progress through six seconds. It does not
apply that absolute-timestamp oracle to MP4, whose SourceReader output can
be rebased after seeking. `--live-hls-probe` instead removes ENDLIST for a
static live-window startup control; it cannot be combined with `--seek-probe`
and is not a moving-window continuity test.

`--balanced-reads` selects the stream with less delivered timestamp progress
instead of using unpaced `ANY_STREAM` arrival order. It retains the same
512-read cap; audio arriving earlier must not be mistaken for a guaranteed
even split of that budget. The R2 validation record retains the unpaced seek
budget exhaustion separately. Qualify the balanced mode using the old
offset-failing input and old zero-origin passing control before trusting its
candidate result. This cadence is not claimed to reproduce AVPro exactly.

The offset-origin TS fixture fails initial decoding on both A3.21 and A3.22
R1, while timestamp-zero controls decode on both. This is the prior-failing
runtime regression for R2's HLS origin mapping. See
[the R2 validation record](../../docs/GE_PROTON11_6_A322_R2_VALIDATION.md)
for controls, build identities, retained unsuccessful probe revisions and
actual candidate results. `test_hls_timeline.py --wine-tree DIR` checks the
source contracts only; it does not replace the decoded-sample regression.
# Focused frame-consuming follow-ups (2026-09-13)

The existing `hls_clock_probe.c` / `run_hls_clock.py` now also support:

- `--seek-scrub`: the recorded fractional seek cadence with Pause/position/Play,
  frame consumption between calls, and four measured recovery phases. This
  passes on P1 and is **not** a vetted reproducer of the live HEVC defect.
- `--filter-error`: the exact synthetic corrupt-NAL fixture from
  `tests/media-edge-cases/make_bad_nal.py`. Require normal initial playback,
  one DECODE/MF_E_INVALID_STREAM_DATA error rather than ENDED, then advancing
  frames/clock after manual clean-source reopen. P1 fails with false ENDED.
- `--case rtsp --mediamtx PATH --ffmpeg PATH`: real-time TCP publication of
  the hash-locked synthetic H.264/AAC fixture, initial and sustained software
  frame/clock progress, then live SetSource replacement. No live seeking.
  Both processes run inside the existing private namespace, never against
  a host service. Publication is capped at 90 seconds (~4.3 MiB of this fixed
  payload), the overall case at 110 seconds; no other listener is enabled.
  This passes on P1 and is a happy-path regression control, not a defect oracle.

All modes retain fresh synthetic AppIDs (438100 refused), private null audio,
software bitmap transfer, local bounded evidence and parent-enforced teardown.
RTSP does not traverse the HTTP server, so `served_bytes=0` in that case is
an **HTTP-only** counter, not an assertion that no RTSP bytes arrived.
These checks do not qualify physical audio, A/V synchronization, DXGI, VRChat
or headset/load behavior. Build the small Windows probe with the existing
instructions below; this is separable from a Proton build.
