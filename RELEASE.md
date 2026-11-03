# SE3 — GE-Proton11-11 RTSP prerelease

Experimental x86_64 Linux prerelease on the GE-Proton11-11 base, built and
qualified on 2026-11-03.
Intended for users experienced with Proton debugging; assistance is not guaranteed.

Tool name: `proton-ge-11-11-rtsp-se3`. Nix users: use tag `se3`.

SE3 carries 34 Wine media patches plus FFmpeg build modules, including the AAC
parser. The launcher must match the pinned upstream GE file exactly; there is
no launcher-side XR policy. SE1 (GE-Proton11-6) and SE2 (GE-Proton11-9) remain
available under their own tags.

## Changes since SE2

- **Videos end properly.** In SE2, players that pass audio through their own
  audio effect, such as VRChat's AVPro video player, could freeze at the end
  of a video with a buzzing sound and never report that the video had
  finished. Wine's media decoders and converters now ignore an empty input
  sample instead of treating it as the end of the stream, so playback reaches
  the end and the player is told that it finished.
- **Rebased on GE-Proton11-11.** The 17 SE2 Wine patches were carried to the
  new base (three needed new offsets or a rebase) and 17 new patches were added
  on top.
- **No hang at exit while a URL is still opening.** Media Foundation shutdown
  no longer waits forever on an open that has not finished, and a startup that
  overlaps a shutdown waits for it instead of leaving the platform half
  started.
- **No lost leading frames at stream start.** All selected streams become
  active together, so the first packets of a later stream (for example a
  leading ALAC block) are not dropped.
- **HTTP reconnect for every direct URL.** GE enabled byte-exact reconnect
  only for `.mp4` and googlevideo URLs; SE3 enables it for any direct HTTP
  source, resumes at the exact byte on servers that support ranges, and
  retries a brief 5xx response at open. HLS segment, key and playlist
  transfers also resume after a connection reset.
- **HLS segment retries.** A segment or key request answered with a server
  error (5xx) or 429 is retried three times, after 1, 2 and 3 seconds, rather
  than skipped at once; a first segment that fails no longer fails the open.
- **A source that goes silent ends sooner.** A direct HTTP source that stops
  sending now reconnects after 8 s without data and reports one error after
  15 s (known-length media) or 20 s (live) of silence, instead of waiting up
  to 75 s. A source that returns within that window still resumes at the same
  byte.
- **A live RTSP stream that ends reports a network error.** When the
  publisher drops or the server restarts, the player gets a connection error
  and can retry, instead of freezing on the last frame as if the stream had
  finished normally.
- **Unplayable media reports an error.** When nothing can decode a source,
  MediaEngine raises "not supported" instead of staying in its loading state.
- **More files play.** Raw FLAC files play; AVI files tagged with the usual
  MPEG-4 Part 2 aliases (xvid, divx, DX50, FMP4) and MS-MPEG4 v3 (DIV3, MPG3)
  are recognized.
- **Seeking in legacy Windows Media and DirectShow content.**
  - Windows Media reader seeks land on the requested position.
  - Seeks in MPEG program streams and Matroska files, and a Stop then Run
    restart, work in the DirectShow parser.
  - A seek in an ASF file no longer hangs, and video resumes straight away
    afterwards.
- **Multipart MJPEG over HTTP** is timed by frame arrival rather than a
  nominal frame rate.
- **A handle leak is fixed.** Opening a video leaked about five kernel
  handles (three for a source reader); they are now closed.
- FFmpeg build modules are unchanged from SE2: secure RTSPS redirects, HTTP
  seek and file-size fixes, an HLS seek before the first segment, the MPEG
  video parser and the AAC parser. Details are in the [patch index](patches/README.md).

## Download and verify

Binary: `proton-ge-11-11-rtsp-se3.tar.gz` — **565,937,205 bytes**.

SHA-256:
```text
95d9094e4e7622376080d66ee50386306b6cb85255215222043287f0069f10c3
```

Download `SHA256SUMS` alongside your chosen assets and run
`sha256sum --check --ignore-missing SHA256SUMS`; require an `OK` result for
each downloaded file. See [installation and NixOS](docs/INSTALL.md).

Source/build materials:

- `proton-ge-11-11-rtsp-se3-source-x86_64.tar.zst`: prepared corresponding
  source, 1,408,247,639 bytes; SHA-256
  `e5f128a9785830096b5d649a2d66076a66fe224ae53f9bfe7ca2b19fc67373b9`.
- `proton-ge-11-11-rtsp-se3-build-inputs.tar.zst`: the 16 verified contrib
  inputs, 475,844,563 bytes; SHA-256
  `1e768c80e0fc5180321d3df3b9c093f5537a0d736f80608403ac32a19e4788cf`.
