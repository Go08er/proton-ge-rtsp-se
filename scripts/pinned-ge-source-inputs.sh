#!/usr/bin/env bash
# SPDX-License-Identifier: BSD-3-Clause
# Helpers for GE snapshots that prepare Wine-Mono from a declared archive.
# Requires pinned-ge-common.sh; older pins retain their original behavior.

pinned_ge_has_mono_source() {
  pinned_ge_git -C "$1" cat-file -e \
    "$PIN_SOURCE_COMMIT:patches/wine-mono/prepare.sh" 2>/dev/null
}

pinned_ge_require_pristine_with_contrib() {
  local source="$1" manifest="$2" entries record path mode size sha status mono_version
  declare -A declared=()

  pinned_ge_require_complete_build_contrib "$source" "$manifest" || return 1
  entries="$(pinned_ge_build_contrib_entries "$manifest")" || return 1
  while IFS=$'\t' read -r path mode size sha; do
    declared["$path"]=1
  done <<<"$entries"
  mono_version="$(pinned_ge_git -C "$source" show \
    "$PIN_SOURCE_COMMIT:patches/wine-mono/source.conf" \
    | sed -n 's/^WINEMONO_VER=//p')" || return 1
  [[ "$mono_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ \
      && -n "${declared[contrib/wine-mono-${mono_version}-src.tar.xz]+present}" ]] \
    || { pinned_ge_fail "the selected Wine-Mono source archive must be declared and prefetched before preparation"; return 1; }
  status="$(pinned_ge_git -C "$source" status --porcelain --untracked-files=all)" \
    || return 1
  while IFS= read -r record; do
    [[ -n "$record" ]] || continue
    # Keep tracked files, submodules and unrelated untracked files pristine.
    # Quoted/unusual paths fail closed; contrib manifest paths are ordinary paths.
    path="${record:3}"
    [[ "$record" == '?? '* && -n "${declared[$path]+present}" ]] \
      || { pinned_ge_fail "source is not pristine outside declared contrib inputs: $record"; return 1; }
  done <<<"$status"
}

pinned_ge_mono_source_digest() (
  set -euo pipefail
  local source="$1" digest
  [[ -d "$source/wine-mono" && ! -L "$source/wine-mono" \
      && ! -e "$source/wine-mono/.git" && ! -L "$source/wine-mono/.git" \
      && -f "$source/wine-mono/.proton-prepared" \
      && ! -L "$source/wine-mono/.proton-prepared" ]] \
    || { pinned_ge_fail "prepared Wine-Mono source/stamp is missing or unsafe"; return 1; }
  # GE ignores /wine-mono/, so the Git-based root digest does not cover it.
  # Reuse the complete-tree hash: content, modes and symlinks, excluding mtimes.
  digest="$(bash "$PINNED_GE_ROOT/scripts/hash-source-tree.sh" \
    --tree "$source/wine-mono" \
    | awk -F '\t' '$1 == "normalized_tar_sha256" {print $2}')" || return 1
  [[ "$digest" =~ ^[0-9a-f]{64}$ ]] \
    || { pinned_ge_fail "could not hash prepared Wine-Mono source"; return 1; }
  printf '%s\n' "$digest"
)

pinned_ge_require_mono_source_state() {
  local source="$1" state="$2" expected actual
  pinned_ge_has_mono_source "$source" || return 0
  expected="$(pinned_ge_state_value "$state" wine_mono_source_sha256)" || return 1
  actual="$(pinned_ge_mono_source_digest "$source")" || return 1
  [[ "$actual" == "$expected" ]] \
    || { pinned_ge_fail "prepared Wine-Mono source differs from its recorded digest"; return 1; }
}
