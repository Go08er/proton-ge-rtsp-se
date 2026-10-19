# SE2 — GE-Proton11-9 RTSP prerelease

Experimental x86_64 Linux prerelease on the GE-Proton11-9 base, built and
qualified on 2026-10-18.
Intended for users experienced with Proton debugging; assistance is not guaranteed.

Tool name: `proton-ge-11-9-rtsp-se2`. Nix users: use tag `se2`.

SE2 carries 17 Wine media patches (the P23 set) plus FFmpeg build modules,
including a new AAC parser. The launcher must match the pinned upstream GE
file exactly; there is no launcher-side XR policy. SE1 (GE-Proton11-6) remains
available under its own tags.

## Changes since SE1

- **Rebased on GE-Proton11-9.** The Wine series was re-derived against the new
  base as 17 patches; the SE1 patch set was not reapplied unchanged.
- **Reload after a network error works.** A terminal source error during a
  restarting seek no longer leaves the presentation clock running, so the
  replacement source starts and finishes preroll.
- **Corrupt-data errors are delivered when playback reaches them.** A data
  error on a future packet no longer ends playback seconds early or discards
  the already-queued good samples.
- **Instant seek during a stalled download.** A seek interrupts the stalled
  read and reopens the transport with a fresh request, rather than waiting for
  the read to time out.
- **GE11-9's HTTP reconnect and single 403 retry are adopted.** As upstream,
  reconnect applies only to `.mp4` and googlevideo progressive URLs; other
  HTTP media is unchanged.
- **HLS refill holds are shorter.** An FFmpeg AAC parser build module gives
  MPEG-TS audio correct packet durations, so read-ahead is no longer
  under-credited: in a contained loopback test under an 80% throttle, holds
  were about 6 s instead of one 19 s hold.
- FFmpeg build modules: secure RTSPS redirects, HTTP seek and file-size
  fixes, an HLS seek before the first segment, the MPEG video parser and the
  AAC parser. Details are in the [patch index](patches/README.md).

## Download and verify

Binary: `proton-ge-11-9-rtsp-se2.tar.gz` — **565,841,164 bytes**.

SHA-256:
```text
0568079f9685b4647eb31490ea9e64ca4dcec8b3ae60468e66b36c5c69db1591
```

Download `SHA256SUMS` alongside your chosen assets and run
`sha256sum --check --ignore-missing SHA256SUMS`; require an `OK` result for
each downloaded file. See [installation and NixOS](docs/INSTALL.md).

Source/build materials:

- `proton-ge-11-9-rtsp-se2-source-x86_64.tar.zst`: prepared corresponding
  source, 1,402,978,802 bytes; SHA-256
  `240cd96951722b53486373acc95a8d8eb780f59ec8867bb013bface5e9a6b538`.
- `proton-ge-11-9-rtsp-se2-build-inputs.tar.zst`: the 16 verified contrib
  inputs, 475,823,823 bytes; SHA-256
  `a65db70c69c4af73d2b4d3d005ebd409283fce5ce1ec574b17234cb6f52039c1`.
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
  - preparation, independent fresh-setup verification, artifact
    re-verification, source audits and post-build preparation all passed.
- **Artifact checks passed:**
  - hashes and gzip integrity;
  - exact archive/tree match;
  - links, types and permissions;
  - home-path privacy scan;
  - no WineGStreamer payload.
- **The same content as the tested candidate.** SE2 rebuilds the exact
  content of candidate P24 under the release name:
  - the same pin fields apart from identity;
  - the same 17 Wine patches;
  - the same prepared Wine tree (all 28 media postimage hashes);
  - identical FFmpeg configuration.
- **File-by-file comparison of the tool trees (6,160 files):**
  - 4,343 files are byte-identical;
  - the rest differ only by build name or path, build IDs, timestamps or
    generated IDs;
  - every media-critical binary (Media Foundation, WineDMO, quartz, FFmpeg)
    is identical once those fields are normalized;
  - the launcher is byte-identical.
- **Nix.** The Nix prebuilt package built from the release archive matches
  the tool exactly, and the NixOS module evaluates.

## Runtime (SE2 artifact; contained loopback unless noted)

- **Contained tests pass:**
  - RTSP ×2;
  - HLS healthy, burst and seek;
  - HTTP seek;
  - HLS VOD.
- **Throttle and warm-up.** Five 80%-throttle/warm-up runs pass the frozen
  policy scorer, each with two holds of about 6 s and no startup hold.
- **ALAC.** The ALAC SourceReader ×4 shows no leading-sample loss.
- **Backward startup.** HTTPS backward startup passes.
- **F102 102-case regression set:** 79 PASS / 5 FAIL / 12 INCOMPLETE / 6 not run, with no case changing class
  against the previous candidate baseline (79 / 5 / 18). The FAILs are the
  two cases whose frozen oracle forbids the adopted GE 403 retry, and three
  inherited SourceReader cases decided as no product change. The 18
  decoder-coordinate cases are INCOMPLETE or not run on a clean package
  (no decoder-identity records), as on the baseline.

**Candidate history.** P24 is content-identical to SE2. It passed the same
contained set and went through a maintainer VRChat session that played well.

Known limits:

- HTTP reconnect applies only to `.mp4` and googlevideo URLs, as in upstream
  GE-Proton11-9.
- The 18 decoder-coordinate cases of the 102-case F102 regression set report
  INCOMPLETE on a clean package: they need decoder-identity records that only
  a qualification overlay emits. They are not passes.
- A maintainer VRChat session on the content-identical candidate played well,
  but its logs show background errors that have not yet been classified. Log
  output is not a playback oracle.
- The unattended source-build wrapper needs a fresh-setup receipt that this
  repository's tooling does not produce on its own; see
  [building](docs/BUILDING.md).

SE2 is pre-release. No general stability, format coverage, long-soak or
measured A/V synchronization guarantee follows. Keep a fallback compatibility
tool and report confirmed, privacy-reviewed reproductions. See
[testing](docs/TESTING.md).

## Privacy

No private Proton logs, game prefixes, account data, private media URLs or
captured third-party media are in any asset. Only synthetic fixtures and
reviewed source are published.