- `SUBMODULES.tsv`, `UPSTREAM-SOURCES.tsv` and the additional Gecko, ONNX
  Runtime, Xalia and zenity-rs source archives complete the source account
  described in [source and licensing](docs/SOURCE.md).
- Repository source contains the selected pin, patches, manifests, tests,
  Nix packaging and [automated build instructions](docs/BUILDING.md).

## Qualification and limits

### Build and identity

- **Build.** One offline GE `redist` build completed for both Wine
  architectures:
  - pinned budget Make 4 × Ninja 2;
  - all 98 submodules and the 16 contrib inputs seeded locally;
  - preparation, independent fresh-setup verification, artifact
    re-verification, source audits and post-build preparation all passed.
- **Artifact checks passed:**
  - hashes and gzip integrity;
  - exact archive/tree match;
  - links, types and permissions;
  - home-path privacy scan;
  - no WineGStreamer payload.
- **The same content as the tested candidate.** SE3 rebuilds the exact
  content of the candidate tested in VRChat, under the release name:
  - the same pin fields apart from identity;
  - the same 34 Wine patches;
  - an identical prepared Wine tree and identical FFmpeg configuration.
- **File-by-file comparison of the tool trees (6,164 files):**
  - 4,345 files are byte-identical;
  - the rest differ only by build name or path, build IDs, timestamps or
    generated IDs. The release name is three characters shorter, so embedded
    build paths shift bytes in 48 non-media binaries; their exported symbols
    are unchanged;
  - every media-critical binary (Media Foundation, WineDMO, quartz) is
    identical once those fields are normalized, and FFmpeg differs only by
    the build path in its configuration string and the byte shifts that
    follow from it;
  - the launcher is byte-identical.
- **Nix.** The Nix prebuilt package built from the release archive matches
  the tool exactly, and the NixOS module evaluates.

### Runtime

- **VRChat.** The candidate with this exact content was tested in VRChat:
  videos with AVPro's audio effect in the chain, including one with repeated
  seeks, played to their end with no buzzing and reported that they finished,
  and a local and an external live RTSP stream played.
- **End of video, offline.** Players that pass audio through their own
  effect reached the end and drained their audio in every SE3 run, across
  H.264/AAC, AV1, HEVC, VP8, VP9/Opus and 44.1 kHz AAC files, with and
  without repeated seeks. The candidate without the fix hung in the same
  tests.
- **Functional sweep.** 92 scenarios, compared with the first GE-Proton11-11
  candidate:
  - 48 unchanged and passing, 29 fixed;
  - 8 changed as intended by the shorter silent-source wait;
  - 7 unchanged known defects (legacy AMStream and mfplay paths, and HLS live
    and variant edge cases);
  - no regressions and no hangs.
- **Regression set.** 78 of 102 cases pass, 6 fail and 18 are incomplete. This
  is the same result as before, apart from one live RTSP case that failed
  once on the RTSP timing jump described below and passed in three reruns.
  ALAC streams start without lost frames (4 of 4).

Known limits:

- The audio clock advances in 10 ms steps, as in GE-Proton11-11 and earlier
  releases; at 60 fps, frames therefore land 20, 20 and 10 ms apart.
- Live RTSP: when the server's first RTCP sender report arrives (about 10 s
  in with MediaMTX), FFmpeg re-aligns audio and video to the server's timing,
  so playback can jump ahead once by up to about 0.15 s. SE2 and plain FFmpeg
  do the same. On SE3 the frame shown at that moment can be up to about 60 ms
  late.
- The silent-source policy is deliberate: in testing, server outages of up
  to 10 seconds resumed, while outages of 14 seconds or more ended playback
  with one error. The last buffered seconds are not played before that
  error.
- RGB32 output keeps GE's orientation behavior. The ARGB32 path used by
  Media Foundation players is unaffected; the Unity VideoPlayer path has not
  been checked.
- Legacy and niche paths (for example AMStream ASF, mfplay and live MJPEG
  startup) are not part of the qualification claims.
- The unattended source-build wrapper needs a fresh-setup receipt that this
  repository's tooling does not produce on its own; see
  [building](docs/BUILDING.md).

SE3 is pre-release. No general stability, format coverage, long-soak or
measured A/V synchronization guarantee follows. Keep a fallback compatibility
tool and report confirmed, privacy-reviewed reproductions. See
[testing](docs/TESTING.md).

## Privacy

No private Proton logs, game prefixes, account data, private media URLs or
captured third-party media are in any asset. Only synthetic fixtures and
reviewed source are published.
