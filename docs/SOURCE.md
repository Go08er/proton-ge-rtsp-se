# Source and licensing

SE2 is an additive patchset over GE-Proton11-9, not an independent media
backend. Upstream authors retain their copyrights and licenses. The root
BSD-3-Clause license covers this repository's independently authored tooling
where applicable; it does not relicense Wine, FFmpeg or third-party code.
Patches modifying upstream files follow the licenses of those files.

## Exact build inputs

- GE commit: `01bfbf67b35418fdd705f2be09e0bfb43eece24b` (tag `GE-Proton11-9`).
- GE root tree: `465a332291b33655c8bfacf94ab8ac0f2779551e`.
- Wine: `981e2f0b9007fd70a6e0ed6119cb18f4164e26f9`.
- FFmpeg: `9047fa1b084f76b1b4d065af2d743df1b40dfb56`, plus the declared
  security/TLS and crypto-build patch series, and six hash-pinned build
  modules (secure RTSPS redirects, HTTP seek, HTTP file size, HLS early seek,
  MPEG video parser, AAC parser).
- Wine patch series: `patches/series-ge-proton11-9-se2`, 17 entries.
- Ordered Wine series/content SHA-256 (`pinned_ge_series_digest`):
  `fa18c907344c727af11e03751f1cae19b538680f8d6c3274fda58afb48c19bb2`.
- Pin: `config/ge-proton11-9-se2.env`; this selects the upstream launcher.
- Complete GE root gitlinks: `release-manifests/GE-Proton11-9.manifest.tsv`
  (43 registered submodules).
- All 98 initialized top-level/nested submodule revisions:
  release asset `SUBMODULES.tsv` (source revisions, not a count of compiled
  components).
- Contrib inputs: `config/ge-build-contrib-01bfbf67-full-ge.tsv` (16 entries).

The exact SDK image and its verified image ID are in the pin. The build uses
Make 4 × Ninja 2 and an offline container; source/input acquisition is a
separate step. The NVIDIA-library and Vulkan-layer payload groups are built
(neither is disabled in the pin). The original GE source, all active patches
and the preparation/build scripts are part of the source account.

Wine changes concern the Media Foundation/MediaEngine, WineDMO and
WineWayland paths. FFmpeg remains the demux/decode backend. The SE2 launcher
matches upstream GE byte-for-byte; `PROTON_XR_MODE` is not parsed or applied.

## Distribution materials

The prerelease includes verified binary/source materials and checksums;
their final filenames and hashes are recorded in [the release notes](../RELEASE.md).
The prepared-source archive is intended for source inspection and the exact
modified source record. Use the pinned clean-input workflow for rebuilding,
not a stale configure-state or an unrelated prepared checkout.
Git administration, Python caches and the three unused FEX precompiled test
collections (`fex-gcc-target-tests-bins`, `fex-gvisor-tests-bins`,
`fex-posixtest-bins`) are omitted. GE's Makefile enables FEX only for
aarch64; it is not part of this x86_64 artifact. Their initialized revisions
remain recorded in `SUBMODULES.tsv`. No compiled/modified SE2 source is
omitted by that exclusion.

The binary retains upstream `LICENSE` and `LICENSE.OFL`. Component license
texts remain in their corresponding source trees. Gecko, Mono, Xalia, ONNX
Runtime and zenity-rs are upstream prebuilt inputs, as they are in GE's
workflow: "from source" here means rebuilding the Proton/GE candidate, not
claiming that every third-party bootstrap input is rebuilt from source.
Their origins and expected hashes are recorded rather than hidden.

The release also supplies the official Wine Gecko 2.47.4 source
distribution and source snapshots for ONNX Runtime 1.14.1, Xalia 0.5.0 and
zenity-rs 0.2.8; the Wine Mono 11.3.0 source is part of the build-input
archive. The snapshots retain their dependency
manifests/submodule declarations; they are not claims that all optional
upstream dependencies have been vendored or independently rebuilt.
The build-input archive includes the actual Piper/espeak-ng/Sonic source
archives used by this build. See `UPSTREAM-SOURCES.tsv` in the release for
origins, sizes and independently observed SHA-256 values.

The inherited GE license file mentions GStreamer from its broader upstream
distribution. SE2's artifact check requires that no GStreamer payload is
present; retaining that notice is not evidence of another media backend.

No private Proton logs, game prefixes, account data or captured third-party
media are part of the public source export.
