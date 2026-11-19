#!/usr/bin/env bash
# SPDX-License-Identifier: BSD-3-Clause
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=pinned-ge-common.sh
source "$ROOT_DIR/scripts/pinned-ge-common.sh"

SOURCE_DIR=""
DEST=""
PIN_CHECK=1

usage() {
  cat <<'EOF2'
Usage: export-dxvk-legacy-source.sh --source DIR [--dest DIR] [--no-pin-check]
                                    [--config FILE]

Export the pin's legacy DXVK tree (PIN_DXVK_LEGACY_*) with git archive from the
materialized DXVK object stores under DIR/dxvk, after verifying every pinned
commit and tree id, and print its normalized tree digest. The default
destination is DIR/dxvk-legacy, which is also added to the checkout's
.git/info/exclude. With --dest the checkout is not touched at all.
--no-pin-check only prints the digest (used to compute PIN_DXVK_LEGACY_TREE_SHA256
for a new pin); the default compares it with the pin and removes a mismatching
export.
EOF2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --source)
      [[ $# -ge 2 && -n "$2" ]] || { usage >&2; exit 2; }
      SOURCE_DIR="$2"; shift 2 ;;
    --dest)
      [[ $# -ge 2 && -n "$2" ]] || { usage >&2; exit 2; }
      DEST="$2"; shift 2 ;;
    --config)
      [[ $# -ge 2 && -n "$2" ]] || { usage >&2; exit 2; }
      PINNED_GE_CONFIG="$2"; shift 2 ;;
    --no-pin-check) PIN_CHECK=0; shift ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'ERROR: unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ -n "$SOURCE_DIR" ]] || { usage >&2; exit 2; }
pinned_ge_load_config
SOURCE_DIR="$(realpath -e -- "$SOURCE_DIR")"
default_dest=0
if [[ -z "$DEST" ]]; then
  DEST="$SOURCE_DIR/dxvk-legacy"
  default_dest=1
fi
DEST="$(realpath -m -- "$DEST")"

pinned_ge_dxvk_legacy_export "$SOURCE_DIR" "$DEST"
digest="$(pinned_ge_dxvk_legacy_source_digest "$DEST")"
if [[ "$PIN_CHECK" == 1 && "$digest" != "$PIN_DXVK_LEGACY_TREE_SHA256" ]]; then
  rm -rf -- "$DEST"
  pinned_ge_fail "exported legacy DXVK tree digest $digest differs from PIN_DXVK_LEGACY_TREE_SHA256"
fi
if [[ "$default_dest" == 1 ]]; then
  pinned_ge_dxvk_legacy_ensure_excluded "$SOURCE_DIR"
fi
printf 'dxvk_legacy_source_sha256\t%s\n' "$digest"
