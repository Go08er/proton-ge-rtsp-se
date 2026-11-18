# Development on main: SE4-P6

`main` carries an unreleased development candidate, **SE4-P6** (build name
`proton-ge-11-12-rtsp-se4-p6`). It is source only: it is not tagged, not
released, and there is no binary for it on GitHub. The latest release is still
**SE3** (see [RELEASE.md](../RELEASE.md)); everything the README and the
release notes say about SE3 stays true for SE3.

SE4-P6 is published so that others can read, build and test it. It has had
much less testing than a release (see "Testing status").

## What it is

- **Base:** GE-Proton11-12.
- **Wine:** the project's 36-patch series, applied after GE's own
  `ge-video-rework`.
- **FFmpeg:** the pinned security backports and build modules listed below.

Files that define it:

- Pin: `config/ge-proton11-12-se4-p6.env`
- Series: `patches/series-ge-proton11-12-se4-p6`
- Wine patches: `patches/ge-proton11-12-se4-p6/`
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

## How to build it

```sh
bash scripts/build-se4-p6.sh \
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
- The pin skips two GE patches (see the comments in the pin): GE's pending
  rtworkq hotfix, which conflicts with the project's own rtworkq patch, and a
  protonfixes patch whose files the pinned protonfixes already contains. The
  build name is `proton-ge-11-12-rtsp-se4-p6`.

The pin budgets 8 jobs (Make 4 x Ninja 2); the script accepts at most 8.
`scripts/build-se1.sh`, `build-se2.sh` and `build-se3.sh` are unchanged.

## Changes since SE3

- **Rebased on GE-Proton11-12.** The SE3 Wine series was carried to the new
  GE base.
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
  after a connection reset". It does not apply to SE4-P6. Direct HTTP sources
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
- **Audio renderer lock.** The audio renderer no longer holds its lock across
  audio-driver calls, so a stalled audio server no longer blocks the
  application's per-frame video calls.

## Testing status

- The automated qualification suite passed against the previous candidate.
- One session of about three hours of ordinary in-game video playback showed
  no stalls or lock waits in the diagnostics.
- The live RTSP-over-TCP case that motivated the last two patches is **not yet
  confirmed in game**.

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

## Diagnostics

The media engine and the audio renderer print WARN and ERR lines on the
`mfplat` channel for slow application callbacks, long engine-lock holds or
waits, and slow audio-driver calls (100 ms or more is a WARN, one second or
more an ERR). When reporting a problem, run with `WINEDEBUG=warn+mfplat` and
read [TESTING.md](TESTING.md) first for what to redact.
