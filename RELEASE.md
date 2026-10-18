# SE2 — GE-Proton11-9 RTSP prerelease

Experimental x86_64 Linux prerelease, built on the GE-Proton11-9 base.
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
  under-credited: holds were about 6 s instead of 19 s under an 80% throttle.
- FFmpeg build modules: secure RTSPS redirects, HTTP seek and file-size
  fixes, an HLS seek before the first segment, the MPEG video parser and the
  AAC parser. Details are in the [patch index](patches/README.md).

## Download and verify

Binary: `proton-ge-11-9-rtsp-se2.tar.gz` — **@SE2_BINARY_BYTES@ bytes**.

SHA-256:
```text
@SE2_BINARY_SHA256@
```

Download `SHA256SUMS` alongside your chosen assets and run
`sha256sum --check --ignore-missing SHA256SUMS`; require an `OK` result for
each downloaded file. See [installation and NixOS](docs/INSTALL.md).

Source/build materials:

- `proton-ge-11-9-rtsp-se2-source-x86_64.tar.zst`: prepared corresponding
  source, @SE2_SOURCE_BYTES@ bytes; SHA-256
  `@SE2_SOURCE_SHA256@`.
- `proton-ge-11-9-rtsp-se2-build-inputs.tar.zst`: the 16 verified contrib
  inputs, 475,823,823 bytes; SHA-256
  `a65db70c69c4af73d2b4d3d005ebd409283fce5ce1ec574b17234cb6f52039c1`.
- `SUBMODULES.tsv`, `UPSTREAM-SOURCES.tsv` and the additional Gecko, ONNX
  Runtime, Xalia and zenity-rs source archives complete the source account
  described in [source and licensing](docs/SOURCE.md).
- Repository source contains the selected pin, patches, manifests, tests,
  Nix packaging and [automated build instructions](docs/BUILDING.md).

## Qualification and limits

@SE2_QUALIFICATION@

Known limits:

- A rare freeze after a backward seek was seen once in 10 runs on the
  candidate; its cause is not established.
- HTTP reconnect applies only to `.mp4` and googlevideo URLs, as in upstream
  GE-Proton11-9.
- 18 of the 102 F102 coordinate cases need an observer to judge; they are not
  automated passes.
- Background errors appear in the logs from a maintainer VRChat test whose
  user experience was good. Log output is not a playback oracle.
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
