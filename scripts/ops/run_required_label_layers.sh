#!/usr/bin/env bash
# Run every semantic layer required for a publishable snapshot.
set -uo pipefail

SCRIPTS_DIR="${SCRIPTS_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

run_layer(){
  local name="$1" script="$2"
  echo "[required-labels] $name"
  if bash "$SCRIPTS_DIR/$script" 2>&1 | sed 's/^/  /'; then
    return 0
  fi
  echo "[required-labels] FAILED: $name" >&2
  return 1
}

run_layer "product names" label_product_names.sh || exit 1
run_layer "excerpts" label_excerpts.sh || exit 1
run_layer "representative comments" label_comment_picks.sh || exit 1
