# Build SE2 from source

The build uses a pinned GE-Proton11-9 commit, pinned submodules, 16
hash-checked contrib inputs and a specific SteamRT SDK image. The NVIDIA
library and Vulkan-layer groups are built. Fetching happens
before compilation; the build container remains `--network=none`.

On NixOS, enable rootless Podman in your normal system configuration first
(`virtualisation.podman.enable = true`) and ensure your account can use it.
Have substantial free space for source, SDK cache and intermediate objects
(allow at least 80 GB beyond your normal free-space reserve).

From a checkout of this repository, use a NEW directory outside the checkout:

```sh
nix run .#build-from-source -- \
  --work-dir "$HOME/builds/proton-ge-rtsp-se2-1" \
  --fresh-setup-receipt /path/to/fresh-setup-receipt.json
```

The pinned build refuses to start without a passing fresh Wine
configure/makedep receipt for the prepared source, which the wrapper forwards
but does not create. The gate (`tests/wine-header-compile/fresh_setup.py`) is
described in [its README](../tests/wine-header-compile/README.md); it runs in
the pinned SDK against retained configure logs, so an unattended end-to-end
build is not yet supported.

This acquires pinned sources and the SDK when absent, prepares and audits the
series, fetches/validates declared inputs, builds, and verifies the artifact.
By default the 16 contrib inputs come from the release's hash-pinned cache
archive; every file is then checked against the original input manifest.
It installs nothing into Steam and does not start Steam. The pin sets the
budget to 8 (Make 4 × Ninja 2), which is also the wrapper's maximum; use
`--jobs 4`, for example, on a smaller machine. A larger budget needs an
explicit `PINNED_GE_AUTHORIZED_JOB_CAP` and the lower-level scripts.
Builds honor the shared `~/Documents/.proton-build.lock` by default. Do not
run a second cooperating Proton build outside that lock.

To reuse local inputs, add:

```sh
--seed /path/to/local/ge-source \
--contrib-cache /path/to/contrib-cache \
--sdk-cache /path/to/isolated-sdk-cache
```

Inputs already correct are retained. Never resume from an unrelated candidate's
state or prepared tree. The automated command refuses an existing work
directory; lower-level scripts require explicit config/source/state/build
paths for any deliberate recovery. The build name and pin are immutable.

You can inspect the workflow without building:

```sh
nix run .#build-from-source -- --work-dir "$HOME/builds/se2-example" --dry-run
```

The wrapper supplies Nix host tools and orchestrates the existing GE/Podman
workflow. It is not a pure sandboxed Nix derivation compiling all of Proton.
The prebuilt package and a wrapper around your own resulting archive both
integrate with `programs.steam.extraCompatPackages`.

If a future GE revision adds a download, record its origin, size and hash in
that NEW pin's contrib manifest and prefetch it before retrying. Do not allow
network access during compilation or change an existing pin to hide drift.
The `pic.zip` Piper input is branch-derived: its hash intentionally fails if
the upstream branch archive changes. The release cache preserves the exact
observed bytes. A supplied `--contrib-cache` uses the ordinary prefetcher's
original upstream URLs only for missing entries; use a complete verified
cache to avoid that branch-drift dependency.

The retained historical pin and patch files support regression controls;
they are not alternative defaults for SE2. The selected files are
`config/ge-proton11-9-se2.env` and `patches/series-ge-proton11-9-se2`.
`scripts/build-se1.sh` and the SE1 pin are kept so the `se1` tags stay
reproducible, but they predate the receipt requirement and no longer run
end-to-end with these scripts; build SE1 from its own tag.
