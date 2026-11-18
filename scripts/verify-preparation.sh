#!/usr/bin/env bash
# SPDX-License-Identifier: BSD-3-Clause
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_DIR="${SOURCE_DIR:-$ROOT_DIR/sources/ge-proton11}"
PATCH_SERIES="$ROOT_DIR/patches/series"
WOW64_PROBE="$ROOT_DIR/patches/candidates/0001-winedmo-use-destroy-params-for-wow64-demuxer.patch"
PROTON_LAUNCHER_PATCH="$ROOT_DIR/patches/proton/0001-launcher-add-scoped-xrizer-mode.patch"
# shellcheck source=pinned-ge-common.sh
source "$ROOT_DIR/scripts/pinned-ge-common.sh"

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<'EOF'
Usage: verify-preparation.sh [--config FILE] [--series FILE]

Run the static preparation, safety, and model gates. The default remains the
immutable A3.12 control; pass the candidate config explicitly when qualifying
a candidate. Historical pins can select their archived patch series explicitly.
Set PREPARED_SOURCE explicitly to also check the selected candidate's Wine source
contracts; this does not substitute for complete preparation provenance.
For P8, PREPARATION_TEST_CC can name an available native C compiler command
for extracted master lifecycle controls (otherwise an available cc is used).
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --config)
      [[ $# -ge 2 && -n "$2" ]] || { usage >&2; exit 2; }
      PINNED_GE_CONFIG="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --series)
      [[ $# -ge 2 && -n "$2" ]] || { usage >&2; exit 2; }
      PATCH_SERIES="$2"
      shift 2
      ;;
    *)
      printf 'ERROR: unknown option: %s\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

PROJECT_HOME_PATTERN='(?<![A-Za-z0-9._~-])(?:/home/(?!runner/work/llvm-mingw(?:/|[^A-Za-z0-9._-]|$))[^ /]+|/Users/[^ /]+)'

mapfile -t SHELL_FILES < <(
  find "$ROOT_DIR/scripts" "$ROOT_DIR/tests/media" "$ROOT_DIR/tests/tooling" \
    "$ROOT_DIR/tests/media-engine-pause-scrub" \
    -maxdepth 1 \
    -type f -name '*.sh' -print | LC_ALL=C sort
)
[[ ${#SHELL_FILES[@]} -gt 0 ]] || fail "no shell files found"
bash -n "${SHELL_FILES[@]}"
bash -n "$ROOT_DIR"/config/*.env

if command -v shellcheck >/dev/null 2>&1; then
  # Config variables are consumed through strict indirect lookup in the shared
  # helper, which ShellCheck cannot model (SC2034). Follow that helper and keep
  # every other warning/error fatal.
  shellcheck -x -P "$ROOT_DIR/scripts" --severity=warning -e SC2034 \
    "$ROOT_DIR"/scripts/*.sh
  (
    cd "$ROOT_DIR/tests/media"
    shellcheck -x ./*.sh
  )
  (
    cd "$ROOT_DIR/tests/tooling"
    shellcheck -x ./*.sh
  )
  (
    cd "$ROOT_DIR/tests/media-engine-pause-scrub"
    shellcheck -x ./run_runtime_probe.sh ./test_runner_guards.sh
  )
else
  printf 'NOTE: shellcheck is unavailable outside the project Nix shell.\n'
fi

if command -v nix-instantiate >/dev/null 2>&1; then
  nix-instantiate --parse "$ROOT_DIR/shell.nix" >/dev/null
fi

"$ROOT_DIR/scripts/check-ge-release.sh" --help >/dev/null
"$ROOT_DIR/scripts/record-release-manifest.sh" --help >/dev/null
"$ROOT_DIR/scripts/materialize-ge-wine.sh" --help >/dev/null
"$ROOT_DIR/scripts/audit-patched-wine.sh" --help >/dev/null
"$ROOT_DIR/scripts/audit-ffmpeg-source.sh" --help >/dev/null
"$ROOT_DIR/scripts/apply-pinned-ffmpeg-security-series.sh" --help >/dev/null
"$ROOT_DIR/scripts/verify-artifact-archive.py" --help >/dev/null
"$ROOT_DIR/scripts/hash-source-tree.sh" --help >/dev/null
bash "$ROOT_DIR/scripts/bootstrap-pinned-ge.sh" --help >/dev/null
bash "$ROOT_DIR/scripts/materialize-pinned-ge-submodules.sh" --help >/dev/null
bash "$ROOT_DIR/scripts/prefetch-pinned-ge-contrib.sh" --help >/dev/null
bash "$ROOT_DIR/scripts/prepare-pinned-ge-source.sh" --help >/dev/null
bash "$ROOT_DIR/scripts/build-pinned-ge.sh" --help >/dev/null
bash "$ROOT_DIR/scripts/record-pinned-ge-resume-state.sh" --help >/dev/null
bash "$ROOT_DIR/scripts/verify-pinned-ge-artifact.sh" --help >/dev/null
for offline_object_probe in \
    bootstrap-sources.sh \
    materialize-ge-wine.sh \
    verify-baseline.sh \
    verify-research-snapshot.sh; do
  rg -Fq 'export GIT_NO_LAZY_FETCH=1' \
    "$ROOT_DIR/scripts/$offline_object_probe" \
    || fail "$offline_object_probe permits an implicit promisor fetch"
done
for bootstrap_gate in \
    'cat-file -e "$PIN_SOURCE_TREE^{tree}"' \
    'local clone omitted the pinned GE tree object' \
    '[[ ! -L "$SOURCE_DIR" ]]' \
    'pinned_ge_require_absent_path "pinned GE source destination" "$SOURCE_DIR"' \
    'mkdir -- "$SOURCE_DIR"' \
    'if [[ "$status" != 0 && "$CREATED_SOURCE" == 1 ]]'; do
  rg -Fq "$bootstrap_gate" "$ROOT_DIR/scripts/bootstrap-pinned-ge.sh" \
    || fail "offline bootstrap omits fail-closed object gate: $bootstrap_gate"
done
for materializer_gate in \
    'REFERENCE_SOURCES+=("$2")' \
    'pinned_ge_find_complete_reference_repo' \
    'pinned_ge_require_existing_submodule' \
    'GIT_NO_LAZY_FETCH=1' \
    'clone --local --no-hardlinks --no-checkout' \
    'Surviving Git alternates files: 0'; do
  rg -Fq "$materializer_gate" \
    "$ROOT_DIR/scripts/materialize-pinned-ge-submodules.sh" \
    || fail "submodule materializer omits local-reference gate: $materializer_gate"
done

if [[ -d "$SOURCE_DIR/wine/.git" || -f "$SOURCE_DIR/wine/.git" ]]; then
  if git -C "$SOURCE_DIR/wine" apply --check "$WOW64_PROBE"; then
    printf 'WOW64 teardown defect remains present in the local Wine research source; Alpha patch 3 carries the correction.\n'
  elif sed -n '/static NTSTATUS wow64_demuxer_destroy/,/^}/p' \
      "$SOURCE_DIR/wine/dlls/winedmo/unixlib.c" \
      | rg -q 'struct demuxer_destroy_params'; then
    printf 'WOW64 teardown correction is already implemented by the local Wine source.\n'
  else
    fail "WOW64 teardown probe neither applies nor finds an upstream correction"
  fi
else
  printf 'NOTE: Wine source is unavailable; WOW64 teardown probe skipped.\n'
fi

if [[ -e "$SOURCE_DIR/ffmpeg/.git" ]]; then
  "$ROOT_DIR/scripts/audit-ffmpeg-source.sh" --source "$SOURCE_DIR" >/dev/null
else
  printf 'NOTE: FFmpeg source is unavailable; source dependency audit skipped.\n'
fi

pinned_ge_load_config
[[ "$PIN_SCHEMA_VERSION" == 5 ]] \
  || fail "selected security-refresh build does not use pin schema 5"
[[ "$PINNED_GE_HAS_RETAINED_RESUME" == 0 ]] \
  || fail "fresh selected pin carries misleading old-base resume provenance"
selected_module_series=()
case "$PIN_ID" in
  ge-master-snapshot-20260723-a312)
    SELECTED_PROFILE=a312
    [[ "$PIN_BUILD_NAME" \
        == Proton-RTSP-on-GE11-A3.12-NetworkError-bb1caad3 \
        && "$PIN_KIND" == development-snapshot \
        && "$PIN_SOURCE_REF" \
          == bb1caad333b08cf87d49d0f794a538502d992eae \
        && "$PIN_SOURCE_COMMIT" \
          == bb1caad333b08cf87d49d0f794a538502d992eae \
        && "$PIN_SOURCE_TREE" \
          == 818b5a31bfa063e860f6817a1c1ac3ff55316c02 \
        && "$PIN_WINE_COMMIT" \
          == fc39a66977983a16a31318f98386386ec2dd6b55 \
        && "$PINNED_GE_HAS_PATCH_OVERLAP" == 1 ]] \
      || fail "immutable A3.12 control identity changed"
    patch_overlap_manifest="$(pinned_ge_patch_overlap_manifest_path)"
    [[ "$(pinned_ge_patch_overlap_records \
        "$patch_overlap_manifest" | wc -l)" == 2 ]] \
      || fail "A3.12 GE patch-overlap manifest is not the reviewed pair"
    ;;
  ge-proton11-3-a314)
    SELECTED_PROFILE=a314
    [[ "$PIN_BUILD_NAME" \
        == Proton-RTSP-on-GE11-A3.14-GE-Proton11-3-8c8003f7 \
        && "$PIN_KIND" == release-tag \
        && "$PIN_SOURCE_REF" == refs/tags/GE-Proton11-3 \
        && "$PIN_SOURCE_COMMIT" \
          == 8c8003f7f5473d883fbe1bc7ac070c79955754e8 \
        && "$PIN_SOURCE_TREE" \
          == 1e55008bb5995b5cfaf2643e6ce1c44f4e11e208 \
        && "$PIN_WINE_COMMIT" \
          == 9578fa3613f3379179b576968bc77c8161ab6ea8 \
        && "$PIN_FFMPEG_CRYPTO_BUILD_MAKEFILE_BLOB" \
          == bfb3c4316dc348e93e5571c822a634ce98f5ac6c \
        && "$PINNED_GE_HAS_PATCH_OVERLAP" == 0 ]] \
      || fail "immutable A3.14 GE-Proton11-3 identity changed"
    ;;
  ge-proton11-3-a315)
    SELECTED_PROFILE=a315
    [[ "$PIN_BUILD_NAME" \
        == Proton-RTSP-on-GE11-A3.15-GE-Proton11-3-dabf93db \
        && "$PIN_KIND" == release-tag \
        && "$PIN_SOURCE_REF" == refs/tags/GE-Proton11-3 \
        && "$PIN_SOURCE_COMMIT" \
          == 8c8003f7f5473d883fbe1bc7ac070c79955754e8 \
        && "$PIN_SOURCE_TREE" \
          == 1e55008bb5995b5cfaf2643e6ce1c44f4e11e208 \
        && "$PIN_WINE_COMMIT" \
          == 9578fa3613f3379179b576968bc77c8161ab6ea8 \
        && "$PIN_FFMPEG_CRYPTO_BUILD_MAKEFILE_BLOB" \
          == bfb3c4316dc348e93e5571c822a634ce98f5ac6c \
        && "$PINNED_GE_HAS_PATCH_OVERLAP" == 0 ]] \
      || fail "immutable A3.15 GE-Proton11-3 identity changed"
    ;;
  ge-proton11-3-a316)
    SELECTED_PROFILE=a316
    [[ "$PIN_BUILD_NAME" \
        == Proton-RTSP-on-GE11-A3.16-GE-Proton11-3-3d49c777 \
        && "$PIN_KIND" == release-tag \
        && "$PIN_SOURCE_REF" == refs/tags/GE-Proton11-3 \
        && "$PIN_SOURCE_COMMIT" \
          == 8c8003f7f5473d883fbe1bc7ac070c79955754e8 \
        && "$PIN_SOURCE_TREE" \
          == 1e55008bb5995b5cfaf2643e6ce1c44f4e11e208 \
        && "$PIN_WINE_COMMIT" \
          == 9578fa3613f3379179b576968bc77c8161ab6ea8 \
        && "$PIN_FFMPEG_CRYPTO_BUILD_MAKEFILE_BLOB" \
          == bfb3c4316dc348e93e5571c822a634ce98f5ac6c \
        && "$PINNED_GE_HAS_PATCH_OVERLAP" == 0 ]] \
      || fail "immutable A3.16 GE-Proton11-3 identity changed"
    ;;
  ge-proton11-6-a319)
    SELECTED_PROFILE=a319
    [[ "$PIN_BUILD_NAME" \
        == Proton-RTSP-on-GE11-A3.19-GE-Proton11-6-7e88ceff \
        && "$PIN_KIND" == release-tag \
        && "$PIN_SOURCE_REF" == refs/tags/GE-Proton11-6 \
        && "$PIN_SOURCE_COMMIT" \
          == 7e88cefffc122ea1584c2156b8d7bae6cf69b2a7 \
        && "$PIN_SOURCE_TREE" \
          == 851680369dc46489360e4f67bfa3acc6b701ef4a \
        && "$PIN_WINE_COMMIT" \
          == 9358696fe9a2261329f4a83aa6a65fd436106154 \
        && "$PIN_FFMPEG_CRYPTO_BUILD_MAKEFILE_BLOB" \
          == 284157f8120d27f8bb7291acf662e799cddf717b \
        && "$PINNED_GE_HAS_PATCH_OVERLAP" == 0 ]] \
      || fail "immutable A3.19 GE-Proton11-6 identity changed"
    ;;
  ge-proton11-6-a320|ge-proton11-6-a321|ge-proton11-6-a322|ge-proton11-6-a322-r2|ge-proton11-6-a323|ge-proton11-6-se1|ge-proton11-6-se2-p1|ge-proton11-6-se2-p2|ge-proton11-6-se2-p3|ge-proton11-6-se2-p4|ge-proton11-6-se2-p5|ge-proton11-6-se2-p6|ge-proton11-6-se2-p7)
    SELECTED_PROFILE=${PIN_ID##*-}
    candidate_number=${SELECTED_PROFILE#a3}
    if [[ "$PIN_ID" == ge-proton11-6-a322-r2 ]]; then
      SELECTED_PROFILE=a322
      candidate_number=22-R2
    fi
    expected_build_name="Proton-RTSP-on-GE11-A3.$candidate_number-GE-Proton11-6-7e88ceff"
    if [[ "$PIN_ID" == ge-proton11-6-se1 ]]; then
      # SE1 retains the exact A3.23 Wine series; only launcher policy changes.
      SELECTED_PROFILE=a323
      expected_build_name=proton-ge-11-6-rtsp-se1
      [[ "$PIN_PROTON_LAUNCHER_POLICY" == upstream ]] \
        || fail "SE1 must use the unmodified upstream launcher"
    elif [[ "$PIN_ID" == ge-proton11-6-se2-p1 || "$PIN_ID" == ge-proton11-6-se2-p2 || "$PIN_ID" == ge-proton11-6-se2-p3 || "$PIN_ID" == ge-proton11-6-se2-p4 || "$PIN_ID" == ge-proton11-6-se2-p5 || "$PIN_ID" == ge-proton11-6-se2-p6 || "$PIN_ID" == ge-proton11-6-se2-p7 ]]; then
      # These subsets retain the foundation gates and exact ordered additions.
      SELECTED_PROFILE=a323
      expected_build_name="proton-ge-11-6-rtsp-se2-${PIN_ID##*-}"
      selected_module_series=(
        proposed/0027-winedmo-expose-vp8-and-hevc-decoders.patch
        proposed/0028-winedmo-bound-published-stream-access.patch
        proposed/0030-winedmo-check-filter-initialization-failures.patch
      )
      if [[ "$PIN_ID" == ge-proton11-6-se2-p2 || "$PIN_ID" == ge-proton11-6-se2-p3 || "$PIN_ID" == ge-proton11-6-se2-p4 || "$PIN_ID" == ge-proton11-6-se2-p5 || "$PIN_ID" == ge-proton11-6-se2-p6 || "$PIN_ID" == ge-proton11-6-se2-p7 ]]; then
        selected_module_series+=(
          proposed/0037-winedmo-discard-resampler-delay-on-flush.patch
          proposed/0038-winedmo-describe-filter-eof-failures.patch
        )
      fi
      if [[ "$PIN_ID" == ge-proton11-6-se2-p3 || "$PIN_ID" == ge-proton11-6-se2-p4 || "$PIN_ID" == ge-proton11-6-se2-p5 || "$PIN_ID" == ge-proton11-6-se2-p6 || "$PIN_ID" == ge-proton11-6-se2-p7 ]]; then
        selected_module_series+=(proposed/0039-mf-report-terminal-direct-filter-errors.patch)
      fi
      if [[ "$PIN_ID" == ge-proton11-6-se2-p4 || "$PIN_ID" == ge-proton11-6-se2-p5 || "$PIN_ID" == ge-proton11-6-se2-p6 || "$PIN_ID" == ge-proton11-6-se2-p7 ]]; then
        selected_module_series+=(proposed/0040-mfmediaengine-remove-uninitialized-topology-cleanup.patch)
      fi
      if [[ "$PIN_ID" == ge-proton11-6-se2-p5 || "$PIN_ID" == ge-proton11-6-se2-p6 || "$PIN_ID" == ge-proton11-6-se2-p7 ]]; then
        selected_module_series+=(
          proposed/0029-winedmo-latch-asf-startup-timestamp-decision.patch
          proposed/0031-winedmo-open-secure-rtsp-tcp-aliases.patch
          proposed/0032-winedmo-classify-http-media-after-probing.patch
          proposed/0033-winedmo-bound-and-extend-audio-channel-counts.patch
          proposed/0034-mfmediaengine-honor-ready-source-autoplay.patch
          proposed/0036-mfmediaengine-guard-audio-only-segment-end.patch
          proposed/0041-winedmo-allow-supported-hls-audio-containers.patch
        )
        [[ "${PIN_FFMPEG_RTSPS_PATCH_SHA256:-}" == 4620be1a6b9fae9b1c386ee17b8ef7e2f6f30a20ca32c7fd9534ef0822ec9f25 \
            && "${PIN_FFMPEG_RTSPS_RTSP_BLOB:-}" == f2927f4a4bf14239c83a63e923e077e4dd68ad47 ]] \
          || fail "SE2-P5 secure RTSP Wine module requires its exact FFmpeg companion"
        pinned_ge_rtsps_transport_patch >/dev/null
      elif [[ -n "${PIN_FFMPEG_RTSPS_PATCH_SHA256:-}${PIN_FFMPEG_RTSPS_RTSP_BLOB:-}" ]]; then
        fail "historical SE2 subsets do not include the secure RTSP companion"
      fi
      if [[ "$PIN_ID" == ge-proton11-6-se2-p6 || "$PIN_ID" == ge-proton11-6-se2-p7 ]]; then
        selected_module_series+=(proposed/0042-winedmo-expose-existing-flac-audio-decoder.patch)
        [[ "${PIN_FFMPEG_HTTP_SEEK_PATCH_SHA256:-}" == b3669b91b08502e943bd564f3a99bef50d2d54440f8f4cc189e2b0d3b2b14ecb \
            && "${PIN_FFMPEG_HTTP_SEEK_HTTP_BLOB:-}" == 03dba285f93c762073e6a923be80ae3cca016226 ]] \
          || fail "SE2-P6 requires its exact HTTP seek companion"
        pinned_ge_http_seek_patch >/dev/null
      elif [[ -n "${PIN_FFMPEG_HTTP_SEEK_PATCH_SHA256:-}${PIN_FFMPEG_HTTP_SEEK_HTTP_BLOB:-}" ]]; then
        fail "historical SE2 subsets do not include the HTTP seek companion"
      fi
      if [[ "$PIN_ID" == ge-proton11-6-se2-p7 ]]; then
        selected_module_series+=(
          proposed/0043-mf-rearm-audio-sample-demand-after-flush.patch
          proposed/0044-mf-initialize-sar-marker-entry-before-copy.patch
          proposed/0045-mf-reset-seek-eos-and-discriminate-sink-markers.patch
        )
      fi
      [[ "$PIN_PROTON_LAUNCHER_POLICY" == upstream \
          && "$PIN_WITHOUT_NVIDIA_LIBS" == 0 && "$PIN_WITHOUT_VKLAYERS" == 0 \
          && "$PIN_REGISTERED_SUBMODULE_COUNT" == 42 \
          && "$PIN_GITLINK_COUNT" == 42 \
          && "$PIN_UNMAPPED_OPTIONAL_GITLINK_COUNT" == 0 \
          && "${PIN_FFMPEG_DAV1D_PATCH_SHA256:-}" \
            == fc0e7fccb6862c463fc92487cc8d79c7ccc242cb84c4811712f42c8a863a2c8c \
          && "${PIN_FFMPEG_DAV1D_MAKEFILE_BLOB:-}" \
            == b0363a2bc898363dbe368e966248cad3738d2acc ]] \
        || fail "SE2-P1 full-GE component or separate AV1 module identity changed"
      pinned_ge_dav1d_build_patch >/dev/null
    fi
    [[ "$PIN_BUILD_NAME" \
        == "$expected_build_name" \
        && "$PIN_KIND" == release-tag \
        && "$PIN_SOURCE_REF" == refs/tags/GE-Proton11-6 \
        && "$PIN_SOURCE_COMMIT" \
          == 7e88cefffc122ea1584c2156b8d7bae6cf69b2a7 \
        && "$PIN_SOURCE_TREE" \
          == 851680369dc46489360e4f67bfa3acc6b701ef4a \
        && "$PIN_WINE_COMMIT" \
          == 9358696fe9a2261329f4a83aa6a65fd436106154 \
        && "$PIN_FFMPEG_CRYPTO_BUILD_MAKEFILE_BLOB" \
          == 284157f8120d27f8bb7291acf662e799cddf717b \
        && "$PINNED_GE_HAS_PATCH_OVERLAP" == 0 ]] \
      || fail "$SELECTED_PROFILE GE-Proton11-6 candidate identity changed"
    ;;
  ge-master-20260913-se2-p8|ge-master-20260913-se2-p9|ge-master-20260913-se2-p10|ge-master-20260913-se2-p11|ge-master-20260913-se2-p12|ge-master-20260913-se2-p13|ge-proton11-7-se2-p14|ge-proton11-7-se2-p15|ge-proton11-7-se2-p16|ge-proton11-7-se2-p17|ge-proton11-7-se2-p18|ge-proton11-7-se2-p19a|ge-proton11-7-se2-p19b|ge-proton11-7-se2-p19b2)
    # Reuse the A3.23 foundation gates; bind each base independently while
    # sharing the unchanged module contracts and full-GE component policy.
    SELECTED_PROFILE=a323
    [[ "$PIN_ID" != ge-proton11-7-se2-p19b && "$PIN_ID" != ge-proton11-7-se2-p19b2 ]] || SELECTED_PROFILE=p19b
    expected_se2_submodules=42
    expected_se2_dav1d_postimage=d928598c149e70b3af85f4d83d0012f28f6104b6
    if [[ "$PIN_ID" == ge-proton11-7-se2-p14 || "$PIN_ID" == ge-proton11-7-se2-p15 || "$PIN_ID" == ge-proton11-7-se2-p16 || "$PIN_ID" == ge-proton11-7-se2-p17 || "$PIN_ID" == ge-proton11-7-se2-p18 || "$PIN_ID" == ge-proton11-7-se2-p19a || "$PIN_ID" == ge-proton11-7-se2-p19b || "$PIN_ID" == ge-proton11-7-se2-p19b2 ]]; then
      expected_se2_submodules=43
      expected_se2_dav1d_postimage=8da60c649bcbf3c2c86c042c95551883e5dab64f
      [[ "$PIN_BUILD_NAME" == "proton-ge-11-7-rtsp-se2-${PIN_ID##*-}" \
          && "$PIN_KIND" == release-tag \
          && "$PIN_SOURCE_REF" == refs/tags/GE-Proton11-7 \
          && "$PIN_SOURCE_COMMIT" == c191f35dcebbeccfacd3b4c6f6eea026e588c1c2 \
          && "$PIN_SOURCE_TREE" == 9ce007c8526d8c04d0face13dacff1612ff23c8b \
          && "$PIN_WINE_COMMIT" == 46b29104e3741fe23bf5e2547196a253aab88c89 \
          && "$PIN_FFMPEG_CRYPTO_BUILD_MAKEFILE_BLOB" == c7aab44f326494a1c67f67bdda65b2245fc94b6d \
          && "$PINNED_GE_HAS_PATCH_OVERLAP" == 0 ]] \
        || fail "SE2-P14 GE-Proton11-7 identity or crypto postimage changed"
    else
      [[ "$PIN_BUILD_NAME" == "proton-ge-master-0b8c4d30-rtsp-se2-${PIN_ID##*-}" \
          && "$PIN_KIND" == development-snapshot \
          && "$PIN_SOURCE_REF" == 0b8c4d30d76abb74cc5cc4efdbadb410db00455f \
          && "$PIN_SOURCE_COMMIT" == 0b8c4d30d76abb74cc5cc4efdbadb410db00455f \
          && "$PIN_SOURCE_TREE" == ea31809f040dae7144160fbf08727d4a0979503e \
          && "$PIN_WINE_COMMIT" == 00e639898e01f8dd6fbee3851bd4c1e412c5b875 \
          && "$PIN_FFMPEG_CRYPTO_BUILD_MAKEFILE_BLOB" == 50af7a37bc7f97c3d8ba6cb560f529f7ec148199 \
          && "$PINNED_GE_HAS_PATCH_OVERLAP" == 0 ]] \
        || fail "SE2-P8 frozen GE master identity or crypto postimage changed"
    fi
    [[ "$PIN_PROTON_LAUNCHER_POLICY" == upstream \
        && "$PIN_WITHOUT_NVIDIA_LIBS" == 0 && "$PIN_WITHOUT_VKLAYERS" == 0 \
        && "$PIN_REGISTERED_SUBMODULE_COUNT" == "$expected_se2_submodules" \
        && "$PIN_GITLINK_COUNT" == "$expected_se2_submodules" \
        && "$PIN_UNMAPPED_OPTIONAL_GITLINK_COUNT" == 0 \
        && "$PIN_STEAMRT_IMAGE" == registry.gitlab.steamos.cloud/proton/steamrt4/sdk/x86_64:4.0.20260714.251823-0 \
        && "$PIN_STEAMRT_IMAGE_ID" == 01f74089b0ffb6fc127eadca189776ab56461515ba575ff1bfbd66a39d3f753b ]] \
      || fail "SE2-P8 full-GE components, launcher or retained SDK identity changed"
    [[ "${PIN_FFMPEG_DAV1D_PATCH_SHA256:-}" == fc0e7fccb6862c463fc92487cc8d79c7ccc242cb84c4811712f42c8a863a2c8c \
        && "${PIN_FFMPEG_DAV1D_MAKEFILE_BLOB:-}" == "$expected_se2_dav1d_postimage" \
        && "${PIN_FFMPEG_RTSPS_PATCH_SHA256:-}" == 4620be1a6b9fae9b1c386ee17b8ef7e2f6f30a20ca32c7fd9534ef0822ec9f25 \
        && "${PIN_FFMPEG_RTSPS_RTSP_BLOB:-}" == f2927f4a4bf14239c83a63e923e077e4dd68ad47 \
        && "${PIN_FFMPEG_HTTP_SEEK_PATCH_SHA256:-}" == b3669b91b08502e943bd564f3a99bef50d2d54440f8f4cc189e2b0d3b2b14ecb \
        && "${PIN_FFMPEG_HTTP_SEEK_HTTP_BLOB:-}" == 03dba285f93c762073e6a923be80ae3cca016226 ]] \
      || fail "SE2-P8 requires its exact AV1, secure RTSP and HTTP seek companions"
    pinned_ge_dav1d_build_patch >/dev/null
    pinned_ge_rtsps_transport_patch >/dev/null
    pinned_ge_http_seek_patch >/dev/null
    selected_module_series=(
      proposed/0027-winedmo-expose-vp8-and-hevc-decoders.patch
      proposed/0028-winedmo-bound-published-stream-access.patch
      proposed/0030-winedmo-check-filter-initialization-failures.patch
      proposed/0037-winedmo-discard-resampler-delay-on-flush.patch
      proposed/0038-winedmo-describe-filter-eof-failures.patch
      proposed/0039-mf-report-terminal-direct-filter-errors.patch
      proposed/0040-mfmediaengine-remove-uninitialized-topology-cleanup.patch
      proposed/0029-winedmo-latch-asf-startup-timestamp-decision.patch
      proposed/0031-winedmo-open-secure-rtsp-tcp-aliases.patch
      ge-master-20260913-se2-p8/0032-winedmo-classify-http-media-after-probing.patch
      proposed/0033-winedmo-bound-and-extend-audio-channel-counts.patch
      proposed/0034-mfmediaengine-honor-ready-source-autoplay.patch
      proposed/0036-mfmediaengine-guard-audio-only-segment-end.patch
      proposed/0041-winedmo-allow-supported-hls-audio-containers.patch
      proposed/0042-winedmo-expose-existing-flac-audio-decoder.patch
      proposed/0043-mf-rearm-audio-sample-demand-after-flush.patch
      proposed/0044-mf-initialize-sar-marker-entry-before-copy.patch
      proposed/0045-mf-reset-seek-eos-and-discriminate-sink-markers.patch
      ge-master-20260913-se2-p8/0046-mf-tests-preserve-held-marker-context.patch
      ge-master-20260913-se2-p8/0047-winedmo-expose-ac3-and-eac3-audio-decoding.patch
    )
    if [[ "$PIN_ID" != ge-master-20260913-se2-p8 ]]; then
      selected_module_series+=(proposed/0048-winedmo-expose-existing-dts-alac-and-g711-decoders.patch)
      selected_module_series+=(proposed/0049-winedmo-expose-existing-mpeg-layer-audio-decoder.patch)
      if [[ "$PIN_ID" != ge-master-20260913-se2-p9 ]]; then
        selected_module_series+=(ge-master-20260913-se2-p10/0050-winedmo-expose-existing-mjpeg-video-decoder.patch)
      else
        selected_module_series+=(proposed/0050-winedmo-expose-existing-mjpeg-video-decoder.patch)
      fi
    fi
    if [[ "$PIN_ID" == ge-master-20260913-se2-p11 ]]; then
      selected_module_series+=(proposed/0051-winedmo-expose-existing-mpeg-video-decoders.patch)
      selected_module_series+=(proposed/0052-winedmo-register-existing-mpeg4-video-aliases.patch)
      selected_module_series+=(proposed/0053-winedmo-map-exact-h264-es-subtype.patch)
    elif [[ "$PIN_ID" == ge-master-20260913-se2-p12 || "$PIN_ID" == ge-master-20260913-se2-p13 || "$PIN_ID" == ge-proton11-7-se2-p14 || "$PIN_ID" == ge-proton11-7-se2-p15 || "$PIN_ID" == ge-proton11-7-se2-p16 || "$PIN_ID" == ge-proton11-7-se2-p17 || "$PIN_ID" == ge-proton11-7-se2-p18 || "$PIN_ID" == ge-proton11-7-se2-p19a ]]; then
      selected_module_series+=(ge-master-20260913-se2-p12/0051-winedmo-expose-existing-mpeg-video-decoders.patch)
      selected_module_series+=(ge-master-20260913-se2-p12/0052-winedmo-register-existing-mpeg4-video-aliases.patch)
      selected_module_series+=(proposed/0053-winedmo-map-exact-h264-es-subtype.patch)
      selected_module_series+=(proposed/0054-winedmo-drain-parser-tail-before-decoder-eos.patch)
      if [[ "$PIN_ID" == ge-master-20260913-se2-p13 || "$PIN_ID" == ge-proton11-7-se2-p14 || "$PIN_ID" == ge-proton11-7-se2-p15 || "$PIN_ID" == ge-proton11-7-se2-p16 || "$PIN_ID" == ge-proton11-7-se2-p17 || "$PIN_ID" == ge-proton11-7-se2-p18 || "$PIN_ID" == ge-proton11-7-se2-p19a ]]; then
        selected_module_series+=(proposed/0055-mfmediaengine-wait-for-renderer-drain-before-ended.patch)
        selected_module_series+=(proposed/0056-winedmo-preserve-vc1-input-timestamp-origin.patch)
        if [[ "$PIN_ID" == ge-proton11-7-se2-p15 ]]; then
          selected_module_series+=(
            proposed/0057-mfmediaengine-request-video-samples-on-clock.patch
            proposed/0058-mfmediaengine-share-immediate-seek-policy.patch
            proposed/0059-winedmo-probe-site-specific-hls-paths.patch
            proposed/0060-media-trace-bounded-attribution-counters.patch
          )
        elif [[ "$PIN_ID" == ge-proton11-7-se2-p16 || "$PIN_ID" == ge-proton11-7-se2-p17 || "$PIN_ID" == ge-proton11-7-se2-p18 || "$PIN_ID" == ge-proton11-7-se2-p19a ]]; then
          selected_module_series+=(
            proposed/0057-mfmediaengine-request-video-samples-on-clock.patch
            proposed/0058-mfmediaengine-share-immediate-seek-policy.patch
            proposed/0060-media-trace-bounded-attribution-counters.patch
            proposed/0061-winedmo-preserve-demuxed-video-timestamps.patch
          )
          if [[ "$PIN_ID" == ge-proton11-7-se2-p17 || "$PIN_ID" == ge-proton11-7-se2-p18 || "$PIN_ID" == ge-proton11-7-se2-p19a ]]; then
            selected_module_series[-1]=proposed/0061-winedmo-preserve-demuxed-video-timestamps-v2.patch
          fi
          if [[ "$PIN_ID" == ge-proton11-7-se2-p18 || "$PIN_ID" == ge-proton11-7-se2-p19a ]]; then
            selected_module_series+=(proposed/0062-winedmo-use-zero-based-parser-byte-position.patch)
          fi
          if [[ "$PIN_ID" == ge-proton11-7-se2-p19a ]]; then
            selected_module_series+=(
              ge-proton11-7-se2-p19a/0063-sr5-terminal-reader-errors.patch
              ge-proton11-7-se2-p19a/0064-sr3-propagate-output-layout.patch
              ge-proton11-7-se2-p19a/0065-sr1-preserve-source-timestamps.patch
              ge-proton11-7-se2-p19a/0066-sr4-forward-reconnect-events.patch
              ge-proton11-7-se2-p19a/0067-sr6-complete-prestart-flush.patch
              ge-proton11-7-se2-p19a/0068-sr2-preserve-leading-mp4-audio.patch
              ge-proton11-7-se2-p19a/0069-session-retain-stopped-sink-demand.patch
            )
          fi
          [[ "${PIN_FFMPEG_MPEGVIDEO_PATCH_SHA256:-}" == df53226a6d21f40b3337b5a6b38daada83ae216a76d2323e503c382dd5f620f1 \
              && "${PIN_FFMPEG_MPEGVIDEO_MAKEFILE_BLOB:-}" == 10724217d239068e71a57ce806936c91518fc501 ]] \
            || fail "P16 requires its exact MPEGVIDEO parser companion"
          pinned_ge_mpegvideo_build_patch >/dev/null
        fi
      fi
    fi
    ;;
  ge-proton11-9-se2-p20|ge-proton11-9-se2-p21|ge-proton11-9-se2-p22|ge-proton11-9-se2-p23|ge-proton11-9-se2-p24|ge-proton11-9-se2)
    # Fresh, source-reviewed GE11-9 residual composition. Bind every pin field
    # and companion postimage without inheriting an older candidate profile.
    SELECTED_PROFILE="${PIN_ID##*-}"
    selected_pin_sha256=05f43b644f619e07b0d55de8a8d1169422c0dbd147f048837dda47dcc099e522
    selected_residual_digest=58945b0803e0fa65e1e7807ac72c517e98f917b651bfed74c7b7b10de965937d
    if [[ "$SELECTED_PROFILE" == p21 ]]; then
      selected_pin_sha256=7d7dcd9901bfdbfec2a4a848033396f49f6f197d5874eb569c9d0c8ef5b09151
      selected_residual_digest=41b325bb83b1c9c9637b1573ffc34f8012855b16dd2a03cf7d13a3d1a6e1e66f
    elif [[ "$SELECTED_PROFILE" == p22 ]]; then
      selected_pin_sha256=75990d9bd53b136a352ac7000ae8f963f014f0f3991fe074016336fcbeff0edb
      selected_residual_digest=697eddec068dceb8276ed4677f9852b0eeebe6d261f630078a16b80e20d13ce8
    elif [[ "$SELECTED_PROFILE" == p23 ]]; then
      selected_pin_sha256=902b296f3eaf0c425febad727018f3b271a7eca3004458a1cdd4910fbaa1c1ca
      selected_residual_digest=0944b6a012793b03e9937baf30e79d890e425d7e6280f7fb7bcbd7649df6a8ff
    elif [[ "$SELECTED_PROFILE" == p24 ]]; then
      selected_pin_sha256=ddb7183ee86ab34a73fd2b1c1d07e5efa6f428f9e6e7e27330497659daf18b7c
      selected_residual_digest=dd9c1ea4563140dde394d7ad628ff5c37b89014e3d2a81edd84ada4d7ae2ee90
    elif [[ "$SELECTED_PROFILE" == se2 ]]; then
      # SE2 release: P24 content (series references the P24 patch files), release identity.
      selected_pin_sha256=0ef5401d156ee4a4b2cf5aa9b1eff7468f1297000f5096f931c7c56359b37e67
      selected_residual_digest=fa18c907344c727af11e03751f1cae19b538680f8d6c3274fda58afb48c19bb2
    fi
    selected_build_name="proton-ge-11-9-rtsp-se2-$SELECTED_PROFILE"
    [[ "$SELECTED_PROFILE" != se2 ]] || selected_build_name=proton-ge-11-9-rtsp-se2
    [[ "$(pinned_ge_sha256 "$PINNED_GE_CONFIG_PATH")" \
          == "$selected_pin_sha256" \
        && "$PIN_BUILD_NAME" == "$selected_build_name" \
        && "$PIN_KIND" == release-tag \
        && "$PIN_SOURCE_REF" == refs/tags/GE-Proton11-9 \
        && "$PIN_SOURCE_COMMIT" == 01bfbf67b35418fdd705f2be09e0bfb43eece24b \
        && "$PIN_SOURCE_TREE" == 465a332291b33655c8bfacf94ab8ac0f2779551e \
        && "$PIN_WINE_COMMIT" == 981e2f0b9007fd70a6e0ed6119cb18f4164e26f9 \
        && "$PIN_PROTON_LAUNCHER_POLICY" == upstream \
        && "$PIN_WITHOUT_NVIDIA_LIBS" == 0 && "$PIN_WITHOUT_VKLAYERS" == 0 \
        && "$PINNED_GE_HAS_PATCH_OVERLAP" == 0 \
        && -z "${PIN_FFMPEG_DAV1D_PATCH_SHA256:-}${PIN_FFMPEG_DAV1D_MAKEFILE_BLOB:-}" ]] \
      || fail "$PIN_ID immutable GE-Proton11-9 pin or upstream-dav1d policy changed"
    pinned_ge_rtsps_transport_patch >/dev/null
    pinned_ge_http_seek_patch >/dev/null
    pinned_ge_mpegvideo_build_patch >/dev/null
    pinned_ge_http_filesize_patch >/dev/null
    pinned_ge_hls_early_seek_patch >/dev/null
    # The AAC parser build module belongs to P24 alone; P20-P23 stay immutable
    # without it, and P24 must carry exactly the reviewed patch and postimage.
    if [[ "$SELECTED_PROFILE" == p24 || "$SELECTED_PROFILE" == se2 ]]; then
      [[ "${PIN_FFMPEG_AAC_PARSER_PATCH_SHA256:-}" == 755d0909e3b1c1873086dfc16b3bb865850c7591453579bac1580be67519e374 \
          && "${PIN_FFMPEG_AAC_PARSER_MAKEFILE_BLOB:-}" == db09146eb92a83607657e98c2c00958c0740ecc8 \
          && "${PIN_FFMPEG_MPEGVIDEO_MAKEFILE_BLOB:-}" == 16a91ff3b5bc37d419846ed4eefd435cef58914c ]] \
        || fail "P24 requires its exact AAC parser build module after the P23 MPEGVIDEO module"
      pinned_ge_aac_parser_build_patch >/dev/null
    else
      [[ -z "${PIN_FFMPEG_AAC_PARSER_PATCH_SHA256:-}${PIN_FFMPEG_AAC_PARSER_MAKEFILE_BLOB:-}" ]] \
        || fail "$PIN_ID is immutable and must not carry the AAC parser build module"
    fi
    ;;
  ge-proton11-11-se3-p1)
    # SE3-P1: the SE2 series (17 Wine patches, 0003/0006/0021 refreshed) rebased onto
    # GE-Proton11-11. Bind every pin field; GE11-9 candidates above stay immutable.
    SELECTED_PROFILE=se3p1
    selected_pin_sha256=2c65d37b3fe951936d9b27e0a510ee3a4dafb51cf49faa19804f850a39c72de8
    selected_residual_digest=8e8a156cc553cff66450f0b177bfb04f4dc166849f4db1d62889b1569a002eb5
    [[ "$(pinned_ge_sha256 "$PINNED_GE_CONFIG_PATH")" == "$selected_pin_sha256" \
        && "$PIN_BUILD_NAME" == proton-ge-11-11-rtsp-se3-p1 \
        && "$PIN_KIND" == release-tag \
        && "$PIN_SOURCE_REF" == refs/tags/GE-Proton11-11 \
        && "$PIN_SOURCE_COMMIT" == c0c2ee35e6d4d3bff4d39c6246ac46636434feb8 \
        && "$PIN_SOURCE_TREE" == c172c6ce0963373c2b498916d74c42e5fa733797 \
        && "$PIN_WINE_COMMIT" == c53678ab22a85f0fad3588dd34f0452a463bd015 \
        && "$PIN_WINE_STAGING_COMMIT" == 6cc805ea57132eeaf44764e9213823c9b8d0d300 \
        && "$PIN_FFMPEG_COMMIT" == 9047fa1b084f76b1b4d065af2d743df1b40dfb56 \
        && "$PIN_PATCH_DRIVER_BLOB" == 2f2569df12710459603f9f8b1ba4d078d156aaf0 \
        && "$PIN_PROTON_LAUNCHER_POLICY" == upstream \
        && "$PIN_WITHOUT_NVIDIA_LIBS" == 0 && "$PIN_WITHOUT_VKLAYERS" == 0 \
        && "$PINNED_GE_HAS_PATCH_OVERLAP" == 0 \
        && -z "${PIN_FFMPEG_DAV1D_PATCH_SHA256:-}${PIN_FFMPEG_DAV1D_MAKEFILE_BLOB:-}" ]] \
      || fail "$PIN_ID immutable GE-Proton11-11 pin or upstream-dav1d policy changed"
    pinned_ge_rtsps_transport_patch >/dev/null
    pinned_ge_http_seek_patch >/dev/null
    pinned_ge_mpegvideo_build_patch >/dev/null
    pinned_ge_http_filesize_patch >/dev/null
    pinned_ge_hls_early_seek_patch >/dev/null
    [[ "${PIN_FFMPEG_AAC_PARSER_PATCH_SHA256:-}" == 755d0909e3b1c1873086dfc16b3bb865850c7591453579bac1580be67519e374 \
        && "${PIN_FFMPEG_AAC_PARSER_MAKEFILE_BLOB:-}" == db09146eb92a83607657e98c2c00958c0740ecc8 \
        && "${PIN_FFMPEG_MPEGVIDEO_MAKEFILE_BLOB:-}" == 16a91ff3b5bc37d419846ed4eefd435cef58914c ]] \
      || fail "SE3-P1 requires its exact AAC parser build module after the MPEGVIDEO module"
    pinned_ge_aac_parser_build_patch >/dev/null
    ;;
  ge-proton11-11-se3-p2)
    # SE3-P2: SE3-P1's 17 Wine patches byte-identical + 0025-0034, on
    # GE-Proton11-11. Bind every pin field; GE11-9 candidates above stay immutable.
    SELECTED_PROFILE=se3p2
    selected_pin_sha256=dc0cbf760fd271eb9cd1b056cee5c8d44dde062f5fa15ea4aad2cf8756fea4bb
    selected_residual_digest=a53527b7e326d88cf3ffd5828ce8e4582544b478015211a03dd02d227cdcbf5e
    [[ "$(pinned_ge_sha256 "$PINNED_GE_CONFIG_PATH")" == "$selected_pin_sha256" \
        && "$PIN_BUILD_NAME" == proton-ge-11-11-rtsp-se3-p2 \
        && "$PIN_KIND" == release-tag \
        && "$PIN_SOURCE_REF" == refs/tags/GE-Proton11-11 \
        && "$PIN_SOURCE_COMMIT" == c0c2ee35e6d4d3bff4d39c6246ac46636434feb8 \
        && "$PIN_SOURCE_TREE" == c172c6ce0963373c2b498916d74c42e5fa733797 \
        && "$PIN_WINE_COMMIT" == c53678ab22a85f0fad3588dd34f0452a463bd015 \
        && "$PIN_WINE_STAGING_COMMIT" == 6cc805ea57132eeaf44764e9213823c9b8d0d300 \
        && "$PIN_FFMPEG_COMMIT" == 9047fa1b084f76b1b4d065af2d743df1b40dfb56 \
        && "$PIN_PATCH_DRIVER_BLOB" == 2f2569df12710459603f9f8b1ba4d078d156aaf0 \
        && "$PIN_PROTON_LAUNCHER_POLICY" == upstream \
        && "$PIN_WITHOUT_NVIDIA_LIBS" == 0 && "$PIN_WITHOUT_VKLAYERS" == 0 \
        && "$PINNED_GE_HAS_PATCH_OVERLAP" == 0 \
        && -z "${PIN_FFMPEG_DAV1D_PATCH_SHA256:-}${PIN_FFMPEG_DAV1D_MAKEFILE_BLOB:-}" ]] \
      || fail "$PIN_ID immutable GE-Proton11-11 pin or upstream-dav1d policy changed"
    pinned_ge_rtsps_transport_patch >/dev/null
    pinned_ge_http_seek_patch >/dev/null
    pinned_ge_mpegvideo_build_patch >/dev/null
    pinned_ge_http_filesize_patch >/dev/null
    pinned_ge_hls_early_seek_patch >/dev/null
    [[ "${PIN_FFMPEG_AAC_PARSER_PATCH_SHA256:-}" == 755d0909e3b1c1873086dfc16b3bb865850c7591453579bac1580be67519e374 \
        && "${PIN_FFMPEG_AAC_PARSER_MAKEFILE_BLOB:-}" == db09146eb92a83607657e98c2c00958c0740ecc8 \
        && "${PIN_FFMPEG_MPEGVIDEO_MAKEFILE_BLOB:-}" == 16a91ff3b5bc37d419846ed4eefd435cef58914c ]] \
      || fail "SE3-P2 requires its exact AAC parser build module after the MPEGVIDEO module"
    pinned_ge_aac_parser_build_patch >/dev/null
    ;;
  ge-proton11-11-se3-p3)
    # SE3-P3: SE3-P1's 17 Wine patches + 0025-0036, on
    # GE-Proton11-11. Bind every pin field; GE11-9 candidates above stay immutable.
    SELECTED_PROFILE=se3p3
    selected_pin_sha256=735fb14b9ad1d0e5dd40cdbf141e0f6ae120cf285b9feda8b15a80a355afa5fb
    selected_residual_digest=4690633db6f45d9ad8103d44441034cc7a448125faeb394302bed34a165d1bf9
    [[ "$(pinned_ge_sha256 "$PINNED_GE_CONFIG_PATH")" == "$selected_pin_sha256" \
        && "$PIN_BUILD_NAME" == proton-ge-11-11-rtsp-se3-p3 \
        && "$PIN_KIND" == release-tag \
        && "$PIN_SOURCE_REF" == refs/tags/GE-Proton11-11 \
        && "$PIN_SOURCE_COMMIT" == c0c2ee35e6d4d3bff4d39c6246ac46636434feb8 \
        && "$PIN_SOURCE_TREE" == c172c6ce0963373c2b498916d74c42e5fa733797 \
        && "$PIN_WINE_COMMIT" == c53678ab22a85f0fad3588dd34f0452a463bd015 \
        && "$PIN_WINE_STAGING_COMMIT" == 6cc805ea57132eeaf44764e9213823c9b8d0d300 \
        && "$PIN_FFMPEG_COMMIT" == 9047fa1b084f76b1b4d065af2d743df1b40dfb56 \
        && "$PIN_PATCH_DRIVER_BLOB" == 2f2569df12710459603f9f8b1ba4d078d156aaf0 \
        && "$PIN_PROTON_LAUNCHER_POLICY" == upstream \
        && "$PIN_WITHOUT_NVIDIA_LIBS" == 0 && "$PIN_WITHOUT_VKLAYERS" == 0 \
        && "$PINNED_GE_HAS_PATCH_OVERLAP" == 0 \
        && -z "${PIN_FFMPEG_DAV1D_PATCH_SHA256:-}${PIN_FFMPEG_DAV1D_MAKEFILE_BLOB:-}" ]] \
      || fail "$PIN_ID immutable GE-Proton11-11 pin or upstream-dav1d policy changed"
    pinned_ge_rtsps_transport_patch >/dev/null
    pinned_ge_http_seek_patch >/dev/null
    pinned_ge_mpegvideo_build_patch >/dev/null
    pinned_ge_http_filesize_patch >/dev/null
    pinned_ge_hls_early_seek_patch >/dev/null
    [[ "${PIN_FFMPEG_AAC_PARSER_PATCH_SHA256:-}" == 755d0909e3b1c1873086dfc16b3bb865850c7591453579bac1580be67519e374 \
        && "${PIN_FFMPEG_AAC_PARSER_MAKEFILE_BLOB:-}" == db09146eb92a83607657e98c2c00958c0740ecc8 \
        && "${PIN_FFMPEG_MPEGVIDEO_MAKEFILE_BLOB:-}" == 16a91ff3b5bc37d419846ed4eefd435cef58914c ]] \
      || fail "SE3-P3 requires its exact AAC parser build module after the MPEGVIDEO module"
    pinned_ge_aac_parser_build_patch >/dev/null
    ;;
  ge-proton11-11-se3-p4)
    # SE3-P4: SE3-P1's 17 Wine patches + 0025-0037, on
    # GE-Proton11-11. Bind every pin field; GE11-9 candidates above stay immutable.
    SELECTED_PROFILE=se3p4
    selected_pin_sha256=62907f5d1e521a3fc6f72d8fa31261dacbc9e4b48cc66222ca7949c843daf23d
    selected_residual_digest=3bf24ca68715faeb20ed1cf39c0ecd98f3416e95889b5215cbccea5c31145097
    [[ "$(pinned_ge_sha256 "$PINNED_GE_CONFIG_PATH")" == "$selected_pin_sha256" \
        && "$PIN_BUILD_NAME" == proton-ge-11-11-rtsp-se3-p4 \
        && "$PIN_KIND" == release-tag \
        && "$PIN_SOURCE_REF" == refs/tags/GE-Proton11-11 \
        && "$PIN_SOURCE_COMMIT" == c0c2ee35e6d4d3bff4d39c6246ac46636434feb8 \
        && "$PIN_SOURCE_TREE" == c172c6ce0963373c2b498916d74c42e5fa733797 \
        && "$PIN_WINE_COMMIT" == c53678ab22a85f0fad3588dd34f0452a463bd015 \
        && "$PIN_WINE_STAGING_COMMIT" == 6cc805ea57132eeaf44764e9213823c9b8d0d300 \
        && "$PIN_FFMPEG_COMMIT" == 9047fa1b084f76b1b4d065af2d743df1b40dfb56 \
        && "$PIN_PATCH_DRIVER_BLOB" == 2f2569df12710459603f9f8b1ba4d078d156aaf0 \
        && "$PIN_PROTON_LAUNCHER_POLICY" == upstream \
        && "$PIN_WITHOUT_NVIDIA_LIBS" == 0 && "$PIN_WITHOUT_VKLAYERS" == 0 \
        && "$PINNED_GE_HAS_PATCH_OVERLAP" == 0 \
        && -z "${PIN_FFMPEG_DAV1D_PATCH_SHA256:-}${PIN_FFMPEG_DAV1D_MAKEFILE_BLOB:-}" ]] \
      || fail "$PIN_ID immutable GE-Proton11-11 pin or upstream-dav1d policy changed"
    pinned_ge_rtsps_transport_patch >/dev/null
    pinned_ge_http_seek_patch >/dev/null
    pinned_ge_mpegvideo_build_patch >/dev/null
    pinned_ge_http_filesize_patch >/dev/null
    pinned_ge_hls_early_seek_patch >/dev/null
    [[ "${PIN_FFMPEG_AAC_PARSER_PATCH_SHA256:-}" == 755d0909e3b1c1873086dfc16b3bb865850c7591453579bac1580be67519e374 \
        && "${PIN_FFMPEG_AAC_PARSER_MAKEFILE_BLOB:-}" == db09146eb92a83607657e98c2c00958c0740ecc8 \
        && "${PIN_FFMPEG_MPEGVIDEO_MAKEFILE_BLOB:-}" == 16a91ff3b5bc37d419846ed4eefd435cef58914c ]] \
      || fail "SE3-P4 requires its exact AAC parser build module after the MPEGVIDEO module"
    pinned_ge_aac_parser_build_patch >/dev/null
    ;;
  ge-proton11-11-se3-p5)
    # SE3-P5: SE3-P1's 17 Wine patches + 0025-0037, on
    # GE-Proton11-11. Bind every pin field; GE11-9 candidates above stay immutable.
    SELECTED_PROFILE=se3p5
    selected_pin_sha256=526e4a93b9fc6eacf7b65ab3c6e916598212d542a361af84ea2b8d4b705cd83f
    selected_residual_digest=829b181d44a45c7bb10b4f235c4de1d4521886e3fa361b3c330275b674e5c133
    [[ "$(pinned_ge_sha256 "$PINNED_GE_CONFIG_PATH")" == "$selected_pin_sha256" \
        && "$PIN_BUILD_NAME" == proton-ge-11-11-rtsp-se3-p5 \
        && "$PIN_KIND" == release-tag \
        && "$PIN_SOURCE_REF" == refs/tags/GE-Proton11-11 \
        && "$PIN_SOURCE_COMMIT" == c0c2ee35e6d4d3bff4d39c6246ac46636434feb8 \
        && "$PIN_SOURCE_TREE" == c172c6ce0963373c2b498916d74c42e5fa733797 \
        && "$PIN_WINE_COMMIT" == c53678ab22a85f0fad3588dd34f0452a463bd015 \
        && "$PIN_WINE_STAGING_COMMIT" == 6cc805ea57132eeaf44764e9213823c9b8d0d300 \
        && "$PIN_FFMPEG_COMMIT" == 9047fa1b084f76b1b4d065af2d743df1b40dfb56 \
        && "$PIN_PATCH_DRIVER_BLOB" == 2f2569df12710459603f9f8b1ba4d078d156aaf0 \
        && "$PIN_PROTON_LAUNCHER_POLICY" == upstream \
        && "$PIN_WITHOUT_NVIDIA_LIBS" == 0 && "$PIN_WITHOUT_VKLAYERS" == 0 \
        && "$PINNED_GE_HAS_PATCH_OVERLAP" == 0 \
        && -z "${PIN_FFMPEG_DAV1D_PATCH_SHA256:-}${PIN_FFMPEG_DAV1D_MAKEFILE_BLOB:-}" ]] \
      || fail "$PIN_ID immutable GE-Proton11-11 pin or upstream-dav1d policy changed"
    pinned_ge_rtsps_transport_patch >/dev/null
    pinned_ge_http_seek_patch >/dev/null
    pinned_ge_mpegvideo_build_patch >/dev/null
    pinned_ge_http_filesize_patch >/dev/null
    pinned_ge_hls_early_seek_patch >/dev/null
    [[ "${PIN_FFMPEG_AAC_PARSER_PATCH_SHA256:-}" == 755d0909e3b1c1873086dfc16b3bb865850c7591453579bac1580be67519e374 \
        && "${PIN_FFMPEG_AAC_PARSER_MAKEFILE_BLOB:-}" == db09146eb92a83607657e98c2c00958c0740ecc8 \
        && "${PIN_FFMPEG_MPEGVIDEO_MAKEFILE_BLOB:-}" == 16a91ff3b5bc37d419846ed4eefd435cef58914c ]] \
      || fail "SE3-P5 requires its exact AAC parser build module after the MPEGVIDEO module"
    pinned_ge_aac_parser_build_patch >/dev/null
    ;;
  ge-proton11-11-se3-p6)
    # SE3-P6: SE3-P1's 17 Wine patches + 0025-0038, on
    # GE-Proton11-11. Bind every pin field; GE11-9 candidates above stay immutable.
    SELECTED_PROFILE=se3p6
    selected_pin_sha256=fe0df21e963178d91ee4ba5cd41df90a745c7b5f356aef9e2636b5a0f8d62120
    selected_residual_digest=6bd58e6f4911ddb8a9e1aaed440973639a00a443338e5141a710e2237cb5d4f9
    [[ "$(pinned_ge_sha256 "$PINNED_GE_CONFIG_PATH")" == "$selected_pin_sha256" \
        && "$PIN_BUILD_NAME" == proton-ge-11-11-rtsp-se3-p6 \
        && "$PIN_KIND" == release-tag \
        && "$PIN_SOURCE_REF" == refs/tags/GE-Proton11-11 \
        && "$PIN_SOURCE_COMMIT" == c0c2ee35e6d4d3bff4d39c6246ac46636434feb8 \
        && "$PIN_SOURCE_TREE" == c172c6ce0963373c2b498916d74c42e5fa733797 \
        && "$PIN_WINE_COMMIT" == c53678ab22a85f0fad3588dd34f0452a463bd015 \
        && "$PIN_WINE_STAGING_COMMIT" == 6cc805ea57132eeaf44764e9213823c9b8d0d300 \
        && "$PIN_FFMPEG_COMMIT" == 9047fa1b084f76b1b4d065af2d743df1b40dfb56 \
        && "$PIN_PATCH_DRIVER_BLOB" == 2f2569df12710459603f9f8b1ba4d078d156aaf0 \
        && "$PIN_PROTON_LAUNCHER_POLICY" == upstream \
        && "$PIN_WITHOUT_NVIDIA_LIBS" == 0 && "$PIN_WITHOUT_VKLAYERS" == 0 \
        && "$PINNED_GE_HAS_PATCH_OVERLAP" == 0 \
        && -z "${PIN_FFMPEG_DAV1D_PATCH_SHA256:-}${PIN_FFMPEG_DAV1D_MAKEFILE_BLOB:-}" ]] \
      || fail "$PIN_ID immutable GE-Proton11-11 pin or upstream-dav1d policy changed"
    pinned_ge_rtsps_transport_patch >/dev/null
    pinned_ge_http_seek_patch >/dev/null
    pinned_ge_mpegvideo_build_patch >/dev/null
    pinned_ge_http_filesize_patch >/dev/null
    pinned_ge_hls_early_seek_patch >/dev/null
    [[ "${PIN_FFMPEG_AAC_PARSER_PATCH_SHA256:-}" == 755d0909e3b1c1873086dfc16b3bb865850c7591453579bac1580be67519e374 \
        && "${PIN_FFMPEG_AAC_PARSER_MAKEFILE_BLOB:-}" == db09146eb92a83607657e98c2c00958c0740ecc8 \
        && "${PIN_FFMPEG_MPEGVIDEO_MAKEFILE_BLOB:-}" == 16a91ff3b5bc37d419846ed4eefd435cef58914c ]] \
      || fail "SE3-P6 requires its exact AAC parser build module after the MPEGVIDEO module"
    pinned_ge_aac_parser_build_patch >/dev/null
    ;;
  ge-proton11-11-se3-p7)
    # SE3-P7: SE3-P1's 17 Wine patches + 0025-0041, on
    # GE-Proton11-11. Bind every pin field; GE11-9 candidates above stay immutable.
    SELECTED_PROFILE=se3p7
    selected_pin_sha256=94da5db661ffcf49493726e8c69d91c2b99b7ac5fb78fc5e16ccfd1e751803c3
    selected_residual_digest=20ce449770cb2650b11127a855bb88e28eda48921f01eb6f73333955189df280
    [[ "$(pinned_ge_sha256 "$PINNED_GE_CONFIG_PATH")" == "$selected_pin_sha256" \
        && "$PIN_BUILD_NAME" == proton-ge-11-11-rtsp-se3-p7 \
        && "$PIN_KIND" == release-tag \
        && "$PIN_SOURCE_REF" == refs/tags/GE-Proton11-11 \
        && "$PIN_SOURCE_COMMIT" == c0c2ee35e6d4d3bff4d39c6246ac46636434feb8 \
        && "$PIN_SOURCE_TREE" == c172c6ce0963373c2b498916d74c42e5fa733797 \
        && "$PIN_WINE_COMMIT" == c53678ab22a85f0fad3588dd34f0452a463bd015 \
        && "$PIN_WINE_STAGING_COMMIT" == 6cc805ea57132eeaf44764e9213823c9b8d0d300 \
        && "$PIN_FFMPEG_COMMIT" == 9047fa1b084f76b1b4d065af2d743df1b40dfb56 \
        && "$PIN_PATCH_DRIVER_BLOB" == 2f2569df12710459603f9f8b1ba4d078d156aaf0 \
        && "$PIN_PROTON_LAUNCHER_POLICY" == upstream \
        && "$PIN_WITHOUT_NVIDIA_LIBS" == 0 && "$PIN_WITHOUT_VKLAYERS" == 0 \
        && "$PINNED_GE_HAS_PATCH_OVERLAP" == 0 \
        && -z "${PIN_FFMPEG_DAV1D_PATCH_SHA256:-}${PIN_FFMPEG_DAV1D_MAKEFILE_BLOB:-}" ]] \
      || fail "$PIN_ID immutable GE-Proton11-11 pin or upstream-dav1d policy changed"
    pinned_ge_rtsps_transport_patch >/dev/null
    pinned_ge_http_seek_patch >/dev/null
    pinned_ge_mpegvideo_build_patch >/dev/null
    pinned_ge_http_filesize_patch >/dev/null
    pinned_ge_hls_early_seek_patch >/dev/null
    [[ "${PIN_FFMPEG_AAC_PARSER_PATCH_SHA256:-}" == 755d0909e3b1c1873086dfc16b3bb865850c7591453579bac1580be67519e374 \
        && "${PIN_FFMPEG_AAC_PARSER_MAKEFILE_BLOB:-}" == db09146eb92a83607657e98c2c00958c0740ecc8 \
        && "${PIN_FFMPEG_MPEGVIDEO_MAKEFILE_BLOB:-}" == 16a91ff3b5bc37d419846ed4eefd435cef58914c ]] \
      || fail "SE3-P7 requires its exact AAC parser build module after the MPEGVIDEO module"
    pinned_ge_aac_parser_build_patch >/dev/null
    ;;
  ge-proton11-11-se3-p8)
    # SE3-P8: SE3-P1's 17 Wine patches + 0025-0041 minus 0039, on
    # GE-Proton11-11. Bind every pin field; GE11-9 candidates above stay immutable.
    SELECTED_PROFILE=se3p8
    selected_pin_sha256=3b34f2e0c5165bf27006af7c610815861810bc3c88f1dc3e28db605ac67b59c6
    selected_residual_digest=f3a358edbf65b0bcf15087d76cdd0ae3ffa730aa54a37075c8d2fa935606da68
    [[ "$(pinned_ge_sha256 "$PINNED_GE_CONFIG_PATH")" == "$selected_pin_sha256" \
        && "$PIN_BUILD_NAME" == proton-ge-11-11-rtsp-se3-p8 \
        && "$PIN_KIND" == release-tag \
        && "$PIN_SOURCE_REF" == refs/tags/GE-Proton11-11 \
        && "$PIN_SOURCE_COMMIT" == c0c2ee35e6d4d3bff4d39c6246ac46636434feb8 \
        && "$PIN_SOURCE_TREE" == c172c6ce0963373c2b498916d74c42e5fa733797 \
        && "$PIN_WINE_COMMIT" == c53678ab22a85f0fad3588dd34f0452a463bd015 \
        && "$PIN_WINE_STAGING_COMMIT" == 6cc805ea57132eeaf44764e9213823c9b8d0d300 \
        && "$PIN_FFMPEG_COMMIT" == 9047fa1b084f76b1b4d065af2d743df1b40dfb56 \
        && "$PIN_PATCH_DRIVER_BLOB" == 2f2569df12710459603f9f8b1ba4d078d156aaf0 \
        && "$PIN_PROTON_LAUNCHER_POLICY" == upstream \
        && "$PIN_WITHOUT_NVIDIA_LIBS" == 0 && "$PIN_WITHOUT_VKLAYERS" == 0 \
        && "$PINNED_GE_HAS_PATCH_OVERLAP" == 0 \
        && -z "${PIN_FFMPEG_DAV1D_PATCH_SHA256:-}${PIN_FFMPEG_DAV1D_MAKEFILE_BLOB:-}" ]] \
      || fail "$PIN_ID immutable GE-Proton11-11 pin or upstream-dav1d policy changed"
    pinned_ge_rtsps_transport_patch >/dev/null
    pinned_ge_http_seek_patch >/dev/null
    pinned_ge_mpegvideo_build_patch >/dev/null
    pinned_ge_http_filesize_patch >/dev/null
    pinned_ge_hls_early_seek_patch >/dev/null
    [[ "${PIN_FFMPEG_AAC_PARSER_PATCH_SHA256:-}" == 755d0909e3b1c1873086dfc16b3bb865850c7591453579bac1580be67519e374 \
        && "${PIN_FFMPEG_AAC_PARSER_MAKEFILE_BLOB:-}" == db09146eb92a83607657e98c2c00958c0740ecc8 \
        && "${PIN_FFMPEG_MPEGVIDEO_MAKEFILE_BLOB:-}" == 16a91ff3b5bc37d419846ed4eefd435cef58914c ]] \
      || fail "SE3-P8 requires its exact AAC parser build module after the MPEGVIDEO module"
    pinned_ge_aac_parser_build_patch >/dev/null
    ;;
  ge-proton11-11-se3-p9)
    # SE3-P9: SE3-P1's 17 Wine patches + 0025-0042 minus 0039, on
    # GE-Proton11-11. Bind every pin field; GE11-9 candidates above stay immutable.
    SELECTED_PROFILE=se3p9
    selected_pin_sha256=2540d8776ac28696ca9e86949c01e0fd9ea53301b8bd7949f41f6592bd8bc433
    selected_residual_digest=d845d1cb7e28109a48225b563ba34286b47ea7bf0e9a605fadbe8e1ec552789c
    [[ "$(pinned_ge_sha256 "$PINNED_GE_CONFIG_PATH")" == "$selected_pin_sha256" \
        && "$PIN_BUILD_NAME" == proton-ge-11-11-rtsp-se3-p9 \
        && "$PIN_KIND" == release-tag \
        && "$PIN_SOURCE_REF" == refs/tags/GE-Proton11-11 \
        && "$PIN_SOURCE_COMMIT" == c0c2ee35e6d4d3bff4d39c6246ac46636434feb8 \
        && "$PIN_SOURCE_TREE" == c172c6ce0963373c2b498916d74c42e5fa733797 \
        && "$PIN_WINE_COMMIT" == c53678ab22a85f0fad3588dd34f0452a463bd015 \
        && "$PIN_WINE_STAGING_COMMIT" == 6cc805ea57132eeaf44764e9213823c9b8d0d300 \
        && "$PIN_FFMPEG_COMMIT" == 9047fa1b084f76b1b4d065af2d743df1b40dfb56 \
        && "$PIN_PATCH_DRIVER_BLOB" == 2f2569df12710459603f9f8b1ba4d078d156aaf0 \
        && "$PIN_PROTON_LAUNCHER_POLICY" == upstream \
        && "$PIN_WITHOUT_NVIDIA_LIBS" == 0 && "$PIN_WITHOUT_VKLAYERS" == 0 \
        && "$PINNED_GE_HAS_PATCH_OVERLAP" == 0 \
        && -z "${PIN_FFMPEG_DAV1D_PATCH_SHA256:-}${PIN_FFMPEG_DAV1D_MAKEFILE_BLOB:-}" ]] \
      || fail "$PIN_ID immutable GE-Proton11-11 pin or upstream-dav1d policy changed"
    pinned_ge_rtsps_transport_patch >/dev/null
    pinned_ge_http_seek_patch >/dev/null
    pinned_ge_mpegvideo_build_patch >/dev/null
    pinned_ge_http_filesize_patch >/dev/null
    pinned_ge_hls_early_seek_patch >/dev/null
    [[ "${PIN_FFMPEG_AAC_PARSER_PATCH_SHA256:-}" == 755d0909e3b1c1873086dfc16b3bb865850c7591453579bac1580be67519e374 \
        && "${PIN_FFMPEG_AAC_PARSER_MAKEFILE_BLOB:-}" == db09146eb92a83607657e98c2c00958c0740ecc8 \
        && "${PIN_FFMPEG_MPEGVIDEO_MAKEFILE_BLOB:-}" == 16a91ff3b5bc37d419846ed4eefd435cef58914c ]] \
      || fail "SE3-P9 requires its exact AAC parser build module after the MPEGVIDEO module"
    pinned_ge_aac_parser_build_patch >/dev/null
    ;;
  ge-proton11-11-se3)
    # SE3 release: SE3-P9's content (34 Wine patches) under the release identity, on
    # GE-Proton11-11. Bind every pin field; GE11-9 candidates above stay immutable.
    SELECTED_PROFILE=se3
    selected_pin_sha256=daf5ad072a39e7c65a076963740fbe512c3bda2e8dcc753c4d3f9ea42681add5
    selected_residual_digest=ca987d562522c0da79f68b9720e9efee9cb6d0ae46de569a7820028e0603ec4b
    [[ "$(pinned_ge_sha256 "$PINNED_GE_CONFIG_PATH")" == "$selected_pin_sha256" \
        && "$PIN_BUILD_NAME" == proton-ge-11-11-rtsp-se3 \
        && "$PIN_KIND" == release-tag \
        && "$PIN_SOURCE_REF" == refs/tags/GE-Proton11-11 \
        && "$PIN_SOURCE_COMMIT" == c0c2ee35e6d4d3bff4d39c6246ac46636434feb8 \
        && "$PIN_SOURCE_TREE" == c172c6ce0963373c2b498916d74c42e5fa733797 \
        && "$PIN_WINE_COMMIT" == c53678ab22a85f0fad3588dd34f0452a463bd015 \
        && "$PIN_WINE_STAGING_COMMIT" == 6cc805ea57132eeaf44764e9213823c9b8d0d300 \
        && "$PIN_FFMPEG_COMMIT" == 9047fa1b084f76b1b4d065af2d743df1b40dfb56 \
        && "$PIN_PATCH_DRIVER_BLOB" == 2f2569df12710459603f9f8b1ba4d078d156aaf0 \
        && "$PIN_PROTON_LAUNCHER_POLICY" == upstream \
        && "$PIN_WITHOUT_NVIDIA_LIBS" == 0 && "$PIN_WITHOUT_VKLAYERS" == 0 \
        && "$PINNED_GE_HAS_PATCH_OVERLAP" == 0 \
        && -z "${PIN_FFMPEG_DAV1D_PATCH_SHA256:-}${PIN_FFMPEG_DAV1D_MAKEFILE_BLOB:-}" ]] \
      || fail "$PIN_ID immutable GE-Proton11-11 pin or upstream-dav1d policy changed"
    pinned_ge_rtsps_transport_patch >/dev/null
    pinned_ge_http_seek_patch >/dev/null
    pinned_ge_mpegvideo_build_patch >/dev/null
    pinned_ge_http_filesize_patch >/dev/null
    pinned_ge_hls_early_seek_patch >/dev/null
    [[ "${PIN_FFMPEG_AAC_PARSER_PATCH_SHA256:-}" == 755d0909e3b1c1873086dfc16b3bb865850c7591453579bac1580be67519e374 \
        && "${PIN_FFMPEG_AAC_PARSER_MAKEFILE_BLOB:-}" == db09146eb92a83607657e98c2c00958c0740ecc8 \
        && "${PIN_FFMPEG_MPEGVIDEO_MAKEFILE_BLOB:-}" == 16a91ff3b5bc37d419846ed4eefd435cef58914c ]] \
      || fail "SE3 requires its exact AAC parser build module after the MPEGVIDEO module"
    pinned_ge_aac_parser_build_patch >/dev/null
    ;;
  ge-proton11-12-se4-p1)
    # SE4-P1: GE-Proton11-12 + the reworked project Wine series + the SE3 FFmpeg
    # modules + the HTTP chunked-end module; skips GE's rtworkq post-series hotfix
    # in favor of the project's own patch 0025. Bind every pin field.
    SELECTED_PROFILE=se4p1
    selected_pin_sha256=d307ef1efa6074d748782148134c0a4d73d866ef838cdc7812d880e3c07b2e8d
    # Series digest of patches/series-ge-proton11-12-se4-p1 (pinned_ge_series_digest).
    selected_residual_digest=db18182cf259b0c25401361ec0604ae34edc2ef77f413533792998305963ef7f
    [[ "$(pinned_ge_sha256 "$PINNED_GE_CONFIG_PATH")" == "$selected_pin_sha256" \
        && "$PIN_BUILD_NAME" == proton-ge-11-12-rtsp-se4-p1 \
        && "$PIN_KIND" == release-tag \
        && "$PIN_SOURCE_REF" == refs/tags/GE-Proton11-12 \
        && "$PIN_SOURCE_COMMIT" == f85547f0ea51ac356ab42b4de57b927b0044cc85 \
        && "$PIN_SOURCE_TREE" == b8286f4c76ec63a6b2096ab111d04d410bba19de \
        && "$PIN_WINE_COMMIT" == fda79a585939fb7512dc220a11249f9ffe825fcf \
        && "$PIN_WINE_STAGING_COMMIT" == 6cc805ea57132eeaf44764e9213823c9b8d0d300 \
        && "$PIN_FFMPEG_COMMIT" == 9047fa1b084f76b1b4d065af2d743df1b40dfb56 \
        && "$PIN_PATCH_DRIVER_BLOB" == f0d6510f75de69d17a6fb6278fe308541a4e1ef6 \
        && "$PIN_PROTON_LAUNCHER_POLICY" == upstream \
        && "$PIN_WITHOUT_NVIDIA_LIBS" == 0 && "$PIN_WITHOUT_VKLAYERS" == 0 \
        && "$PINNED_GE_HAS_PATCH_OVERLAP" == 0 \
        && -z "${PIN_FFMPEG_DAV1D_PATCH_SHA256:-}${PIN_FFMPEG_DAV1D_MAKEFILE_BLOB:-}" ]] \
      || fail "$PIN_ID immutable GE-Proton11-12 pin or upstream-dav1d policy changed"
    pinned_ge_rtsps_transport_patch >/dev/null
    pinned_ge_http_seek_patch >/dev/null
    pinned_ge_mpegvideo_build_patch >/dev/null
    pinned_ge_http_filesize_patch >/dev/null
    pinned_ge_http_chunkend_patch >/dev/null
    pinned_ge_hls_early_seek_patch >/dev/null
    [[ "${PIN_FFMPEG_HTTP_CHUNKEND_PATCH_SHA256:-}" == b170e0eea6e4b364fc5b4616f22e1a2b464662c19ef71f89b0592c806f1250db \
        && "${PIN_FFMPEG_HTTP_CHUNKEND_HTTP_BLOB:-}" == ff99262dec1124c133f1a832b04845e7bf06c020 ]] \
      || fail "SE4-P1 requires its exact HTTP chunked-end module"
    [[ "${PIN_FFMPEG_AAC_PARSER_PATCH_SHA256:-}" == 755d0909e3b1c1873086dfc16b3bb865850c7591453579bac1580be67519e374 \
        && "${PIN_FFMPEG_AAC_PARSER_MAKEFILE_BLOB:-}" == fcf554c93afb1e3f13173909d74273cfee58ee19 \
        && "${PIN_FFMPEG_MPEGVIDEO_MAKEFILE_BLOB:-}" == 6da863e55ba90e9e5dc816a796594f1d8cea6c28 \
        && "$PIN_FFMPEG_CRYPTO_BUILD_MAKEFILE_BLOB" == bd0333dcc2207809189d535729c74f6a3a4f33ba ]] \
      || fail "SE4-P1 requires its exact crypto/MPEGVIDEO/AAC Makefile.in build modules for GE-Proton11-12"
    pinned_ge_aac_parser_build_patch >/dev/null
    [[ "${PIN_GE_SKIP_PATCHES:-}" == patches/wine-hotfixes/pending/rtworkq-dont-hold-queues-section-during-system-queue-shutdown.patch:fa65977bda168c863cffea3faa0643f21c0f990524e7e90fe1105794e501bc7d ]] \
      || fail "SE4-P1 must skip exactly GE's rtworkq post-series hotfix"
    ;;
  ge-proton11-12-se4-p1-r2)
    # SE4-P1 r2: the draft arm's pin plus a second GE deviation (protonfixes 0003,
    # already present byte-identically in the pinned protonfixes). Same series,
    # same GE11-12 fields, same build name; the draft pin and arm stay as the record.
    SELECTED_PROFILE=se4p1
    selected_pin_sha256=0d0900fdfc8db9c923a86f1ea3f56840a57b68c10fc8728aa728dc9f8bdbc3b0
    # Series digest of patches/series-ge-proton11-12-se4-p1 (pinned_ge_series_digest).
    selected_residual_digest=db18182cf259b0c25401361ec0604ae34edc2ef77f413533792998305963ef7f
    [[ "$(pinned_ge_sha256 "$PINNED_GE_CONFIG_PATH")" == "$selected_pin_sha256" \
        && "$PIN_BUILD_NAME" == proton-ge-11-12-rtsp-se4-p1 \
        && "$PIN_KIND" == release-tag \
        && "$PIN_SOURCE_REF" == refs/tags/GE-Proton11-12 \
        && "$PIN_SOURCE_COMMIT" == f85547f0ea51ac356ab42b4de57b927b0044cc85 \
        && "$PIN_SOURCE_TREE" == b8286f4c76ec63a6b2096ab111d04d410bba19de \
        && "$PIN_WINE_COMMIT" == fda79a585939fb7512dc220a11249f9ffe825fcf \
        && "$PIN_WINE_STAGING_COMMIT" == 6cc805ea57132eeaf44764e9213823c9b8d0d300 \
        && "$PIN_FFMPEG_COMMIT" == 9047fa1b084f76b1b4d065af2d743df1b40dfb56 \
        && "$PIN_PATCH_DRIVER_BLOB" == f0d6510f75de69d17a6fb6278fe308541a4e1ef6 \
        && "$PIN_PROTON_LAUNCHER_POLICY" == upstream \
        && "$PIN_WITHOUT_NVIDIA_LIBS" == 0 && "$PIN_WITHOUT_VKLAYERS" == 0 \
        && "$PINNED_GE_HAS_PATCH_OVERLAP" == 0 \
        && -z "${PIN_FFMPEG_DAV1D_PATCH_SHA256:-}${PIN_FFMPEG_DAV1D_MAKEFILE_BLOB:-}" ]] \
      || fail "$PIN_ID immutable GE-Proton11-12 pin or upstream-dav1d policy changed"
    pinned_ge_rtsps_transport_patch >/dev/null
    pinned_ge_http_seek_patch >/dev/null
    pinned_ge_mpegvideo_build_patch >/dev/null
    pinned_ge_http_filesize_patch >/dev/null
    pinned_ge_http_chunkend_patch >/dev/null
    pinned_ge_hls_early_seek_patch >/dev/null
    [[ "${PIN_FFMPEG_HTTP_CHUNKEND_PATCH_SHA256:-}" == b170e0eea6e4b364fc5b4616f22e1a2b464662c19ef71f89b0592c806f1250db \
        && "${PIN_FFMPEG_HTTP_CHUNKEND_HTTP_BLOB:-}" == ff99262dec1124c133f1a832b04845e7bf06c020 ]] \
      || fail "SE4-P1 requires its exact HTTP chunked-end module"
    [[ "${PIN_FFMPEG_AAC_PARSER_PATCH_SHA256:-}" == 755d0909e3b1c1873086dfc16b3bb865850c7591453579bac1580be67519e374 \
        && "${PIN_FFMPEG_AAC_PARSER_MAKEFILE_BLOB:-}" == fcf554c93afb1e3f13173909d74273cfee58ee19 \
        && "${PIN_FFMPEG_MPEGVIDEO_MAKEFILE_BLOB:-}" == 6da863e55ba90e9e5dc816a796594f1d8cea6c28 \
        && "$PIN_FFMPEG_CRYPTO_BUILD_MAKEFILE_BLOB" == bd0333dcc2207809189d535729c74f6a3a4f33ba ]] \
      || fail "SE4-P1 requires its exact crypto/MPEGVIDEO/AAC Makefile.in build modules for GE-Proton11-12"
    pinned_ge_aac_parser_build_patch >/dev/null
    [[ "${PIN_GE_SKIP_PATCHES:-}" == patches/wine-hotfixes/pending/rtworkq-dont-hold-queues-section-during-system-queue-shutdown.patch:fa65977bda168c863cffea3faa0643f21c0f990524e7e90fe1105794e501bc7d,patches/protonfixes/0003-gamefix-kingdoms-of-amalur-re-reckoning-d3dcompiler.patch:30f6b9b5bd427eadeb114a748fa4ed6666d11f26e26447f6492daa31d0e17311 ]] \
      || fail "SE4-P1 r2 must skip exactly GE's rtworkq post-series hotfix and protonfixes 0003"
    ;;
  ge-proton11-12-se4-p2)
    # SE4-P2 (2026-11-10): the SE4-P1 r2 pin with only PIN_ID and PIN_BUILD_NAME
    # changed, and the SE4-P2 series (SE4-P1 + 0043, finding F1). Same GE11-12
    # fields, FFmpeg modules and skips; the SE4-P1 profile token is reused.
    SELECTED_PROFILE=se4p1
    selected_pin_sha256=7e2472f58543970d1c698f03d71ac32c10491e6378221347453308c59c610d4d
    # Series digest of patches/series-ge-proton11-12-se4-p2 (pinned_ge_series_digest).
    selected_residual_digest=ea31439bd4c3e2ee79091d593647a7961fe145f940672b4ecad62ea24608c34f
    [[ "$(pinned_ge_sha256 "$PINNED_GE_CONFIG_PATH")" == "$selected_pin_sha256" \
        && "$PIN_BUILD_NAME" == proton-ge-11-12-rtsp-se4-p2 \
        && "$PIN_KIND" == release-tag \
        && "$PIN_SOURCE_REF" == refs/tags/GE-Proton11-12 \
        && "$PIN_SOURCE_COMMIT" == f85547f0ea51ac356ab42b4de57b927b0044cc85 \
        && "$PIN_SOURCE_TREE" == b8286f4c76ec63a6b2096ab111d04d410bba19de \
        && "$PIN_WINE_COMMIT" == fda79a585939fb7512dc220a11249f9ffe825fcf \
        && "$PIN_WINE_STAGING_COMMIT" == 6cc805ea57132eeaf44764e9213823c9b8d0d300 \
        && "$PIN_FFMPEG_COMMIT" == 9047fa1b084f76b1b4d065af2d743df1b40dfb56 \
        && "$PIN_PATCH_DRIVER_BLOB" == f0d6510f75de69d17a6fb6278fe308541a4e1ef6 \
        && "$PIN_PROTON_LAUNCHER_POLICY" == upstream \
        && "$PIN_WITHOUT_NVIDIA_LIBS" == 0 && "$PIN_WITHOUT_VKLAYERS" == 0 \
        && "$PINNED_GE_HAS_PATCH_OVERLAP" == 0 \
        && -z "${PIN_FFMPEG_DAV1D_PATCH_SHA256:-}${PIN_FFMPEG_DAV1D_MAKEFILE_BLOB:-}" ]] \
      || fail "$PIN_ID immutable GE-Proton11-12 pin or upstream-dav1d policy changed"
    pinned_ge_rtsps_transport_patch >/dev/null
    pinned_ge_http_seek_patch >/dev/null
    pinned_ge_mpegvideo_build_patch >/dev/null
    pinned_ge_http_filesize_patch >/dev/null
    pinned_ge_http_chunkend_patch >/dev/null
    pinned_ge_hls_early_seek_patch >/dev/null
    [[ "${PIN_FFMPEG_HTTP_CHUNKEND_PATCH_SHA256:-}" == b170e0eea6e4b364fc5b4616f22e1a2b464662c19ef71f89b0592c806f1250db \
        && "${PIN_FFMPEG_HTTP_CHUNKEND_HTTP_BLOB:-}" == ff99262dec1124c133f1a832b04845e7bf06c020 ]] \
      || fail "SE4-P1 requires its exact HTTP chunked-end module"
    [[ "${PIN_FFMPEG_AAC_PARSER_PATCH_SHA256:-}" == 755d0909e3b1c1873086dfc16b3bb865850c7591453579bac1580be67519e374 \
        && "${PIN_FFMPEG_AAC_PARSER_MAKEFILE_BLOB:-}" == fcf554c93afb1e3f13173909d74273cfee58ee19 \
        && "${PIN_FFMPEG_MPEGVIDEO_MAKEFILE_BLOB:-}" == 6da863e55ba90e9e5dc816a796594f1d8cea6c28 \
        && "$PIN_FFMPEG_CRYPTO_BUILD_MAKEFILE_BLOB" == bd0333dcc2207809189d535729c74f6a3a4f33ba ]] \
      || fail "SE4-P1 requires its exact crypto/MPEGVIDEO/AAC Makefile.in build modules for GE-Proton11-12"
    pinned_ge_aac_parser_build_patch >/dev/null
    [[ "${PIN_GE_SKIP_PATCHES:-}" == patches/wine-hotfixes/pending/rtworkq-dont-hold-queues-section-during-system-queue-shutdown.patch:fa65977bda168c863cffea3faa0643f21c0f990524e7e90fe1105794e501bc7d,patches/protonfixes/0003-gamefix-kingdoms-of-amalur-re-reckoning-d3dcompiler.patch:30f6b9b5bd427eadeb114a748fa4ed6666d11f26e26447f6492daa31d0e17311 ]] \
      || fail "SE4-P2 must skip exactly GE's rtworkq post-series hotfix and protonfixes 0003"
    ;;
  ge-proton11-12-se4-p3)
    # SE4-P3 (2026-11-11): the SE4-P2 pin with only PIN_ID and PIN_BUILD_NAME
    # changed, and the SE4-P3 series (SE4-P2 + 0044, live-HLS discontinuity timeline).
    # Same GE11-12 fields, FFmpeg modules and skips; the SE4-P1 profile token is reused.
    SELECTED_PROFILE=se4p1
    selected_pin_sha256=72daed54d3b1b2e71a45c97ef3d4ee22fa09870522cb52dfe19377b9d7a8b75f
    # Series digest of patches/series-ge-proton11-12-se4-p3 (pinned_ge_series_digest).
    selected_residual_digest=bbb660243f6c6758176b983bb74a714710c7baaedb48f89936c536886b6bba71
    [[ "$(pinned_ge_sha256 "$PINNED_GE_CONFIG_PATH")" == "$selected_pin_sha256" \
        && "$PIN_BUILD_NAME" == proton-ge-11-12-rtsp-se4-p3 \
        && "$PIN_KIND" == release-tag \
        && "$PIN_SOURCE_REF" == refs/tags/GE-Proton11-12 \
        && "$PIN_SOURCE_COMMIT" == f85547f0ea51ac356ab42b4de57b927b0044cc85 \
        && "$PIN_SOURCE_TREE" == b8286f4c76ec63a6b2096ab111d04d410bba19de \
        && "$PIN_WINE_COMMIT" == fda79a585939fb7512dc220a11249f9ffe825fcf \
        && "$PIN_WINE_STAGING_COMMIT" == 6cc805ea57132eeaf44764e9213823c9b8d0d300 \
        && "$PIN_FFMPEG_COMMIT" == 9047fa1b084f76b1b4d065af2d743df1b40dfb56 \
        && "$PIN_PATCH_DRIVER_BLOB" == f0d6510f75de69d17a6fb6278fe308541a4e1ef6 \
        && "$PIN_PROTON_LAUNCHER_POLICY" == upstream \
        && "$PIN_WITHOUT_NVIDIA_LIBS" == 0 && "$PIN_WITHOUT_VKLAYERS" == 0 \
        && "$PINNED_GE_HAS_PATCH_OVERLAP" == 0 \
        && -z "${PIN_FFMPEG_DAV1D_PATCH_SHA256:-}${PIN_FFMPEG_DAV1D_MAKEFILE_BLOB:-}" ]] \
      || fail "$PIN_ID immutable GE-Proton11-12 pin or upstream-dav1d policy changed"
    pinned_ge_rtsps_transport_patch >/dev/null
    pinned_ge_http_seek_patch >/dev/null
    pinned_ge_mpegvideo_build_patch >/dev/null
    pinned_ge_http_filesize_patch >/dev/null
    pinned_ge_http_chunkend_patch >/dev/null
    pinned_ge_hls_early_seek_patch >/dev/null
    [[ "${PIN_FFMPEG_HTTP_CHUNKEND_PATCH_SHA256:-}" == b170e0eea6e4b364fc5b4616f22e1a2b464662c19ef71f89b0592c806f1250db \
        && "${PIN_FFMPEG_HTTP_CHUNKEND_HTTP_BLOB:-}" == ff99262dec1124c133f1a832b04845e7bf06c020 ]] \
      || fail "SE4-P1 requires its exact HTTP chunked-end module"
    [[ "${PIN_FFMPEG_AAC_PARSER_PATCH_SHA256:-}" == 755d0909e3b1c1873086dfc16b3bb865850c7591453579bac1580be67519e374 \
        && "${PIN_FFMPEG_AAC_PARSER_MAKEFILE_BLOB:-}" == fcf554c93afb1e3f13173909d74273cfee58ee19 \
        && "${PIN_FFMPEG_MPEGVIDEO_MAKEFILE_BLOB:-}" == 6da863e55ba90e9e5dc816a796594f1d8cea6c28 \
        && "$PIN_FFMPEG_CRYPTO_BUILD_MAKEFILE_BLOB" == bd0333dcc2207809189d535729c74f6a3a4f33ba ]] \
      || fail "SE4-P1 requires its exact crypto/MPEGVIDEO/AAC Makefile.in build modules for GE-Proton11-12"
    pinned_ge_aac_parser_build_patch >/dev/null
    [[ "${PIN_GE_SKIP_PATCHES:-}" == patches/wine-hotfixes/pending/rtworkq-dont-hold-queues-section-during-system-queue-shutdown.patch:fa65977bda168c863cffea3faa0643f21c0f990524e7e90fe1105794e501bc7d,patches/protonfixes/0003-gamefix-kingdoms-of-amalur-re-reckoning-d3dcompiler.patch:30f6b9b5bd427eadeb114a748fa4ed6666d11f26e26447f6492daa31d0e17311 ]] \
      || fail "SE4-P3 must skip exactly GE's rtworkq post-series hotfix and protonfixes 0003"
    ;;
  ge-proton11-12-se4-p4)
    # SE4-P4 (2026-11-12): the SE4-P3 pin with PIN_ID and PIN_BUILD_NAME changed and the FFmpeg
    # HLS init-config companion (E6) added; the Wine series is SE4-P3's. Same GE11-12 fields,
    # other FFmpeg modules and skips; the SE4-P1 profile token is reused.
    SELECTED_PROFILE=se4p1
    selected_pin_sha256=c8609d7ee29006ac718c9251a639e30a62a9204005081df186c85e30bcbfb8f3
    # Series digest of patches/series-ge-proton11-12-se4-p4 (pinned_ge_series_digest).
    selected_residual_digest=ae1ee5a108dc861e3de3159ea77c2fc1c0e4931081b722fa59507e1bf69110d9
    [[ "$(pinned_ge_sha256 "$PINNED_GE_CONFIG_PATH")" == "$selected_pin_sha256" \
        && "$PIN_BUILD_NAME" == proton-ge-11-12-rtsp-se4-p4 \
        && "$PIN_KIND" == release-tag \
        && "$PIN_SOURCE_REF" == refs/tags/GE-Proton11-12 \
        && "$PIN_SOURCE_COMMIT" == f85547f0ea51ac356ab42b4de57b927b0044cc85 \
        && "$PIN_SOURCE_TREE" == b8286f4c76ec63a6b2096ab111d04d410bba19de \
        && "$PIN_WINE_COMMIT" == fda79a585939fb7512dc220a11249f9ffe825fcf \
        && "$PIN_WINE_STAGING_COMMIT" == 6cc805ea57132eeaf44764e9213823c9b8d0d300 \
        && "$PIN_FFMPEG_COMMIT" == 9047fa1b084f76b1b4d065af2d743df1b40dfb56 \
        && "$PIN_PATCH_DRIVER_BLOB" == f0d6510f75de69d17a6fb6278fe308541a4e1ef6 \
        && "$PIN_PROTON_LAUNCHER_POLICY" == upstream \
        && "$PIN_WITHOUT_NVIDIA_LIBS" == 0 && "$PIN_WITHOUT_VKLAYERS" == 0 \
        && "$PINNED_GE_HAS_PATCH_OVERLAP" == 0 \
        && -z "${PIN_FFMPEG_DAV1D_PATCH_SHA256:-}${PIN_FFMPEG_DAV1D_MAKEFILE_BLOB:-}" ]] \
      || fail "$PIN_ID immutable GE-Proton11-12 pin or upstream-dav1d policy changed"
    pinned_ge_rtsps_transport_patch >/dev/null
    pinned_ge_http_seek_patch >/dev/null
    pinned_ge_mpegvideo_build_patch >/dev/null
    pinned_ge_http_filesize_patch >/dev/null
    pinned_ge_http_chunkend_patch >/dev/null
    pinned_ge_hls_early_seek_patch >/dev/null
    pinned_ge_hls_init_config_patch >/dev/null
    [[ "${PIN_FFMPEG_HLS_INIT_CONFIG_PATCH_SHA256:-}" == 64e51d21420282a3b25379544a689338ff01ae6435cccd867f258469d0929430 \
        && "${PIN_FFMPEG_HLS_INIT_CONFIG_HLS_BLOB:-}" == 5b1dc4579a040602110d0ffffbc104ea40d9c5da ]] \
      || fail "SE4-P4 requires its exact HLS init-config companion (E6)"
    [[ "${PIN_FFMPEG_HTTP_CHUNKEND_PATCH_SHA256:-}" == b170e0eea6e4b364fc5b4616f22e1a2b464662c19ef71f89b0592c806f1250db \
        && "${PIN_FFMPEG_HTTP_CHUNKEND_HTTP_BLOB:-}" == ff99262dec1124c133f1a832b04845e7bf06c020 ]] \
      || fail "SE4-P1 requires its exact HTTP chunked-end module"
    [[ "${PIN_FFMPEG_AAC_PARSER_PATCH_SHA256:-}" == 755d0909e3b1c1873086dfc16b3bb865850c7591453579bac1580be67519e374 \
        && "${PIN_FFMPEG_AAC_PARSER_MAKEFILE_BLOB:-}" == fcf554c93afb1e3f13173909d74273cfee58ee19 \
        && "${PIN_FFMPEG_MPEGVIDEO_MAKEFILE_BLOB:-}" == 6da863e55ba90e9e5dc816a796594f1d8cea6c28 \
        && "$PIN_FFMPEG_CRYPTO_BUILD_MAKEFILE_BLOB" == bd0333dcc2207809189d535729c74f6a3a4f33ba ]] \
      || fail "SE4-P1 requires its exact crypto/MPEGVIDEO/AAC Makefile.in build modules for GE-Proton11-12"
    pinned_ge_aac_parser_build_patch >/dev/null
    [[ "${PIN_GE_SKIP_PATCHES:-}" == patches/wine-hotfixes/pending/rtworkq-dont-hold-queues-section-during-system-queue-shutdown.patch:fa65977bda168c863cffea3faa0643f21c0f990524e7e90fe1105794e501bc7d,patches/protonfixes/0003-gamefix-kingdoms-of-amalur-re-reckoning-d3dcompiler.patch:30f6b9b5bd427eadeb114a748fa4ed6666d11f26e26447f6492daa31d0e17311 ]] \
      || fail "SE4-P4 must skip exactly GE's rtworkq post-series hotfix and protonfixes 0003"
    ;;
  ge-proton11-12-se4-p6)
    # SE4-P6 (2026-11-14): the SE4-P4 pin with PIN_ID and PIN_BUILD_NAME changed (FFmpeg companions
    # E5 and E6 unchanged); the Wine series is SE4-P4's plus 0046 and 0048. Same GE11-12 fields,
    # other FFmpeg modules and skips; the SE4-P1 profile token is reused.
    SELECTED_PROFILE=se4p1
    selected_pin_sha256=232686e6c5218f75533ef046dbe58e795d40aa363cfbb1e14efff933aa3b5b2a
    # Series digest of patches/series-ge-proton11-12-se4-p6 (pinned_ge_series_digest).
    selected_residual_digest=ba45c48da2bb7c502dc53d437dcb4e91ab5ec66ebd5dfeaee1bf4f0b648c1554
    [[ "$(pinned_ge_sha256 "$PINNED_GE_CONFIG_PATH")" == "$selected_pin_sha256" \
        && "$PIN_BUILD_NAME" == proton-ge-11-12-rtsp-se4-p6 \
        && "$PIN_KIND" == release-tag \
        && "$PIN_SOURCE_REF" == refs/tags/GE-Proton11-12 \
        && "$PIN_SOURCE_COMMIT" == f85547f0ea51ac356ab42b4de57b927b0044cc85 \
        && "$PIN_SOURCE_TREE" == b8286f4c76ec63a6b2096ab111d04d410bba19de \
        && "$PIN_WINE_COMMIT" == fda79a585939fb7512dc220a11249f9ffe825fcf \
        && "$PIN_WINE_STAGING_COMMIT" == 6cc805ea57132eeaf44764e9213823c9b8d0d300 \
        && "$PIN_FFMPEG_COMMIT" == 9047fa1b084f76b1b4d065af2d743df1b40dfb56 \
        && "$PIN_PATCH_DRIVER_BLOB" == f0d6510f75de69d17a6fb6278fe308541a4e1ef6 \
        && "$PIN_PROTON_LAUNCHER_POLICY" == upstream \
        && "$PIN_WITHOUT_NVIDIA_LIBS" == 0 && "$PIN_WITHOUT_VKLAYERS" == 0 \
        && "$PINNED_GE_HAS_PATCH_OVERLAP" == 0 \
        && -z "${PIN_FFMPEG_DAV1D_PATCH_SHA256:-}${PIN_FFMPEG_DAV1D_MAKEFILE_BLOB:-}" ]] \
      || fail "$PIN_ID immutable GE-Proton11-12 pin or upstream-dav1d policy changed"
    pinned_ge_rtsps_transport_patch >/dev/null
    pinned_ge_http_seek_patch >/dev/null
    pinned_ge_mpegvideo_build_patch >/dev/null
    pinned_ge_http_filesize_patch >/dev/null
    pinned_ge_http_chunkend_patch >/dev/null
    pinned_ge_hls_early_seek_patch >/dev/null
    pinned_ge_hls_init_config_patch >/dev/null
    [[ "${PIN_FFMPEG_HLS_INIT_CONFIG_PATCH_SHA256:-}" == 64e51d21420282a3b25379544a689338ff01ae6435cccd867f258469d0929430 \
        && "${PIN_FFMPEG_HLS_INIT_CONFIG_HLS_BLOB:-}" == 5b1dc4579a040602110d0ffffbc104ea40d9c5da ]] \
      || fail "SE4-P6 requires its exact HLS init-config companion (E6)"
    [[ "${PIN_FFMPEG_HTTP_CHUNKEND_PATCH_SHA256:-}" == b170e0eea6e4b364fc5b4616f22e1a2b464662c19ef71f89b0592c806f1250db \
        && "${PIN_FFMPEG_HTTP_CHUNKEND_HTTP_BLOB:-}" == ff99262dec1124c133f1a832b04845e7bf06c020 ]] \
      || fail "SE4-P1 requires its exact HTTP chunked-end module"
    [[ "${PIN_FFMPEG_AAC_PARSER_PATCH_SHA256:-}" == 755d0909e3b1c1873086dfc16b3bb865850c7591453579bac1580be67519e374 \
        && "${PIN_FFMPEG_AAC_PARSER_MAKEFILE_BLOB:-}" == fcf554c93afb1e3f13173909d74273cfee58ee19 \
        && "${PIN_FFMPEG_MPEGVIDEO_MAKEFILE_BLOB:-}" == 6da863e55ba90e9e5dc816a796594f1d8cea6c28 \
        && "$PIN_FFMPEG_CRYPTO_BUILD_MAKEFILE_BLOB" == bd0333dcc2207809189d535729c74f6a3a4f33ba ]] \
      || fail "SE4-P1 requires its exact crypto/MPEGVIDEO/AAC Makefile.in build modules for GE-Proton11-12"
    pinned_ge_aac_parser_build_patch >/dev/null
    [[ "${PIN_GE_SKIP_PATCHES:-}" == patches/wine-hotfixes/pending/rtworkq-dont-hold-queues-section-during-system-queue-shutdown.patch:fa65977bda168c863cffea3faa0643f21c0f990524e7e90fe1105794e501bc7d,patches/protonfixes/0003-gamefix-kingdoms-of-amalur-re-reckoning-d3dcompiler.patch:30f6b9b5bd427eadeb114a748fa4ed6666d11f26e26447f6492daa31d0e17311 ]] \
      || fail "SE4-P6 must skip exactly GE's rtworkq post-series hotfix and protonfixes 0003"
    ;;
  *)
    fail "verify-preparation does not recognize selected pin $PIN_ID"
    ;;
esac
if [[ "$SELECTED_PROFILE" == p19b ]]; then
  [[ "${PIN_FFMPEG_MPEGVIDEO_PATCH_SHA256:-}" == df53226a6d21f40b3337b5a6b38daada83ae216a76d2323e503c382dd5f620f1 \
      && "${PIN_FFMPEG_MPEGVIDEO_MAKEFILE_BLOB:-}" == 10724217d239068e71a57ce806936c91518fc501 \
      && "${PIN_FFMPEG_HTTP_FILESIZE_PATCH_SHA256:-}" == 1248a7b99c46334561a49327ff2fab1e73509879c8f6fa20cf78140dace71d1f \
      && "${PIN_FFMPEG_HTTP_FILESIZE_HTTP_BLOB:-}" == d7e57933651be43fd9ce994533685b9363a35794 \
      && "${PIN_FFMPEG_HLS_EARLY_SEEK_PATCH_SHA256:-}" == 1ea7513c3149c955b26bc708a373bf1b902e255cadb667a9a6f9279763790418 \
      && "${PIN_FFMPEG_HLS_EARLY_SEEK_HLS_BLOB:-}" == 1d2ce08e3e8aa4fad866e82007e57e8c564afe7c ]] \
    || fail "P19b requires its reviewed parser, failed-seek filesize and early HLS seek companions"
  pinned_ge_mpegvideo_build_patch >/dev/null
  pinned_ge_http_filesize_patch >/dev/null
  pinned_ge_hls_early_seek_patch >/dev/null
fi
[[ "$PIN_PACKAGE_RELEASE" == 0 ]] \
  || fail "selected game-test series must remain PACKAGE_RELEASE=0"
expected_default_jobs=16
expected_default_make_jobs=8
if [[ "$PIN_ID" == ge-proton11-7-se2-p16 || "$PIN_ID" == ge-proton11-7-se2-p17 || "$PIN_ID" == ge-proton11-7-se2-p18 || "$PIN_ID" == ge-proton11-7-se2-p19a || "$PIN_ID" == ge-proton11-7-se2-p19b || "$PIN_ID" == ge-proton11-7-se2-p19b2 || "$SELECTED_PROFILE" == p20 || "$SELECTED_PROFILE" == p21 || "$SELECTED_PROFILE" == p22 || "$SELECTED_PROFILE" == p23 || "$SELECTED_PROFILE" == p24 || "$SELECTED_PROFILE" == se2 || "$SELECTED_PROFILE" == se3p1 || "$SELECTED_PROFILE" == se3p2 || "$SELECTED_PROFILE" == se3p3 || "$SELECTED_PROFILE" == se3p4 || "$SELECTED_PROFILE" == se3p5 || "$SELECTED_PROFILE" == se3p6 || "$SELECTED_PROFILE" == se3p7 || "$SELECTED_PROFILE" == se3p8 || "$SELECTED_PROFILE" == se3p9 || "$SELECTED_PROFILE" == se3 || "$SELECTED_PROFILE" == se4p1 ]]; then
  expected_default_jobs=8
  expected_default_make_jobs=4
fi
[[ "$PIN_DEFAULT_JOBS" == "$expected_default_jobs" && "$PIN_DEFAULT_MAKE_JOBS" == "$expected_default_make_jobs" \
    && "$PIN_DEFAULT_NINJA_JOBS" == 2 ]] \
  || fail "scheduler defaults differ from this candidate's reviewed CPU budget"
[[ "$PIN_WINE_STAGING_COMMIT" == 6cc805ea57132eeaf44764e9213823c9b8d0d300 \
    && "$PIN_FFMPEG_COMMIT" == 9047fa1b084f76b1b4d065af2d743df1b40dfb56 ]] \
  || fail "selected shared component pins differ from the reviewed GE delta"
default_schedule="$(pinned_ge_resolve_job_schedule \
  "$PIN_DEFAULT_JOBS" "" "")"
expected_schedule="$(printf '%s\t%s\t2\t%s' "$expected_default_jobs" "$expected_default_make_jobs" "$expected_default_jobs")"
[[ "$default_schedule" == "$expected_schedule" ]] \
  || fail "default scheduler decomposition differs from the selected CPU budget"
lower_schedule="$(pinned_ge_resolve_job_schedule 4 "" "")"
[[ "$lower_schedule" == $'4\t4\t1\t4' ]] \
  || fail "lower global budget did not derive a conservative schedule"
if pinned_ge_validate_job_schedule 16 9 2 >/dev/null 2>&1; then
  fail "oversubscribed 9x2 schedule was accepted under global budget 16"
fi
if pinned_ge_resolve_job_schedule 17 "" "" >/dev/null 2>&1; then
  fail "global schedule above the accepted cap 16 was accepted"
fi
rg -Fq 'unset MAKEFLAGS MFLAGS GNUMAKEFLAGS' \
  "$ROOT_DIR/scripts/build-pinned-ge.sh" \
  || fail "build wrapper does not clear ambient Make parallelism"
if rg -q '^export MAKEFLAGS=' "$ROOT_DIR/scripts/build-pinned-ge.sh"; then
  fail "build wrapper replaces GNU Make's recursive jobserver"
fi
rg -Fq 'SHELL="$HOST_BASH" -j"$MAKE_JOBS"' \
  "$ROOT_DIR/scripts/build-pinned-ge.sh" \
  || fail "build wrapper does not use the orchestrator Make budget"
rg -Fq "'override MAKEOVERRIDES := \$(filter-out SHELL=%,\$(MAKEOVERRIDES))'" \
  "$ROOT_DIR/scripts/build-pinned-ge.sh" \
  || fail "build wrapper does not keep the host SHELL override out of recursive container Make"
rg -Fq 'J="$MAKE_JOBS"' "$ROOT_DIR/scripts/build-pinned-ge.sh" \
  || fail "GE container Make budget is not pinned to orchestrator jobs"
rg -Fq 'NINJA_JOBS="$NINJA_JOBS"' "$ROOT_DIR/scripts/build-pinned-ge.sh" \
  || fail "per-component Ninja budget is not passed to GE"
rg -Fq 'pinned_ge_require_local_steamrt_image "$PODMAN_BIN"' \
  "$ROOT_DIR/scripts/build-pinned-ge.sh" \
  || fail "build wrapper does not bind the local SteamRT image ID"
rg -Fq 'DOCKER_OPTS=--pull=never' "$ROOT_DIR/scripts/build-pinned-ge.sh" \
  || fail "build wrapper permits an implicit SteamRT image pull"
rg -Fq -- '--network=none' "$ROOT_DIR/scripts/build-pinned-ge.sh" \
  || fail "build wrapper permits container network access"
rg -Fq 'REEXEC_ARGS+=(--resume)' "$ROOT_DIR/scripts/build-pinned-ge.sh" \
  || fail "resume mode is lost during the low-impact re-exec"
rg -Fq 'pinned_ge_require_configure_state' "$ROOT_DIR/scripts/build-pinned-ge.sh" \
  || fail "resume mode does not require a configure fingerprint"
rg -Fq 'Reusing verified configure result:' "$ROOT_DIR/scripts/build-pinned-ge.sh" \
  || fail "resume mode does not identify configure-result reuse"
rg -Fq 'pinned-resume-all-source' "$ROOT_DIR/scripts/build-pinned-ge.sh" \
  || fail "resume mode omits the dedicated all-source Make pass"
rg -Fq 'pinned_ge_require_resume_source_barrier' \
  "$ROOT_DIR/scripts/build-pinned-ge.sh" \
  || fail "resume mode omits the post-source deletion/rsync barrier"
for record in \
    'build_invocation_version\t6' \
    'source_path\t%s' \
    'build_path\t%s' \
    'state_path\t%s' \
    'cache_home\t%s' \
    'steamrt_image_id\t%s' \
    'scheduler_policy\tmake-times-ninja-at-most-global' \
    'recursive_make_parallelism\tjobserver' \
    'ge_media_cleanup_manifest_sha256\t%s' \
    'ge_patch_overlap_mode\tstock-effective-exact-skip' \
    'ge_patch_overlap_manifest_sha256\t%s' \
    'ge_patch_overlap_audit_sha256\t%s' \
    'proton_launcher_patch_sha256\t%s' \
    'ffmpeg_security_fix_commits\t%s' \
    'ffmpeg_security_series_digest\t%s' \
    'ffmpeg_security_patch_audit_sha256\t%s' \
    'ffmpeg_repo_state_sha256\t%s' \
    'ffmpeg_crypto_build_patch_sha256\t%s' \
    'ffmpeg_crypto_build_audit_sha256\t%s' \
    'rtsp_hook_order\tafter-ge-video-rework-before-autoreconf' \
    'final_diff_check_baseline_match\tpassed' \
    'final_winegstreamer_external_references\t0'; do
  rg -Fq "$record" "$ROOT_DIR/scripts/build-pinned-ge.sh" \
    || fail "build invocation omits scheduler record: $record"
done
rg -Fq 'pinned_ge_validate_job_schedule' \
  "$ROOT_DIR/scripts/verify-pinned-ge-artifact.sh" \
  || fail "artifact verifier does not revalidate the recorded scheduler"
artifact_verifier="$ROOT_DIR/scripts/verify-pinned-ge-artifact.sh"
for privacy_gate in \
    'python3 - "$TOOL_DIR" "${HOME:-}"' \
    'LLVM_MINGW_PREFIX = b"/home/runner/work/llvm-mingw/"' \
    'WINDOWS_PROFILE_ALLOWLIST = {b"public", b"steamuser"}' \
    'rb"|(?P<root>/root)(?=[/\\]))"' \
    'home_pattern = re.compile(re.escape(builder_home), re.IGNORECASE)' \
    'UTF16_LE_ASCII' \
    'UTF16_BE_ASCII' \
    'mmap.mmap(' \
    'os.scandir(directory)' \
    'absolute symlink:' \
    'out-of-root symlink:' \
    'broken symlink:' \
    'special file (mode' \
    'setuid/setgid file:' \
    'world-writable file:' \
    'privacy scan could not read every regular file' \
    'artifact filesystem or privacy validation failed'; do
  rg -Fq -- "$privacy_gate" "$artifact_verifier" \
    || fail "artifact verifier omits fail-closed privacy gate: $privacy_gate"
done
for script in build-pinned-ge.sh verify-pinned-ge-artifact.sh; do
  rg -Fq 'pinned_ge_require_prepared_media_provenance "$SOURCE_DIR" "$STATE_DIR"' \
    "$ROOT_DIR/scripts/$script" \
    || fail "$script does not validate prepared media-cleanup provenance"
  rg -Fq 'pinned_ge_require_prepared_patch_overlap_provenance' \
    "$ROOT_DIR/scripts/$script" \
    || fail "$script does not validate inherited GE patch-overlap provenance"
  rg -Fq 'pinned_ge_require_prepared_ffmpeg_security_provenance' \
    "$ROOT_DIR/scripts/$script" \
    || fail "$script does not validate prepared FFmpeg security provenance"
  rg -Fq 'pinned_ge_require_prepared_ffmpeg_crypto_build_provenance' \
    "$ROOT_DIR/scripts/$script" \
    || fail "$script does not validate prepared FFmpeg crypto-build provenance"
done
if rg -Fq 'git -C "$SOURCE_DIR/wine" diff --check' \
    "$ROOT_DIR/scripts/build-pinned-ge.sh"; then
  fail "build wrapper still rejects GE's exact recorded Wine diff-check baseline"
fi
prepared_source="${PREPARED_SOURCE:-$(pinned_ge_default_source)}"
prepared_state="${PREPARED_STATE:-$(pinned_ge_default_state_dir)}"
if [[ -e "$prepared_source/wine/.git" \
    && -f "$prepared_state/prepared-source.tsv" ]]; then
  pinned_ge_require_prepared_media_provenance \
    "$prepared_source" "$prepared_state" "$PATCH_SERIES"
  if [[ "$PINNED_GE_HAS_PATCH_OVERLAP" == 1 ]]; then
    pinned_ge_require_prepared_patch_overlap_provenance \
      "$prepared_source" "$prepared_state"
  fi
  printf 'Prepared media cleanup, diff baseline, and zero-reference provenance passed.\n'
else
  printf 'NOTE: complete pinned prepared tree is unavailable; live media provenance check skipped.\n'
fi
printf 'Pinned scheduler uses global=%s, Make=%s, Ninja=%s and rejects product overflow.\n' \
  "$PIN_DEFAULT_JOBS" "$PIN_DEFAULT_MAKE_JOBS" "$PIN_DEFAULT_NINJA_JOBS"
series_entries="$(pinned_ge_series_entries \
  "$ROOT_DIR/patches" "$PATCH_SERIES")"
[[ -n "$series_entries" ]] || fail "pinned Alpha patch series is empty"
mapfile -t series_paths <<<"$series_entries"
expected_base_series=(
  experimental/0001-winedmo-open-rtsp-over-tcp.patch
  experimental/0002-winedmo-interrupt-network-demux-and-report-live-seekability.patch
  experimental/0003-winedmo-use-destroy-params-for-wow64-demuxer.patch
  experimental/0004-winedmo-async-http-and-repair-vod-seeking.patch
  experimental/0005-winedmo-stream-progressive-http-vod.patch
  experimental/0006-winedmo-recover-interrupted-vod-seeks.patch
  experimental/0007-mf-reprime-and-resume-after-vod-seeks.patch
  experimental/0008-winedmo-preserve-audio-timeline-across-flush.patch
  experimental/0009-mf-sar-preserve-running-state-across-flush.patch
  experimental/0011-mf-fix-initial-presentation-clock-offset.patch
  experimental/0013-mfmediaengine-reconcile-pause-scrub-intent.patch
  experimental/0014-mfmediaengine-preserve-pending-start-position.patch
  experimental/0015-mf-order-immediate-replacement-start.patch
  experimental/0017-winedmo-propagate-terminal-network-read-errors.patch
  experimental/0018-winewayland-advertise-wine-vr-device-extensions.patch
)
if [[ "$SELECTED_PROFILE" == p20 || "$SELECTED_PROFILE" == p21 || "$SELECTED_PROFILE" == p22 || "$SELECTED_PROFILE" == p23 || "$SELECTED_PROFILE" == p24 || "$SELECTED_PROFILE" == se2 || "$SELECTED_PROFILE" == se3p1 || "$SELECTED_PROFILE" == se3p2 || "$SELECTED_PROFILE" == se3p3 || "$SELECTED_PROFILE" == se3p4 || "$SELECTED_PROFILE" == se3p5 || "$SELECTED_PROFILE" == se3p6 || "$SELECTED_PROFILE" == se3p7 || "$SELECTED_PROFILE" == se3p8 || "$SELECTED_PROFILE" == se3p9 || "$SELECTED_PROFILE" == se3 || "$SELECTED_PROFILE" == se4p1 ]]; then
  # Digest covers every ordered residual path AND every patch byte; no count
  # or historical patch basename can stand in for this composition identity.
  [[ "$(pinned_ge_series_digest "$ROOT_DIR/patches" "$PATCH_SERIES")" \
      == "$selected_residual_digest" ]] \
    || fail "$PIN_ID requires its exact reviewed GE-Proton11-9 residual composition"
  expected_base_series=()
elif [[ "$SELECTED_PROFILE" == p19b ]]; then
  # Bind every ordered path AND patch byte to the reviewed clean composition.
  # This replaces only P19b's legacy diagnostic-series list, not other profiles.
  expected_p19b_count=69
  expected_p19b_digest=9b50b6f64e71c26969c8cace8a4e283034deb5a3504c39aa47fadec170855228
  if [[ "$PIN_ID" == ge-proton11-7-se2-p19b2 ]]; then
    expected_p19b_count=70
    expected_p19b_digest=c3e368014b33e0697d0d091306c863dd6d90fdbf017d72f425d4c470cc4c7ae3
  fi
  [[ "${#series_paths[@]}" == "$expected_p19b_count" \
      && "$(pinned_ge_series_digest "$ROOT_DIR/patches" "$PATCH_SERIES")" \
        == "$expected_p19b_digest" ]] \
    || fail "$PIN_ID requires its exact reviewed $expected_p19b_count-patch diagnostic-free composition"
  expected_base_series=()
elif [[ "$SELECTED_PROFILE" == a319 || "$SELECTED_PROFILE" == a320 || "$SELECTED_PROFILE" == a321 || "$SELECTED_PROFILE" == a322 || "$SELECTED_PROFILE" == a323 ]]; then
  expected_base_series=("${expected_base_series[@]/experimental\//ge-proton11-6/}")
  expected_base_series+=(ge-proton11-6/0020-quiet-ge-media-diagnostics.patch)
  if [[ "$SELECTED_PROFILE" == a320 || "$SELECTED_PROFILE" == a321 || "$SELECTED_PROFILE" == a322 || "$SELECTED_PROFILE" == a323 ]]; then
    expected_base_series[6]=ge-proton11-6-a320/0007-mf-reprime-and-resume-after-vod-seeks.patch
    expected_base_series[13]=ge-proton11-6-a320/0017-winedmo-propagate-terminal-network-read-errors.patch
    expected_base_series+=(
      ge-proton11-6-a320/0022-mfmediaengine-preserve-selected-frame-tick-result.patch
      ge-proton11-6-a320/0023-mfmediaengine-check-seekability-before-recovery-reset.patch
    )
    if [[ "$PIN_ID" == ge-proton11-6-a322-r2 || "$SELECTED_PROFILE" == a323 ]]; then
      expected_base_series+=(ge-proton11-6-a322-r2/0025-winedmo-normalize-hls-vod-timeline.patch)
    fi
    if [[ "$SELECTED_PROFILE" == a323 ]]; then
      expected_base_series+=(ge-proton11-6-a323/0026-mf-replenish-output-buffers-after-preroll.patch)
    fi
    expected_series_count=$((${#expected_base_series[@]} + 1 + ${#selected_module_series[@]}))
    [[ "${#series_paths[@]}" == "$expected_series_count" ]] \
      || fail "$PIN_ID requires the reviewed $expected_series_count-patch GE-Proton11-6 series"
    if [[ "$SELECTED_PROFILE" == a321 || "$SELECTED_PROFILE" == a322 || "$SELECTED_PROFILE" == a323 ]]; then
      media_profile=$SELECTED_PROFILE
      [[ "$media_profile" != a323 ]] || media_profile=a322
      expected_base_series[4]=ge-proton11-6-$media_profile/0005-winedmo-stream-progressive-http-vod.patch
    fi
  else
    [[ "${#series_paths[@]}" == 17 ]] \
      || fail "A3.19 requires the seventeen-patch GE-Proton11-6 series"
  fi
  expected_base_series+=(ge-proton11-6/0019-winedmo-trace-bounded-rtsp-drain-state.patch)
  expected_base_series+=("${selected_module_series[@]}")
else
  [[ "${#series_paths[@]}" == 15 || "${#series_paths[@]}" == 16 ]] \
    || fail "historical pin requires its 15/16-patch series; select --series patches/series-ge-proton11-3"
fi
if [[ "$PIN_ID" == ge-master-20260913-se2-p13 || "$PIN_ID" == ge-proton11-7-se2-p14 || "$PIN_ID" == ge-proton11-7-se2-p15 || "$PIN_ID" == ge-proton11-7-se2-p16 || "$PIN_ID" == ge-proton11-7-se2-p17 || "$PIN_ID" == ge-proton11-7-se2-p18 || "$PIN_ID" == ge-proton11-7-se2-p19a ]]; then
  expected_base_series[12]=ge-master-20260913-se2-p13/0015-mf-order-immediate-replacement-start.patch
fi
for index in "${!expected_base_series[@]}"; do
  [[ "${series_paths[$index]}" == "${expected_base_series[$index]}" ]] \
    || fail "reviewed Wine media base changed at series position $((index + 1))"
done
if [[ "${#series_paths[@]}" == 16 ]]; then
  [[ "${series_paths[15]}" \
      == experimental/0019-winedmo-trace-bounded-rtsp-drain-state.patch ]] \
    || fail "bounded drain diagnostic is not the final Wine media patch"
elif [[ "$SELECTED_PROFILE" == a314 || "$SELECTED_PROFILE" == a315 \
    || "$SELECTED_PROFILE" == a316 ]]; then
  fail "selected diagnostic candidate requires the complete sixteen-patch series"
fi
current_series_digest="$(
  pinned_ge_series_digest "$ROOT_DIR/patches" "$PATCH_SERIES"
)"
if [[ "$SELECTED_PROFILE" == a315 ]]; then
  [[ "$PIN_BUILD_NAME" \
      == "Proton-RTSP-on-GE11-A3.15-GE-Proton11-3-${current_series_digest:0:8}" ]] \
    || fail "A3.15 build name does not identify the active Wine series digest"
elif [[ "$SELECTED_PROFILE" == a316 ]]; then
  [[ "$PIN_BUILD_NAME" \
      == "Proton-RTSP-on-GE11-A3.16-GE-Proton11-3-${current_series_digest:0:8}" ]] \
    || fail "A3.16 build name does not identify the active Wine series digest"
fi
for a312_gate in \
    scripts/prepare-pinned-ge-source.sh \
    scripts/build-pinned-ge.sh \
    scripts/verify-pinned-ge-artifact.sh; do
  rg -Fq -- '--require-a311-series' "$ROOT_DIR/$a312_gate" \
    || fail "A3.11 foundation audit is not fail-closed in $a312_gate"
  rg -Fq -- '--require-a312-series' "$ROOT_DIR/$a312_gate" \
    || fail "A3.12 source audit is not fail-closed in $a312_gate"
done
for git_patch_gate in \
    'git apply --check --whitespace=error-all' \
    'if ! git apply --numstat -z'; do
  rg -Fq -- "$git_patch_gate" "$ROOT_DIR/scripts/apply-pinned-rtsp-series.sh" \
    || fail "strict RTSP patch hook omits fail-closed Git gate: $git_patch_gate"
done
rg -Fq -- 'patch -Np1 --dry-run --batch --fuzz=0' \
  "$ROOT_DIR/scripts/apply-pinned-rtsp-series.sh" \
  || fail "strict RTSP patch hook omits fail-closed GNU dry-run gate"
for overlap_gate in \
    'pinned_ge_require_source_identity "$SOURCE_ROOT"' \
    'pinned_ge_require_registered_submodules "$SOURCE_ROOT"' \
    'GE protonfixes patch directory differs from the exact two-patch overlap' \
    'patch -Np1 --batch --fuzz=0' \
    'DECLARED_INTERMEDIATE_BLOB' \
    'RESIDUAL_DIFF_SHA256' \
    'stock-effective-exact-skip' \
    'source_change\tnone'; do
  rg -Fq -- "$overlap_gate" \
    "$ROOT_DIR/scripts/audit-pinned-ge-patch-overlap.sh" \
    || fail "GE patch-overlap hook omits fail-closed gate: $overlap_gate"
done
rg -Fq 'expected exactly one GE protonfixes patch application point' \
  "$ROOT_DIR/scripts/prepare-pinned-ge-source.sh" \
  || fail "generated GE driver does not replace only the reviewed overlap call"
ffmpeg_security_records="$(pinned_ge_ffmpeg_security_series_records \
  "$ROOT_DIR/patches/ffmpeg-security" \
  "$ROOT_DIR/patches/ffmpeg-security/series")"
[[ "$(wc -l <<<"$ffmpeg_security_records")" == 4 ]] \
  || fail "FFmpeg security series must contain the exact four reviewed patches"
ffmpeg_security_paths="$(pinned_ge_ffmpeg_security_touched_paths \
  "$ROOT_DIR/patches/ffmpeg-security" \
  "$ROOT_DIR/patches/ffmpeg-security/series")"
[[ "$ffmpeg_security_paths" == \
    $'libavcodec/magicyuv.c\nlibavformat/version_major.h' ]] \
  || fail "FFmpeg security series changed paths outside the reviewed pair"
for security_gate in \
    'apply --check' \
    '--whitespace=error-all' \
    'PIN_FFMPEG_SECURITY_MAGICYUV_BLOB' \
    'PIN_FFMPEG_SECURITY_TLS_VERSION_BLOB' \
    'pinned_ge_repo_state_digest "$SOURCE_DIR/ffmpeg"'; do
  rg -Fq -- "$security_gate" \
    "$ROOT_DIR/scripts/apply-pinned-ffmpeg-security-series.sh" \
    || fail "strict FFmpeg application omits gate: $security_gate"
done
rg -Fq 'CONFIG_MAGICYUV_DECODER 1' \
  <(tr '\n' ' ' <"$ROOT_DIR/scripts/verify-pinned-ge-artifact.sh") \
  || fail "artifact verifier does not bind the enabled MagicYUV decoder to its fixes"
rg -Fq 'pinned_ge_require_exact_ffmpeg_define' \
  "$ROOT_DIR/scripts/verify-pinned-ge-artifact.sh" \
  || fail "artifact verifier does not use exact-one macro assertions"
rg -Fq 'pinned_ge_require_ffmpeg_config_surface' \
  "$ROOT_DIR/scripts/verify-pinned-ge-artifact.sh" \
  || fail "artifact verifier does not invoke the exact FFmpeg surface gate"
crypto_build_record="$(pinned_ge_ffmpeg_crypto_build_patch_record \
  "$ROOT_DIR/patches/ffmpeg-build" "$(pinned_ge_ffmpeg_crypto_build_series)")"
[[ "$(wc -l <<<"$crypto_build_record")" == 1 ]] \
  || fail "FFmpeg crypto-build series must remain exactly one pinned patch"
for tls_backend_fact in \
    'CONFIG_HLS_DEMUXER' 'CONFIG_CRYPTO_PROTOCOL' 'CONFIG_GNUTLS' \
    'CONFIG_LIBZMQ' 'CONFIG_ZMQ_FILTER' \
    'CONFIG_FFMPEG CONFIG_FFPLAY CONFIG_FFPROBE' \
    'CONFIG_TLS_PROTOCOL' 'CONFIG_LIBTLS' 'CONFIG_MBEDTLS' \
    'CONFIG_OPENSSL' 'CONFIG_SCHANNEL' 'CONFIG_SECURETRANSPORT' \
    'CONFIG_FILE_PROTOCOL CONFIG_DATA_PROTOCOL CONFIG_HTTPPROXY_PROTOCOL'; do
  rg -Fq "$tls_backend_fact" \
    "$ROOT_DIR/scripts/pinned-ge-common.sh" \
    || fail "artifact verifier omits TLS backend binding: $tls_backend_fact"
done
rg -Fq -- "-iname '*zmqsend*'" \
  "$ROOT_DIR/scripts/verify-pinned-ge-artifact.sh" \
  || fail "artifact verifier does not reject a packaged zmqsend tool"
for source_state_gate in \
    'prepared_source_version' \
    'pinned_ge_require_source_identity "$SOURCE_DIR"' \
    'pinned_ge_require_registered_submodules "$SOURCE_DIR"' \
    'wine_repo_state_sha256' 'dxvk_repo_state_sha256' \
    'protonfixes_repo_state_sha256' 'ffmpeg_repo_state_sha256'; do
  rg -Fq "$source_state_gate" \
    "$ROOT_DIR/scripts/verify-pinned-ge-artifact.sh" \
    || fail "artifact verifier omits prepared source-state gate: $source_state_gate"
done
rg -Fq 'verify-artifact-archive.py' \
  "$ROOT_DIR/scripts/verify-pinned-ge-artifact.sh" \
  || fail "artifact verifier does not compare the archive with the game-test tree"
for archive_gate in \
    'duplicate archive member' \
    'unsupported archive node type' \
    'archive symlink differs' \
    'archive mode differs' \
    'archive payload differs' \
    'non-zero payload after its tar end marker' \
    'archive omits'; do
  rg -Fq "$archive_gate" "$ROOT_DIR/scripts/verify-artifact-archive.py" \
    || fail "archive/tree verifier omits fail-closed gate: $archive_gate"
done
build_contrib_manifest="$(pinned_ge_build_contrib_manifest_path)"
build_contrib_entries="$(pinned_ge_build_contrib_entries "$build_contrib_manifest")"
mapfile -t parsed_build_contrib_entries <<<"$build_contrib_entries"
manifest_build_contrib_entry_count="$(
  awk -F '\t' '$1 == "entry" { count++ } END { print count + 0 }' \
    "$build_contrib_manifest"
)"
[[ "${#parsed_build_contrib_entries[@]}" \
    == "$manifest_build_contrib_entry_count" ]] \
  || fail \
    "parsed build-contrib entry count differs from the selected pin manifest"
if [[ "$PIN_PROTON_LAUNCHER_POLICY" == scoped-xrizer ]]; then
[[ -f "$PROTON_LAUNCHER_PATCH" && ! -L "$PROTON_LAUNCHER_PATCH" ]] \
  || fail "separate Proton XRizer launcher patch is absent or unsafe"
if [[ -e "$prepared_source/.git" \
    && -f "$prepared_state/prepared-source.tsv" ]]; then
  git -C "$prepared_source" apply --check --reverse -- "$PROTON_LAUNCHER_PATCH"
  [[ "$(pinned_ge_state_value \
      "$prepared_state/prepared-source.tsv" proton_launcher_patch_sha256)" \
      == "$(pinned_ge_sha256 "$PROTON_LAUNCHER_PATCH")" ]] \
    || fail "prepared launcher-patch digest differs from project patch"
fi
elif [[ -e "$prepared_source/.git" && -f "$prepared_state/prepared-source.tsv" ]]; then
  pinned_ge_require_upstream_launcher "$prepared_source" "$prepared_source/proton"
  [[ "$(pinned_ge_state_value "$prepared_state/prepared-source.tsv" proton_launcher_patch)" == none \
      && "$(pinned_ge_state_value "$prepared_state/prepared-source.tsv" proton_launcher_patch_sha256)" \
        == "$(pinned_ge_launcher_patch_sha256)" ]] \
    || fail "prepared upstream launcher has inconsistent no-patch provenance"
fi
if [[ "$PIN_PROTON_LAUNCHER_POLICY" == upstream ]]; then
  printf '%s Wine media patches; upstream Proton launcher (no XRizer compatibility flag). PACKAGE_RELEASE=0.\n' "${#series_paths[@]}"
elif [[ "$SELECTED_PROFILE" == a320 || "$SELECTED_PROFILE" == a321 || "$SELECTED_PROFILE" == a322 || "$SELECTED_PROFILE" == a323 ]]; then
  printf '%s %s GE-Proton11-6 Wine media patches and the separate Proton XRizer launcher patch selected under PACKAGE_RELEASE=0.\n' "${#series_paths[@]}" "$SELECTED_PROFILE"
elif [[ "$SELECTED_PROFILE" == a319 ]]; then
  printf 'Seventeen GE-Proton11-6 Wine media patches and the separate Proton XRizer launcher patch selected under PACKAGE_RELEASE=0.\n'
elif [[ "${#series_paths[@]}" == 16 ]]; then
  printf 'The reviewed fifteen-patch Wine media foundation, the bounded drain diagnostic, and one separate Proton XRizer launcher patch are active under PACKAGE_RELEASE=0.\n'
else
  printf 'Fifteen Wine media patches and one separate Proton XRizer launcher patch are active under PACKAGE_RELEASE=0.\n'
fi

(
  PINNED_GE_CONFIG="$ROOT_DIR/config/ge-master-snapshot-20260713-a311.env"
  pinned_ge_load_config
  old_contrib_manifest="$(pinned_ge_build_contrib_manifest_path)"
  old_contrib_entries="$(pinned_ge_build_contrib_entries "$old_contrib_manifest")"
  [[ "$PIN_BUILD_NAME" == Proton-RTSP-on-GE11-A3.11-ReplacementClock-9fad3bbe \
      && "$PIN_SOURCE_COMMIT" == 9fad3bbe270409e67a8d2f4d123afc73d848306a \
      && "$PINNED_GE_HAS_RETAINED_RESUME" == 1 \
      && "$PINNED_GE_HAS_PATCH_OVERLAP" == 0 \
      && "$(wc -l <<<"$old_contrib_entries")" == 6 ]] \
    || fail "immutable old-base A3.11 control no longer loads independently"
)
(
  PINNED_GE_CONFIG="$ROOT_DIR/config/ge-master-snapshot-20260713.env"
  pinned_ge_load_config
  [[ "$PIN_SCHEMA_VERSION" == 4 \
      && "$PIN_BUILD_NAME" == Proton-RTSP-on-GE11-A3-9fad3bbe \
      && -z "${PIN_FFMPEG_SECURITY_FIX_COMMITS:-}" ]] \
    || fail "immutable legacy A3 config no longer loads as schema 4"
)
printf 'Old-base A3/A3.11 controls remain selectable; the refreshed schema-5 pin retains the exact FFmpeg security series.\n'

for privacy_fixture in \
    '/home/example/project' \
    '/Users/example/project' \
    'HOME=/home/example/project' \
    '](/home/example/project)' \
    'file:///home/example/project'; do
  printf '%s\n' "$privacy_fixture" \
    | rg --pcre2 -q -i "$PROJECT_HOME_PATTERN" \
    || fail "project privacy gate missed fixture: $privacy_fixture"
done
if printf 'https://vrchat.com/home/launch?worldId=fixture\n' \
    | rg --pcre2 -q -i "$PROJECT_HOME_PATTERN"; then
  fail "project privacy gate mistakes an HTTPS path for a local home path"
fi
if privacy_candidates="$(git -C "$ROOT_DIR" grep -I -n -i -E \
    '/home/|/Users/' -- . \
    ':!scripts/verify-preparation.sh' \
    ':!scripts/verify-pinned-ge-artifact.sh')"; then
  # Some Nix Git builds omit PCRE. Keep the same tracked-text/privacy scope,
  # using the already-required ripgrep PCRE engine for the precise predicate.
  if privacy_matches="$(printf '%s\n' "$privacy_candidates" \
      | rg --pcre2 -i "$PROJECT_HOME_PATTERN")"; then
    printf '%s\n' "$privacy_matches" >&2
    fail "personal absolute path found in project-facing text"
  else
    privacy_status=$?
    [[ "$privacy_status" == 1 ]] \
      || fail "could not filter tracked public text for personal paths"
  fi
else
  privacy_status=$?
  [[ "$privacy_status" == 1 ]] \
    || fail "could not scan every tracked public text file for personal paths"
fi

"$ROOT_DIR/tests/media/generate-fixture.sh" >/dev/null
python3 "$ROOT_DIR/tests/sar-flush-control/test_model.py" >/dev/null
python3 "$ROOT_DIR/tests/clock-start-control/test_model.py" >/dev/null
python3 "$ROOT_DIR/tests/pcm-probe-control/test_model.py" >/dev/null
python3 "$ROOT_DIR/tests/tooling/test_launcher_policy.py" >/dev/null
python3 "$ROOT_DIR/tests/tooling/test_preparation_profile.py" >/dev/null
python3 "$ROOT_DIR/tests/tooling/test_p19a_profile.py" >/dev/null
python3 "$ROOT_DIR/tests/tooling/test_p19b_profile.py" >/dev/null
python3 "$ROOT_DIR/tests/tooling/test_p19b2_profile.py" >/dev/null
python3 "$ROOT_DIR/tests/tooling/test_p21_profile.py" >/dev/null
python3 "$ROOT_DIR/tests/tooling/test_p22_profile.py" >/dev/null
python3 "$ROOT_DIR/tests/tooling/test_crypto_series_selection.py" >/dev/null
python3 "$ROOT_DIR/tests/tooling/test_container_cpu_budget.py" >/dev/null
python3 "$ROOT_DIR/tests/tooling/test_ge119_hls_classification.py" >/dev/null
python3 "$ROOT_DIR/tests/network-terminal-error/test_seek_policy.py" >/dev/null
python3 "$ROOT_DIR/tests/tooling/test_wine_added_files.py" >/dev/null
python3 "$ROOT_DIR/tests/tooling/test_wine_fresh_setup.py" >/dev/null
python3 "$ROOT_DIR/tests/wine-header-compile/test_fresh_setup.py" >/dev/null
python3 "$ROOT_DIR/tests/avpro-audio-state/test_model.py" >/dev/null
python3 "$ROOT_DIR/tests/media-engine-pause-scrub/test_model.py" >/dev/null
python3 "$ROOT_DIR/tests/source-replacement-lifecycle/test_model.py" --series "$PATCH_SERIES" >/dev/null
if [[ ( "$SELECTED_PROFILE" == p20 || "$SELECTED_PROFILE" == p21 || "$SELECTED_PROFILE" == p22 || "$SELECTED_PROFILE" == p23 || "$SELECTED_PROFILE" == p24 || "$SELECTED_PROFILE" == se2 || "$SELECTED_PROFILE" == se3p1 || "$SELECTED_PROFILE" == se3p2 || "$SELECTED_PROFILE" == se3p3 || "$SELECTED_PROFILE" == se3p4 || "$SELECTED_PROFILE" == se3p5 || "$SELECTED_PROFILE" == se3p6 || "$SELECTED_PROFILE" == se3p7 || "$SELECTED_PROFILE" == se3p8 || "$SELECTED_PROFILE" == se3p9 || "$SELECTED_PROFILE" == se3 || "$SELECTED_PROFILE" == se4p1 ) && -n "${PREPARED_SOURCE:-}" ]]; then
  # The consolidated series retains the source contracts, not the old patch
  # filenames. Audit their actual postimages; no runtime oracle is changed.
  bash "$ROOT_DIR/scripts/audit-patched-wine.sh" \
    --wine-tree "$prepared_source/wine" --series "$PATCH_SERIES" \
    --require-alpha-series --require-a312-series >/dev/null
fi
if [[ "$SELECTED_PROFILE" == a319 || "$SELECTED_PROFILE" == a320 || "$SELECTED_PROFILE" == a321 || "$SELECTED_PROFILE" == a322 || "$SELECTED_PROFILE" == a323 || "$SELECTED_PROFILE" == p19b ]]; then
  integration_source_args=()
  if [[ -n "${PREPARED_SOURCE:-}" ]]; then
    [[ -f "$prepared_source/wine/dlls/mf/session.c" \
        && -f "$prepared_source/wine/dlls/mfmediaengine/main.c" \
        && -f "$prepared_source/wine/dlls/mfmediaengine/video_frame_sink.c" \
        && -f "$prepared_source/wine/dlls/winedmo/unix_demuxer.c" ]] \
      || fail "explicit PREPARED_SOURCE lacks the Wine sources required by integration tests"
    integration_source_args=(--wine-tree "$prepared_source/wine")
  fi
  python3 "$ROOT_DIR/tests/ge-proton11-6/test_integration.py" \
    "${integration_source_args[@]}" >/dev/null
  if [[ "$SELECTED_PROFILE" == a320 || "$SELECTED_PROFILE" == a321 || "$SELECTED_PROFILE" == a322 || "$SELECTED_PROFILE" == a323 || "$SELECTED_PROFILE" == p19b ]]; then
    for regression in test_seek_restart.py test_frame_tick.py test_recovery_seek.py; do
      python3 "$ROOT_DIR/tests/vod-control/$regression" \
        "${integration_source_args[@]}" >/dev/null
    done
    python3 "$ROOT_DIR/tests/network-terminal-error/test_seek_failure.py" \
      "${integration_source_args[@]}" >/dev/null
  fi
  if [[ "$SELECTED_PROFILE" == a323 || "$SELECTED_PROFILE" == p19b ]]; then
    python3 "$ROOT_DIR/tests/vod-control/test_preroll_buffers.py" \
      "${integration_source_args[@]}" >/dev/null
  fi
  if [[ ( "$PIN_ID" == ge-master-20260913-se2-p8 || "$PIN_ID" == ge-master-20260913-se2-p9 || "$PIN_ID" == ge-master-20260913-se2-p10 || "$PIN_ID" == ge-master-20260913-se2-p11 || "$PIN_ID" == ge-master-20260913-se2-p12 || "$PIN_ID" == ge-master-20260913-se2-p13 || "$PIN_ID" == ge-proton11-7-se2-p14 || "$PIN_ID" == ge-proton11-7-se2-p15 || "$PIN_ID" == ge-proton11-7-se2-p16 || "$PIN_ID" == ge-proton11-7-se2-p17 || "$PIN_ID" == ge-proton11-7-se2-p18 || "$PIN_ID" == ge-proton11-7-se2-p19a || "$SELECTED_PROFILE" == p19b ) && -n "${PREPARED_SOURCE:-}" ]]; then
    python3 "$ROOT_DIR/tests/progressive-http-vod/test_http_policy_audit.py" \
      "${integration_source_args[@]}" >/dev/null
    master_test_cc="${PREPARATION_TEST_CC:-$(command -v cc || true)}"
    if [[ -n "$master_test_cc" ]]; then
      master_control_args=()
      if [[ "$SELECTED_PROFILE" == p19b ]]; then
        master_control_args=(--sar-demand-patch "$ROOT_DIR/patches/ge-proton11-7-se2-p19b/0043-mf-rearm-audio-sample-demand-after-flush.patch")
      fi
      python3 "$ROOT_DIR/tests/session-seek-eos/test_master_controls.py" \
        "${integration_source_args[@]}" --cc "$master_test_cc" "${master_control_args[@]}" >/dev/null
    else
      printf 'NOTE: native compiler unavailable; P8 master lifecycle controls skipped (set PREPARATION_TEST_CC).\n'
    fi
    # Dolby and held-marker tests start from pre-patch controls, not this
    # already integrated tree. Their separate qualification receipts remain
    # required; passing a patched tree would destroy those negative controls.
  fi
fi
PYTHONDONTWRITEBYTECODE=1 \
  python3 "$ROOT_DIR/tests/media-engine-pause-scrub/test_runtime_parser.py" >/dev/null
"$ROOT_DIR/tests/media-engine-pause-scrub/test_runner_guards.sh" >/dev/null
"$ROOT_DIR/tests/tooling/config-security.sh"
"$ROOT_DIR/tests/tooling/bootstrap-ownership.sh"
"$ROOT_DIR/tests/tooling/archive_security.py"
"$ROOT_DIR/tests/tooling/resume-build.sh"
bash "$ROOT_DIR/tests/tooling/submodule-reference.sh"
bash "$ROOT_DIR/tests/tooling/prefetch-build-contrib.sh"
python3 "$ROOT_DIR/tests/tooling/test_upstream_component.py"
python3 "$ROOT_DIR/tests/tooling/test_media_provenance.py"
python3 "$ROOT_DIR/tests/tooling/test_master_media_cleanup.py"
python3 "$ROOT_DIR/tests/tooling/test_master_mono_preparation.py"
python3 "$ROOT_DIR/tests/tooling/test_nvml_build_input.py"
python3 "$ROOT_DIR/tests/tooling/test_low_latency_manifest.py"
python3 "$ROOT_DIR/tests/tooling/test_artifact_privacy.py"
python3 "$ROOT_DIR/tests/tooling/test_ge_skip_patches.py"
if [[ ${#selected_module_series[@]} -gt 0 ]]; then
  # These regressions deliberately start with the unchanged SE1 control,
  # not the selected (already patched) candidate. Source availability remains
  # optional, as for the existing preparation source-contract tests.
  module_reference_source="$ROOT_DIR/worktrees/ge-proton11-6-se1-rtsp"
  if [[ -e "$module_reference_source/.git" \
      && -f "$module_reference_source/Makefile.in" ]]; then
    python3 "$ROOT_DIR/tests/tooling/test_full_ge_components.py" \
      --source "$module_reference_source"
    python3 "$ROOT_DIR/tests/tooling/test_dav1d_build_module.py" \
      --source "$module_reference_source"
    module_make="$(command -v make || true)"
    if [[ -n "$module_make" && "$("$module_make" --version)" == *"GNU Make"* ]]; then
      python3 "$ROOT_DIR/tests/tooling/test_nvidia_build_rules.py" \
        --source "$module_reference_source" --make "$module_make"
    else
      printf 'NOTE: GNU Make is unavailable; NVIDIA job-bound macro fixture skipped.\n'
    fi
  else
    printf 'NOTE: unchanged SE1 source is unavailable; full-GE/AV1/NVIDIA reference regressions skipped.\n'
  fi
fi

printf 'Preparation checks passed without building Proton.\n'
