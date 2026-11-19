# Development on main: SE4-P7

`main` carries an unreleased development candidate, **SE4-P7** (build name
`proton-ge-11-12-rtsp-se4-p7`). It is source only: it is not tagged, not
released, and there is no binary for it on GitHub. The latest release is still
**SE3** (see [RELEASE.md](../RELEASE.md)); everything the README and the
release notes say about SE3 stays true for SE3.

SE4-P7 is published so that others can read, build and test it. It has had
much less testing than a release (see "Testing status").

## What it is

- **Base:** GE-Proton11-12.
- **Wine:** the project's 36-patch series, applied after GE's own
  `ge-video-rework`. It is identical to the previous candidate, SE4-P6.
- **FFmpeg:** the pinned security backports and build modules listed below.
- **DXVK:** two versions ship side by side (see "Choosing the DXVK version").

Files that define it:

- Pin: `config/ge-proton11-12-se4-p7.env`
- Series: `patches/series-ge-proton11-12-se4-p7`
- Wine patches: `patches/ge-proton11-12-se4-p7/`
- Launcher patch: `patches/proton/0002-launcher-add-dxvk-legacy-selection.patch`
- Second DXVK build module: `patches/proposed/dxvk-legacy-build-module.patch`
- Manifests: `config/ge-build-contrib-f85547f0-full-ge.tsv`,
  `config/ge-media-cleanup-f85547f0.tsv` and
  `release-manifests/GE-Proton11-12.manifest.tsv`

FFmpeg patch and module files named by the pin:

- `patches/ffmpeg-security/` (four backports) and
  `patches/ffmpeg-build/ge-proton11-9/0001-ffmpeg-enable-crypto-protocol-for-AES-128-HLS.patch`
- `patches/proposed/ffmpeg-keep-rtsps-redirects-secure.patch`
- `patches/proposed/ffmpeg-http-seek-respect-connection-close.patch`
- `patches/proposed/ffmpeg-http-restore-filesize-on-failed-seek.patch`
- `patches/proposed/ffmpeg-http-chunked-end-not-premature.patch`
- `patches/proposed/ffmpeg-hls-allow-seeks-before-first-segment.patch`
- `patches/proposed/ffmpeg-hls-announce-changed-init-codec-config.patch`
- `patches/proposed/ffmpeg-enable-mpeg-video-parser.patch`
- `patches/proposed/ffmpeg-enable-aac-parser.patch`

## Choosing the DXVK version

SE4-P7 ships two DXVK builds:

- **Primary:** GE-Proton11-12's DXVK (v3.1.1-174, with GE's DXVK patches), in
  `files/lib/wine/dxvk/`. Every game uses it unless told otherwise.
- **Legacy:** upstream DXVK `2cae043b` (v2.7.1-668), unpatched, in
  `files/lib/wine/dxvk-legacy/`.

