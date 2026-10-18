# Master patch index

Start here to understand what the project changes. Each named patch below
links directly to its explanation and code diff. The plain `series` files
are machine-readable application lists, not the browsing interface.

This index tracks the **SE2 set on GE-Proton11-9**: 17 Wine patches, four
FFmpeg security patches, one GE build patch and six FFmpeg build/companion
modules. Its exact inputs are the
[release pin](../config/ge-proton11-9-se2.env) and
[Wine application list](series-ge-proton11-9-se2). For qualification and
known limits, see the [release notes](../RELEASE.md); the descriptions below
explain intent, not a guarantee that every scenario works.

## Choose a component

- **Wine media and VR:** the 17 individual patches below.
- **FFmpeg security and TLS:** [four patches with explanations and upstream commit links](ffmpeg-security/README.md#patch-by-patch-guide).
- **Encrypted HLS build support:** [one GE build-configuration patch](ffmpeg-build/README.md#patch-at-a-glance).
- **Other FFmpeg build and companion modules:** [six patches](#ffmpeg-build-and-companion-modules).
- **How preparation fits together:** [review and replay guide](../docs/PATCHES.md).

## Wine media and VR patches

Read these in the listed order. File numbers are stable identifiers, not
application positions: numbers have gaps. Our Wine series is inserted after
GE's `ge-video-rework` set, not applied directly to an unpatched Wine
checkout. Patches 0001-0013 re-derive the SE1 behavior as residuals against
GE-Proton11-9 (dropping what GE now does itself) and are grouped by area;
0021-0024 are new since SE1. The files live in `ge-proton11-9-se2-p24/`,
the candidate directory the hash-locked series refers to.

| Order | Patch — open explanation and diff | What it addresses |
| --- | --- | --- |
| 1 | [0001 — Bounded network and origin contract](ge-proton11-9-se2-p24/0001-winedmo-retain-bounded-network-and-origin-contract.patch) | RTSP and RTSP-over-TCP opening, cancellable network operations, HTTP/HLS source classification and the VOD timeline origin. |
| 2 | [0002 — Generation queues and adaptive buffer](ge-proton11-9-se2-p24/0002-winedmo-retain-generation-queues-and-adaptive-buffer.patch) | Asynchronous loading, source generations, sample queues, seek scheduling and the adaptive network read-ahead buffer. A multi-behavior patch, not one small fix. |
| 3 | [0003 — Decoder coordinates and parser drain](ge-proton11-9-se2-p24/0003-winedmo-retain-native-decoder-coordinates-and-parser-drain.patch) | Keeps audio and video timestamps in one coordinate system across flushes and drains a parser's tail before decoder end-of-stream. |
| 4 | [0004 — Codec admission and format validation](ge-proton11-9-se2-p24/0004-winedmo-retain-codec-admission-and-format-validation.patch) | Exposes decoders FFmpeg already provides (for example VP8, HEVC, FLAC, AC-3, MPEG audio/video, MJPEG) and bounds channel counts and formats. |
| 5 | [0005 — Reader errors, layout and origin](ge-proton11-9-se2-p24/0005-mfreadwrite-retain-reader-error-layout-and-origin-contract.patch) | SourceReader reports terminal errors, propagates output layout, preserves source timestamps and forwards reconnect events. |
| 6 | [0006 — Session lifecycle and demand](ge-proton11-9-se2-p24/0006-mf-retain-session-lifecycle-and-demand-accounting.patch) | Media Session start ordering for replacement sources, sample demand after seeks and preroll, buffering events, and the first presentation-clock offset. |
| 7 | [0007 — Audio renderer flush and markers](ge-proton11-9-se2-p24/0007-mf-retain-sar-flush-demand-and-marker-ownership.patch) | Flushes a running audio renderer correctly, re-arms audio demand afterward and initializes marker entries before use. |
| 8 | [0008 — MediaEngine control and buffering](ge-proton11-9-se2-p24/0008-mfmediaengine-retain-control-intent-and-buffering-events.patch) | Honors the latest pause/play intent, keeps the replacement source's start position, checks seekability before recovery and consumes buffering events. |
| 9 | [0009 — Render clock and frame demand](ge-proton11-9-se2-p24/0009-mfmediaengine-retain-render-clock-frame-demand.patch) | Requests video samples against the render clock and applies a 50 ms seek-preroll floor to the cached fallback path. |
| 10 | [0010 — Source origin and queued tail](ge-proton11-9-se2-p24/0010-mfsrcsnk-retain-source-origin-and-queued-tail-drain.patch) | Carries the source origin through the source/sink path and drains queued tail samples before end-of-stream. |
| 11 | [0011 — Failed async result status](ge-proton11-9-se2-p24/0011-mfplat-retain-failed-async-result-status.patch) | Preserves the status of a failed asynchronous result instead of reporting success. |
| 12 | [0012 — VR extensions on Wayland](ge-proton11-9-se2-p24/0012-winewayland-retain-vr-device-extensions.patch) | Exposes Wine's synthetic OpenVR and OpenXR device-extension requests through the Wayland driver. |
| 13 | [0013 — Held-marker test context](ge-proton11-9-se2-p24/0013-mf-tests-retain-held-marker-context.patch) | Keeps the Media Foundation test context for held markers in step with the session changes. |
| 14 | [0021 — Stop the clock after a terminal start error](ge-proton11-9-se2-p24/0021-mf-stop-clock-after-terminal-start-error.patch) | Fixes reload after a terminal error during a restarting seek: the stale running clock no longer blocks the replacement source's preroll. |
| 15 | [0022 — Deliver read-ahead data errors when reached](ge-proton11-9-se2-p24/0022-winedmo-defer-read-ahead-data-errors.patch) | A data error on a future packet is raised when playback reaches it, not seconds early; queued good samples are kept. |
| 16 | [0023 — Interrupt a stalled read on seek](ge-proton11-9-se2-p24/0023-winedmo-interrupt-stalled-read-on-seek.patch) | A seek cancels a stalled progressive HTTP read and reopens the transport with a fresh request. |
| 17 | [0024 — Adopt GE's HTTP reconnect](ge-proton11-9-se2-p24/0024-winedmo-adopt-ge-http-reconnect.patch) | Uses GE-Proton11-9's reconnect (`.mp4` and googlevideo URLs) and one 403 retry, with our first-request identity and a longer outer deadline. |

## FFmpeg build and companion modules

These change GE's FFmpeg build or source and are bound by hash in the
[pin](../config/ge-proton11-9-se2.env); they are not part of the Wine series.
Wine behavior that depends on them is noted.

| Module | What it addresses |
| --- | --- |
| [Secure RTSPS redirects](proposed/ffmpeg-keep-rtsps-redirects-secure.patch) | Rejects non-`rtsps` redirects from a TLS session and clears credentials when the authority changes. |
| [HTTP seek honors Connection: close](proposed/ffmpeg-http-seek-respect-connection-close.patch) | Reuses a seek connection only when persistence was requested. |
| [HTTP file size on a failed seek](proposed/ffmpeg-http-restore-filesize-on-failed-seek.patch) | An error response's body length no longer replaces the entity length. |
| [HLS seek before the first segment](proposed/ffmpeg-hls-allow-seeks-before-first-segment.patch) | A timestamp below the playlist start selects the first segment instead of failing. |
| [MPEG video parser](proposed/ffmpeg-enable-mpeg-video-parser.patch) | Enables the parser WineDMO already requests, fixing backward timestamps for B-frame MPEG video. |
| [AAC (ADTS) parser](proposed/ffmpeg-enable-aac-parser.patch) | New in SE2. Gives MPEG-TS/HLS audio correct per-packet durations so read-ahead is credited correctly (shorter HLS refill holds). |

The AES-128 HLS crypto-protocol build patch has its own
[guide](ffmpeg-build/README.md); SE2 uses [series-ge-proton11-9](ffmpeg-build/series-ge-proton11-9).

### Reviewing a suspected regression

Read the patch header and changed functions, then the later patches touching
the same area. For example, a seek during a stalled download involves the
generation queues (0002), the stalled-read interrupt (0023), the reconnect
policy (0024) and session demand (0006). Individual patches are not
independent toggles.

Useful evidence entry points are the [VOD control tests](../tests/vod-control/README.md),
[HTTP/HLS tests](../tests/progressive-http-vod/README.md), and
[source replacement tests](../tests/source-replacement-lifecycle/README.md).
Distinguish source/model tests from actual playback results; the
[release qualification](../RELEASE.md#qualification-and-limits) records
what was tested for the released artifact.

## Historical files and commit history

The SE2 release series references the candidate P24 patch directory.
`experimental/`, older `ge-proton*` variants, the SE2 candidate histories
(`series-*-se2-p*` and their patch directories, kept because the preparation
tests check them) and the other `series-*` lists remain for comparison;
inclusion in a directory does not mean a patch ships. The unqualified
`patches/series` is the retained A3.21 selection, not SE2's list. The separate
launcher compatibility patch under `proton/` is not part of SE2, which uses
the unchanged GE launcher. SE1's index is in the `se1` tag.

The public repository began with one source-kit import, so its initial
patches do not each have a separate GitHub commit. Their files retain their
existing explanations and attribution. This index makes them independently
browsable without fabricating development history, changing patch hashes,
or moving files referenced by immutable pins. For FFmpeg's unmodified
backports, the guide also links the actual upstream commits.

When selecting a new release, update this index's release identity, links and
application order against that release's series files. Document added,
replaced or dropped patches in the release notes; preserve prior release tags
and their inputs. An index entry describes inclusion and purpose, not runtime
qualification.
