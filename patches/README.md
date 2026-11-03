# Master patch index

Start here to understand what the project changes. Each named patch below
links directly to its explanation and code diff. The plain `series` files
are machine-readable application lists, not the browsing interface.

This index tracks the **SE3 set on GE-Proton11-11**: 34 Wine patches, four
FFmpeg security patches, one GE build patch and six FFmpeg build/companion
modules. Its exact inputs are the
[release pin](../config/ge-proton11-11-se3.env) and
[Wine application list](series-ge-proton11-11-se3). For qualification and
known limits, see the [release notes](../RELEASE.md); the descriptions below
explain intent, not a guarantee that every scenario works.

## Choose a component

- **Wine media and VR:** the 34 individual patches below.
- **FFmpeg security and TLS:** [four patches with explanations and upstream commit links](ffmpeg-security/README.md#patch-by-patch-guide).
- **Encrypted HLS build support:** [one GE build-configuration patch](ffmpeg-build/README.md#patch-at-a-glance).
- **Other FFmpeg build and companion modules:** [six patches](#ffmpeg-build-and-companion-modules).
- **How preparation fits together:** [review and replay guide](../docs/PATCHES.md).

## Wine media and VR patches

Read these in the listed order. File numbers are stable identifiers, not
application positions: numbers have gaps. Our Wine series is inserted after
GE's `ge-video-rework` set, not applied directly to an unpatched Wine
checkout. Patches 0001-0013 re-derive the SE1 behavior as residuals against
GE-Proton11 (dropping what GE now does itself) and are grouped by area;
0021-0024 date from SE2, and 0025-0042 are new in SE3 (the numbering has
gaps). The files live in `ge-proton11-11-se3-p9/`, the candidate directory the
hash-locked series refers to. The SE2 patches were carried to GE-Proton11-11:
most are unchanged, 0003 and 0021 are regenerated at new offsets and 0006 is
rebased.

| Order | Patch — open explanation and diff | What it addresses |
| --- | --- | --- |
| 1 | [0001 — Bounded network and origin contract](ge-proton11-11-se3-p9/0001-winedmo-retain-bounded-network-and-origin-contract.patch) | RTSP and RTSP-over-TCP opening, cancellable network operations, HTTP/HLS source classification and the VOD timeline origin. |
| 2 | [0002 — Generation queues and adaptive buffer](ge-proton11-11-se3-p9/0002-winedmo-retain-generation-queues-and-adaptive-buffer.patch) | Asynchronous loading, source generations, sample queues, seek scheduling and the adaptive network read-ahead buffer. A multi-behavior patch, not one small fix. |
| 3 | [0003 — Decoder coordinates and parser drain](ge-proton11-11-se3-p9/0003-winedmo-retain-native-decoder-coordinates-and-parser-drain.patch) | Keeps audio and video timestamps in one coordinate system across flushes and drains a parser's tail before decoder end-of-stream. |
| 4 | [0004 — Codec admission and format validation](ge-proton11-11-se3-p9/0004-winedmo-retain-codec-admission-and-format-validation.patch) | Exposes decoders FFmpeg already provides (for example VP8, HEVC, FLAC, AC-3, MPEG audio/video, MJPEG) and bounds channel counts and formats. |
| 5 | [0005 — Reader errors, layout and origin](ge-proton11-11-se3-p9/0005-mfreadwrite-retain-reader-error-layout-and-origin-contract.patch) | SourceReader reports terminal errors, propagates output layout, preserves source timestamps and forwards reconnect events. |
| 6 | [0006 — Session lifecycle and demand](ge-proton11-11-se3-p9/0006-mf-retain-session-lifecycle-and-demand-accounting.patch) | Media Session start ordering for replacement sources, sample demand after seeks and preroll, buffering events, and the first presentation-clock offset. |
| 7 | [0007 — Audio renderer flush and markers](ge-proton11-11-se3-p9/0007-mf-retain-sar-flush-demand-and-marker-ownership.patch) | Flushes a running audio renderer correctly, re-arms audio demand afterward and initializes marker entries before use. |
| 8 | [0008 — MediaEngine control and buffering](ge-proton11-11-se3-p9/0008-mfmediaengine-retain-control-intent-and-buffering-events.patch) | Honors the latest pause/play intent, keeps the replacement source's start position, checks seekability before recovery and consumes buffering events. |
| 9 | [0009 — Render clock and frame demand](ge-proton11-11-se3-p9/0009-mfmediaengine-retain-render-clock-frame-demand.patch) | Requests video samples against the render clock and applies a 50 ms seek-preroll floor to the cached fallback path. |
| 10 | [0010 — Source origin and queued tail](ge-proton11-11-se3-p9/0010-mfsrcsnk-retain-source-origin-and-queued-tail-drain.patch) | Carries the source origin through the source/sink path and drains queued tail samples before end-of-stream. |
| 11 | [0011 — Failed async result status](ge-proton11-11-se3-p9/0011-mfplat-retain-failed-async-result-status.patch) | Preserves the status of a failed asynchronous result instead of reporting success. |
| 12 | [0012 — VR extensions on Wayland](ge-proton11-11-se3-p9/0012-winewayland-retain-vr-device-extensions.patch) | Exposes Wine's synthetic OpenVR and OpenXR device-extension requests through the Wayland driver. |
| 13 | [0013 — Held-marker test context](ge-proton11-11-se3-p9/0013-mf-tests-retain-held-marker-context.patch) | Keeps the Media Foundation test context for held markers in step with the session changes. |
| 14 | [0021 — Stop the clock after a terminal start error](ge-proton11-11-se3-p9/0021-mf-stop-clock-after-terminal-start-error.patch) | Fixes reload after a terminal error during a restarting seek: the stale running clock no longer blocks the replacement source's preroll. |
| 15 | [0022 — Deliver read-ahead data errors when reached](ge-proton11-11-se3-p9/0022-winedmo-defer-read-ahead-data-errors.patch) | A data error on a future packet is raised when playback reaches it, not seconds early; queued good samples are kept. |
| 16 | [0023 — Interrupt a stalled read on seek](ge-proton11-11-se3-p9/0023-winedmo-interrupt-stalled-read-on-seek.patch) | A seek cancels a stalled progressive HTTP read and reopens the transport with a fresh request. |
| 17 | [0024 — Adopt GE's HTTP reconnect](ge-proton11-11-se3-p9/0024-winedmo-adopt-ge-http-reconnect.patch) | Uses GE's reconnect (`.mp4` and googlevideo URLs on GE-Proton11-9) and one 403 retry, with our first-request identity and a longer outer deadline. |
| 18 | [0025 — Work-queue shutdown without deadlock](ge-proton11-11-se3-p9/0025-rtworkq-shut-down-system-queues-without-holding-the-lock.patch) | The process no longer hangs at exit when a URL is still opening while Media Foundation shuts down; a startup that overlaps a shutdown waits for it. |
| 19 | [0026 — WM reader seeks land on target](ge-proton11-11-se3-p9/0026-winedmo-let-wm-reader-seek-read-while-flushing.patch) | The Windows Media sync reader seeks to the requested position instead of restarting from the beginning. |
| 20 | [0027 — DirectShow parser seek and restart](ge-proton11-11-se3-p9/0027-winedmo-serialise-quartz-parser-seeks-and-rewind-on-restart.patch) | Seeks in MPEG-PS and Matroska files work, and a Stop then Run restart plays again from the right place. |
| 21 | [0028 — Streams activated together at start](ge-proton11-11-se3-p9/0028-winedmo-activate-selected-streams-before-start.patch) | No lost leading packets at stream start: all selected streams become active before the demuxer delivers data. |
| 22 | [0029 — Raw FLAC sample depth](ge-proton11-11-se3-p9/0029-winedmo-default-raw-flac-bits-per-sample.patch) | Raw FLAC files report their sample depth. |
| 23 | [0030 — MPEG-4 and MS-MPEG4 FourCC aliases](ge-proton11-11-se3-p9/0030-winedmo-map-mpeg4-and-msmpeg4-fourcc-aliases.patch) | AVI files tagged xvid, divx, DX50, FMP4, DIV3 and similar aliases are recognized and play. |
| 24 | [0031 — Unplayable media reports an error](ge-proton11-11-se3-p9/0031-mfmediaengine-report-unplayable-topology-as-src-not-supported.patch) | MediaEngine raises an error (not supported) when nothing can decode the source, instead of staying in the loading state. |
| 25 | [0032 — Reconnect for every direct HTTP URL](ge-proton11-11-se3-p9/0032-winedmo-reconnect-all-direct-http-and-hls-requests.patch) | Byte-exact HTTP reconnect for every direct URL and for HLS segment, key and playlist transfers; a brief 5xx at open is retried. |
| 26 | [0033 — Live RTSP end is a network error](ge-proton11-11-se3-p9/0033-winedmo-report-live-rtsp-end-as-network-error.patch) | A live RTSP stream that ends (publisher dropped or server restarted) reports a connection error rather than a normal end. |
| 27 | [0034 — Multipart MJPEG timing](ge-proton11-11-se3-p9/0034-winedmo-timestamp-multipart-mjpeg-by-arrival.patch) | Multipart MJPEG over HTTP is timed by frame arrival instead of a nominal frame rate. |
| 28 | [0035 — Probe audio streams missing a format](ge-proton11-11-se3-p9/0035-winedmo-probe-audio-streams-missing-format.patch) | Audio streams that lack a sample rate or channel count are probed so raw FLAC resolves. |
| 29 | [0036 — ASF seek flushes every stream](ge-proton11-11-se3-p9/0036-qasf-flush-every-stream-when-seeking.patch) | A seek in a DirectShow ASF file no longer hangs. |
| 30 | [0037 — Async WM delivery pacing after a seek](ge-proton11-11-se3-p9/0037-wmvcore-pace-async-delivery-from-the-start-position.patch) | Video resumes at once after a seek in an asynchronously paced Windows Media file. |
| 31 | [0038 — Registry handle leak](ge-proton11-11-se3-p9/0038-mfplat-close-the-category-key-after-enumerating-transforms.patch) | Closes the transform-category registry key after enumeration; opening a video no longer leaks handles. |
| 32 | [0040 — HLS segment retry pacing](ge-proton11-11-se3-p9/0040-winedmo-space-hls-segment-retries-after-server-errors.patch) | A segment or key request answered with a server error (5xx or 429) is retried three times, after 1, 2 and 3 seconds. Playlists are unchanged. |
| 33 | [0041 — Give up on a silent HTTP server sooner](ge-proton11-11-se3-p9/0041-winedmo-give-up-on-a-silent-http-server-sooner.patch) | Reconnects after 8 s without data and reports one error after 15 s (known length) or 20 s (live) of silence instead of waiting up to 75 s. |
| 34 | [0042 — Empty input samples](ge-proton11-11-se3-p9/0042-winedmo-ignore-empty-input-samples.patch) | An empty input sample is ignored instead of ending the stream, so playback reaches its natural end when an audio effect answers a drain with an empty sample. |

## FFmpeg build and companion modules

These change GE's FFmpeg build or source and are bound by hash in the
[pin](../config/ge-proton11-11-se3.env); they are not part of the Wine series.
Wine behavior that depends on them is noted.

| Module | What it addresses |
| --- | --- |
| [Secure RTSPS redirects](proposed/ffmpeg-keep-rtsps-redirects-secure.patch) | Rejects non-`rtsps` redirects from a TLS session and clears credentials when the authority changes. |
| [HTTP seek honors Connection: close](proposed/ffmpeg-http-seek-respect-connection-close.patch) | Reuses a seek connection only when persistence was requested. |
| [HTTP file size on a failed seek](proposed/ffmpeg-http-restore-filesize-on-failed-seek.patch) | An error response's body length no longer replaces the entity length. |
| [HLS seek before the first segment](proposed/ffmpeg-hls-allow-seeks-before-first-segment.patch) | A timestamp below the playlist start selects the first segment instead of failing. |
| [MPEG video parser](proposed/ffmpeg-enable-mpeg-video-parser.patch) | Enables the parser WineDMO already requests, fixing backward timestamps for B-frame MPEG video. |
| [AAC (ADTS) parser](proposed/ffmpeg-enable-aac-parser.patch) | New in SE2, kept in SE3. Gives MPEG-TS/HLS audio correct per-packet durations so read-ahead is credited correctly (shorter HLS refill holds). |

The AES-128 HLS crypto-protocol build patch has its own
[guide](ffmpeg-build/README.md); SE3 uses [series-ge-proton11-9](ffmpeg-build/series-ge-proton11-9).

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

The SE3 release series references the candidate SE3-P9 patch directory.
`experimental/`, older `ge-proton*` variants, the SE2 and SE3 candidate histories
(`series-*-se2-p*`, `series-*-se3-p*` and their patch directories, kept because the preparation
tests check them) and the other `series-*` lists remain for comparison;
inclusion in a directory does not mean a patch ships. The unqualified
`patches/series` is the retained A3.21 selection, not SE3's list. The separate
launcher compatibility patch under `proton/` is not part of SE3, which uses
the unchanged GE launcher. SE1's and SE2's indexes are in the `se1` and `se2` tags.

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