Why: in VRChat, a Unity game, the game can stop for about 30 seconds at a time
while DXVK 3.1.1 compiles shaders, typically when a world or new avatars load.
Profiles taken during these stops show the time inside DXVK itself, not in the
graphics driver. Upstream DXVK has a similar open report,
[doitsujin/dxvk#6052](https://github.com/doitsujin/dxvk/issues/6052). The
legacy build is the same DXVK commit that a build of
[SpookySkeletons' Proton-RTSP](https://github.com/SpookySkeletons/proton-rtsp)
ships; with that build, these stops were not seen.

How the launcher picks one, highest priority first:

1. `PROTON_DXVK_LEGACY=1` in the launch options (or `user_settings.py`)
   selects legacy, `PROTON_DXVK_LEGACY=0` selects primary.
2. The compatibility tokens `dxvklegacy` and `nodxvklegacy` in
   `STEAM_COMPAT_CONFIG` (if both are set, primary wins).
3. VRChat (AppID 438100) defaults to legacy.
4. Every other game uses primary.

So any game can try the legacy DXVK with `PROTON_DXVK_LEGACY=1 %command%`, and
VRChat can return to the primary DXVK with `PROTON_DXVK_LEGACY=0 %command%`.
The launcher copies the chosen DLLs into the prefix at every launch, so
switching needs nothing else. The first launch after a switch compiles shaders
again. The launcher log names the variant: `DXVK variant: legacy|default
(reason)`.

The legacy DXVK has none of GE's DXVK patches (for example HDR detection and
fullscreen fixes for specific games). D3D12 games run on VKD3D-Proton, which
uses DXVK only for DXGI; that pairing has not been tested with the legacy
DXVK.

## How to build it

```sh
bash scripts/build-se4-p7.sh \
  --work-dir /path/to/new/directory \
  --fresh-setup-receipt /path/to/fresh-setup-receipt.json
```

The host requirements, the receipt and the rules about work directories and
caches are the same as in [BUILDING.md](BUILDING.md). What differs:

- Run the script directly, with the host tools from `shell.nix` available.
  `nix run .#build-from-source` still builds SE3.
- No build-inputs archive exists for this candidate. All 16 contrib inputs are
  fetched from their original URLs and checked against the pinned manifest.
  The Piper `pic.zip` input is branch-derived, so its check fails if upstream
  changes that archive.
- The legacy DXVK needs no extra download: its source is exported at prepare
  time from the DXVK repository that the GE source already contains, and
  checked against pinned commit and tree ids.
- The pin skips two GE patches (see the comments in the pin): GE's pending
  rtworkq hotfix, which conflicts with the project's own rtworkq patch, and a
  protonfixes patch whose files the pinned protonfixes already contains.

The pin budgets 8 jobs (Make 4 x Ninja 2); the script accepts at most 8.
`scripts/build-se1.sh`, `build-se2.sh`, `build-se3.sh` and `build-se4-p6.sh`
are unchanged.

## Changes since SE3

- **Rebased on GE-Proton11-12.** The SE3 Wine series was carried to the new
  GE base.
- **Two DXVK versions, selectable per game** (see above). VRChat uses the
  legacy DXVK by default.
- **Live streams from Twitch-style services no longer stall repeatedly.**
  This was SE3's known issue. SE3 forced a reconnect on every HLS segment,
  key and playlist request. A live-edge segment sent as a finished chunked
  response was mistaken for a broken transfer, and was retried for seconds,
  so playback fell behind and stalled again and again. That forced reconnect
  is removed; HLS requests behave as in GE.
- **Live HLS discontinuities no longer freeze the video timeline.** When a
  live playlist restarts its timestamps (a stitched ad, a stream restart),
  the timeline now continues instead of being clamped, so video no longer
  stops for the length of the restart.
- **An HLS stream whose init section changes codec configuration is
  handled.** A new codec configuration in a later init section is now passed
  to the decoder, which previously produced no video for those segments.
- **Retracted from SE3:** "HLS segment, key and playlist transfers also resume
  after a connection reset". It does not apply to SE4. Direct HTTP sources
  still reconnect.
- **HLS segment and key retries are gone.** A segment or key answered with a
  5xx or 429 is no longer retried; the faulted segment is skipped (about 2 s
  of media is lost).
- **Live sources report as live.** A network source with no duration is
  reported as live. Such a source sends BUFFERINGSTARTED and BUFFERINGENDED,
  but no WAITING or PLAYING events on Play or on rebuffering.
- **The URLMon fallback is removed.** A failed plain HTTP open reports its own
  error to the application.
- **No application callbacks under the engine lock.** The media engine no
  longer calls into the application while holding its own lock, so a slow
  callback no longer blocks the application's per-frame calls.
- **Audio renderer lock.** Starting, stopping, resetting and volume changes no
  longer call the audio driver while holding the renderer's lock. Reading the
  audio clock and filling audio buffers still do. (SE4-P6's notes said the
  renderer no longer held its lock across any audio-driver call; that was too
  broad.)

## Testing status

- **Not yet verified in game:** whether the legacy DXVK avoids the VRChat
  stops. That is the reason for this candidate, and it has not been played
  yet.
- The Wine series and FFmpeg are identical to SE4-P6's, which passed the
  automated qualification suite. The live RTSP-over-TCP case that motivated
  SE4-P6's last two patches is still **not confirmed in game**.
- The DXVK selection was tested in scratch prefixes: each rule of the order
  above, including the cases where two rules disagree, switching back and
  forth in one prefix, `PROTON_USE_WINED3D=1` with and without `dxvkd3d8`,
  and a copy of the build with `dxvk-legacy/` removed. Whenever DXVK was in
  use, the prefix held the selected build's DLLs after the launch, and
  switching never changed the prefix version.
- A D3D11 Media Foundation test program (a local H.264 file and a local RTSP
  stream, every frame copied into a D3D11 texture) ran without errors under
  both DXVK builds and under SE4-P6, with similar per-call timings.
  dxvk-nvapi initialized under both builds.
- Not tested: VR/OpenXR at runtime, and D3D12 games with the legacy DXVK.

## Known limits

- Live RTSP: when the server's first RTCP sender report arrives, FFmpeg
  re-aligns audio and video, so playback can jump ahead once by a fraction of
  a second (carried over from SE3).
- A player that polls at exactly the video frame rate can see 60 fps content at
  40 fps, because Wine's audio clock advances in 10 ms steps. This is
  pre-existing and also in SE3.
- While the audio server is stalled, an application's pause, stop, volume or
  shutdown call on a player can still wait until the stall ends. This is work
  in progress.
- Several video players share one work queue, so a slow event handler in one
  player can delay another player's events. This is work in progress.

## Diagnostics

The media engine and the audio renderer print WARN and ERR lines on the
`mfplat` channel for slow application callbacks, long engine-lock holds or
waits, and slow audio-driver calls (100 ms or more is a WARN, one second or
more an ERR). When reporting a problem, run with `WINEDEBUG=warn+mfplat` and
read [TESTING.md](TESTING.md) first for what to redact.
