#!/usr/bin/env bash
# SPDX-License-Identifier: BSD-3-Clause
set -euo pipefail

usage() {
  printf '%s\n' \
    'Usage: build-se4-p6.sh --work-dir NEW_DIRECTORY --fresh-setup-receipt FILE' \
    '                    [--seed LOCAL_GE_REPO] [--contrib-cache DIRECTORY]' \
    '                    [--sdk-cache DIRECTORY] [--jobs 1..8] [--dry-run]' \
    '' \
    'Fetch/verify pinned inputs, prepare source, then build offline under Podman.' \
    'Use nix run .#build-from-source to supply host tools automatically.' \
    'The work directory must not exist. Nothing is installed into Steam.' \
    '' \
    'The pinned build requires a passing fresh Wine configure/makedep receipt for' \
    'the prepared source (see tests/wine-header-compile/README.md); this script' \
    'forwards it unchanged and does not create it. The SE4-P6 pin budgets 8 jobs' \
    '(Make 4 x Ninja 2); this script accepts no more than that.'
}

work_dir='' seed='' contrib_cache='' sdk_cache='' receipt='' jobs=8 dry_run=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --work-dir|--seed|--contrib-cache|--sdk-cache|--jobs|--fresh-setup-receipt)
      [[ $# -ge 2 && -n "$2" ]] || { usage >&2; exit 2; }
      case "$1" in
        --work-dir) work_dir="$2" ;;
        --seed) seed="$2" ;;
        --contrib-cache) contrib_cache="$2" ;;
        --sdk-cache) sdk_cache="$2" ;;
        --jobs) jobs="$2" ;;
        --fresh-setup-receipt) receipt="$2" ;;
      esac
      shift 2 ;;
    --dry-run) dry_run=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'Unknown option: %s\n' "$1" >&2; exit 2 ;;
  esac
done
[[ -n "$work_dir" ]] || { usage >&2; exit 2; }
[[ "$jobs" =~ ^[1-8]$ ]] || { printf 'Jobs must be 1..8.\n' >&2; exit 2; }
[[ ! -e "$work_dir" && ! -L "$work_dir" ]] || {
  printf 'Use a fresh, absent work directory; existing work is never overwritten.\n' >&2
  exit 1
}
work_dir="$(realpath -m -- "$work_dir")"
case "$work_dir" in *[[:space:]]*) printf 'Build paths cannot contain whitespace.\n' >&2; exit 2 ;; esac
kit="${SE4_P6_PROJECT_KIT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
kit="$(realpath -e -- "$kit")"
case "$work_dir/" in "$kit/"*)
  printf 'The work directory must be outside the source kit (avoid recursive copying).\n' >&2
  exit 2 ;;
esac
if [[ -n "$receipt" ]]; then receipt="$(realpath -e -- "$receipt")"; fi
if [[ -n "$seed" ]]; then seed="$(realpath -e -- "$seed")"; fi
if [[ -n "$contrib_cache" ]]; then contrib_cache="$(realpath -m -- "$contrib_cache")"; fi
if [[ -n "$sdk_cache" ]]; then sdk_cache="$(realpath -m -- "$sdk_cache")"; fi
if [[ "$dry_run" == 0 && -z "$receipt" ]]; then
  printf 'The fresh Wine setup receipt is required: --fresh-setup-receipt FILE.\n' >&2
  exit 2
fi
if [[ "$dry_run" == 1 ]]; then
  printf 'Fresh work: %s\nJobs: %s\n' "$work_dir" "$jobs"
  printf '%s\n' 'Copy source kit; verify pin; fetch or seed GE and submodules;' \
    'prepare patches; prefetch 16 hashed inputs; verify SDK image and static gates;' \
    'build redist with network=none and shared lock; verify artifact; do not install.'
  exit 0
fi

