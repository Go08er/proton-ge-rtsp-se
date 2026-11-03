# SE3 — GE-Proton11-11 RTSP prerelease

Experimental x86_64 Linux prerelease on the GE-Proton11-11 base, built and
qualified on @SE3_DATE@.
Intended for users experienced with Proton debugging; assistance is not guaranteed.

Tool name: `proton-ge-11-11-rtsp-se3`. Nix users: use tag `se3`.

SE3 carries 34 Wine media patches plus FFmpeg build modules, including the AAC
parser. The launcher must match the pinned upstream GE file exactly; there is
no launcher-side XR policy. SE1 (GE-Proton11-6) and SE2 (GE-Proton11-9) remain
available under their own tags.

## Changes since SE2

- **Rebased on GE-Proton11-11.** The 17 SE2 Wine patches were carried to the
  new base (three needed new offsets or a rebase) and 17 new patches were added
  on top.
- **No hang at exit while a URL is still opening.** Media Foundation shutdown
  no longer waits forever on an open that has not finished, and a startup that
  overlaps a shutdown waits for it instead of leaving the platform half
  started.
- **Videos reach their natural end.** Playback no longer stops short of the
  end, with the audio running dry, in configurations where an audio effect
  answers a drain request with an empty sample.
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

Binary: `proton-ge-11-11-rtsp-se3.tar.gz` — **@SE3_BINARY_BYTES@ bytes**.

SHA-256:
```text
@SE3_BINARY_SHA256@
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

## Build and identity

- **Build.** One offline GE `redist` build completed for both Wine
  architectures:
  - pinned budget Make 4 × Ninja 2;
  - all 98 submodules and the 16 contrib inputs seeded locally;
  - @SE3_BUILD_CHECKS@
- **The same content as the tested candidate.** @SE3_IDENTITY_TEXT@
- **Nix.** @SE3_NIX_TEXT@

## Runtime

@SE3_QUALIFICATION@

Known limits:

- The audio clock advances in 10 ms steps, as in GE-Proton11-11 and earlier
  releases; at 60 fps, frames therefore land 20, 20 and 10 ms apart.
- The silent-source policy is deliberate: an outage longer than roughly 10 to
  14 seconds ends playback with one error, and the last buffered seconds are
  not played before that error.
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
