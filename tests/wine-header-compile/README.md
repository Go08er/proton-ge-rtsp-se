# Real-header pre-build compilation gate

Required before requesting a full Proton build for a candidate that changes
product C code. Extracted/stubbed unit tests and patch application cannot
satisfy this gate. Compile every C object in each touched Wine module, with
the actual configured flags and real headers, for x86_64 and i386.

`run.py` reads the retained generated Makefile rules and asks `make -n` for
each exact compiler invocation. It executes the C compiles **unconditionally**
(an old object cannot make this pass), then preprocesses with the same flags
to inventory public/private WineDMO flag domains. It never invokes `redist`,
installs, runs Wine, or fetches anything. This is C-object compilation, not
module linking, a complete Proton artifact, or runtime qualification.

## Fresh generation is required before a full build

`fresh_setup.py` complements `run.py`: reused Makefiles cannot prove that a
new header is registered with Wine's makedep. The P19b failure demonstrated
that gap. The fresh gate uses retained `config.log` files **only as configure
argv templates**; no configured object directory, cache, generated Makefile
or old consumer object is reused.

The host prepares an owned scratch dependency root containing the exact
candidate `src-wine`, mounts the prepared candidate read-only, and supplies
`identity.json` with `pin_id`, `series_digest`, `steamrt_image_id`,
`source_hash` (prepared normalized-tar digest), `compiled_source_hash`, the
preserved host `compiled_source_path`, and `generated_source_changes`. GE
generates configure, Vulkan and a few spec/
syscall files before Wine configuration; the two source digests need not be
equal. Each bridge entry is a relative path mapped to `prepared_sha256`
(null for a newly generated file) and `compiled_sha256`. The helper checks
both complete source digests and the complete file/symlink/mode diff, allowing
only its explicit 14 GE-generated paths. Do not carry old caches or backup
files into that bridge, or copy a different candidate's C/header changes.

Inside the same pinned, offline SDK, with the shared lock held and a bounded
CPU/job budget, run the following against **fresh paths**. The host identity
keeps the preserved source path; the receipt separately records the SDK mount
as `container_source_path`. This helper does not acquire the lock or launch Podman:

```sh
python3 -B /gate/fresh_setup.py \
  --scratch-root /scratch \
  --prepared-source /prepared-wine \
  --config-log-x86_64 /argv/x86_64-config.log \
  --config-log-i386 /argv/i386-config.log \
  --identity /identity.json --output /evidence/FRESH-RUN --jobs 4
```

It creates four empty `/scratch/fresh-{red,green}-{x86_64,i386}` directories.
The red control removes **only** `wine/mforigin.h` from the copied include
inventory, and must fail specifically at makedep's missing-header error on
both architectures. Green restores the registration and freshly configures
both. Green x86_64 configuration supplies the new native makedep needed for
i386 configuration. All C object targets in mfreadwrite, winedmo, mfsrcsnk,
mfmp4srcsnk and mfasfsrcsnk are then enumerated from the new Makefiles and
built with their ordinary generated-header/tool prerequisites. No Proton or
default Wine target is invoked. Timeout defaults are 600 seconds per configure
and 1,200 seconds per architecture's compile; the host also bounds the whole
job. A timed-out or signal-killed configure cannot satisfy the red control.

`results.json` binds the pin, series, SDK, both source identities, complete
bridge, all six stage exits, generated configuration hashes and every consumer
object hash. Each stage retains its literal argv, local log and exit receipt.
The copied inventory is restored even on failure, and the full compiled-source
digest must still match. Success is configuration/C-compilation evidence only;
it is not linking, full-build or playback qualification. Retain failed output;
use another fresh scratch/output pair for a later authorized attempt.

Pure helper checks (no configure, compiler, container or Wine):

```sh
python3 -B tests/wine-header-compile/test_fresh_setup.py
python3 -B tests/wine-header-compile/test_gate.py
```

## Retained-Makefile component setup (additional gate, not fresh generation)

Use a fresh reflink/copy of a retained configured build. Apply the candidate
source delta only to its copied `src-wine`, and verify those C/header bytes
against the separately replayed candidate. Do not edit the original build,
source, pin or configuration. A retained configuration is suitable only when
its SDK, architecture flags and dependencies still match the candidate;
otherwise prepare a fresh component configuration and record that difference.

Run from the project's local Nix build-tools environment. Set these explicit
values for the chosen baseline/candidate (never a historical default):

```sh
gate_origin_build=/tmp/rtsp-ge11-se2p16-1
gate_copy="$PWD/work/se2-p17-analysis/compile-build"
gate_output="$PWD/work/se2-p17-analysis/compiler-results"
gate_cache="$PWD/work/podman-home-a314"
gate_image=01f74089b0ffb6fc127eadca189776ab56461515ba575ff1bfbd66a39d3f753b
```

P17's copy and receipts **already exist**; don't overwrite them. For a future
run choose new copy/output paths, copy with `cp -a --reflink=always`, then
apply and verify the new source delta. Mount that copy at the *original path
inside the container*, so absolute paths in the retained Makefile resolve to
the copy. No original build is mounted. The output child must be fresh:

```sh
flock --exclusive --nonblock "$HOME/Documents/.proton-build.lock" \
  env XDG_DATA_HOME="$gate_cache/.local/share" \
      XDG_CONFIG_HOME="$gate_cache/.config" \
      XDG_CACHE_HOME="$gate_cache/.cache" \
  nice -n 10 podman run --rm --pull=never --network=none --cpus=4 \
    -e CCACHE_DISABLE=1 -e WINEDEBUG=-all -e PACKAGE_RELEASE=0 \
    --mount "type=bind,src=$gate_copy,dst=$gate_origin_build" \
    --mount "type=bind,src=$PWD/tests/wine-header-compile,dst=/gate,ro" \
    --mount "type=bind,src=$gate_output,dst=/evidence" \
    "$gate_image" python3 -B /gate/run.py \
      --build-copy "$gate_origin_build" --module dlls/winedmo \
      --output /evidence/FRESH-RUN
```

The lock path above is this workspace's shared build lock, not a new lock.
Repeat `--module` for every other touched module. Resource limits do not
authorize a full build. Review each module's object count, both architectures,
the source/configuration hashes, command JSON and exit codes in `results.json`.
`sees_both=true` reports actual header exposure; it is not automatically a
semantic failure or proof of a wrong flag use. Inspect the consumers.

Before trusting the gate, P17 work ran `--negative` against the unmodified
P16 copy: both `main.c` compiles reproduce the exact macro/enum collision.
That option checks only the two negative controls, never qualifies a candidate.
After the narrow repair, all 50 WineDMO C objects compiled. See the
[P17 result](../../docs/SE2_P17_HEADER_REPAIR_20260923.md).

### Component-only runtime iteration

After the object gate passes, the standard pre-build iteration is to link
only the touched DLLs using the exact generated Makefile command (retain
that command and the linker result), then swap them into a **disposable**
copy of the baseline tool. Keep both architectures' DLL hashes, the source
postimage hash and the untouched Wine executable hash with every receipt.
Verify replacement hashes before running: a directory named after P18 is
not evidence that the experimental DLL was installed successfully.

Run the prior-failing control on the immutable baseline and the disposable
copy with the same sealed input and oracle. Retain failures, including
setup/mislabelled experiments; exclude them explicitly rather than relabeling
them. Compile/link success on i386 is not i386 runtime qualification. Use
the same shared lock, cached SDK, network isolation and resource limits as
the object gate. No full build, install or publication is implied.

Helper parser self-tests (no compiler, container or game):

```sh
python3 -B tests/wine-header-compile/test_gate.py
```