mkdir -p -- "$(dirname "$work_dir")"
mkdir -- "$work_dir"
project="$work_dir/project"
mkdir -- "$project"
# A Nix store input lacks Git administration. Make a fresh local index for
# source/preflight checks; never alter the caller's repository or history.
tar -C "$kit" --exclude='./.git' --exclude='./result*' -cf - . | tar -C "$project" -xf -
chmod -R u+w "$project"
git -C "$project" init -q
git -C "$project" add .
cd "$project"
source scripts/pinned-ge-common.sh
PINNED_GE_CONFIG="$project/config/ge-proton11-12-se4-p6.env"
pinned_ge_load_config
series="$project/patches/series-ge-proton11-12-se4-p6"
source_dir="$work_dir/source"
state_dir="$work_dir/state"
build_dir="$work_dir/build"
# No build-inputs bundle exists for this development candidate: every input in
# the pinned contrib manifest is fetched and hash-checked individually.
contrib_cache="${contrib_cache:-$work_dir/contrib-cache}"
sdk_cache="${sdk_cache:-$work_dir/sdk-cache}"
export GIT_NO_LAZY_FETCH=1

if [[ -z "$seed" ]]; then
  seed="$work_dir/upstream-seed"
  git -c maintenance.auto=false clone --depth 1 --single-branch \
    --branch "${PIN_SOURCE_REF#refs/tags/}" "$PIN_SOURCE_URL" "$seed"
fi
scripts/bootstrap-pinned-ge.sh --config "$PINNED_GE_CONFIG" \
  --source "$source_dir" --seed "$seed"
scripts/materialize-pinned-ge-submodules.sh --config "$PINNED_GE_CONFIG" \
  --source "$source_dir" --reference-source "$seed" --fetch
scripts/prepare-pinned-ge-source.sh --config "$PINNED_GE_CONFIG" \
  --source "$source_dir" --state-dir "$state_dir" --series "$series"
scripts/prefetch-pinned-ge-contrib.sh --config "$PINNED_GE_CONFIG" \
  --source "$source_dir" --cache-dir "$contrib_cache"

# Match the build wrapper's isolated XDG storage, without changing host
# container settings. The pinned image is fetched only in this input phase.
mkdir -p "$sdk_cache/.config" "$sdk_cache/.local/share" "$sdk_cache/.cache"
sdk_env=(env "XDG_CONFIG_HOME=$sdk_cache/.config"
  "XDG_DATA_HOME=$sdk_cache/.local/share" "XDG_CACHE_HOME=$sdk_cache/.cache")
if ! "${sdk_env[@]}" podman image exists "$PIN_STEAMRT_IMAGE"; then
  "${sdk_env[@]}" podman pull "$PIN_STEAMRT_IMAGE"
fi
actual_image="$("${sdk_env[@]}" podman image inspect --format '{{.Id}}' "$PIN_STEAMRT_IMAGE")"
[[ "${actual_image#sha256:}" == "$PIN_STEAMRT_IMAGE_ID" ]] || {
  printf 'SDK image identity differs from the pin; refusing the build.\n' >&2
  exit 1
}
PREPARED_SOURCE="$source_dir" PREPARED_STATE="$state_dir" scripts/verify-preparation.sh \
  --config "$PINNED_GE_CONFIG" --series "$series"
scripts/build-pinned-ge.sh --config "$PINNED_GE_CONFIG" --series "$series" \
  --source "$source_dir" --state-dir "$state_dir" --build-dir "$build_dir" \
  --cache-home "$sdk_cache" --jobs "$jobs" \
  --fresh-setup-receipt "$receipt"
printf 'Verified local build: %s/%s.tar.gz\nNothing installed into Steam.\n' \
  "$build_dir" "$PIN_BUILD_NAME"

# SE4-P6 development candidate: GE-Proton11-12 + the 36-patch Wine series
# (patches/ge-proton11-12-se4-p6/) + the pinned FFmpeg modules. Not a release.
# Build name: proton-ge-11-12-rtsp-se4-p6 (from the pin). PACKAGE_RELEASE stays 0.
