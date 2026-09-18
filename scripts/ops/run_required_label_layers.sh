#!/usr/bin/env bash
# Run every semantic layer required for a publishable snapshot.
#
# Two passes, because grounding adjudication sits between them. The first pass
# labels and imports; any rewrite the overlap screen could not clear is *held*
# rather than imported or rejected, and queued in artifacts/pending-grounding-*.csv.
# verify_grounding.sh then has a model judge that queue, and the second pass
# re-labels and imports the held rows now that verdicts exist.
set -uo pipefail

SCRIPTS_DIR="${SCRIPTS_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
REPO="${REPO:-$(cd "$SCRIPTS_DIR/.." && pwd)}"

run_layer(){
  local name="$1" script="$2"
  echo "[required-labels] $name"
  if bash "$SCRIPTS_DIR/$script" 2>&1 | sed 's/^/  /'; then
    return 0
  fi
  echo "[required-labels] FAILED: $name" >&2
  return 1
}

run_all_layers(){
  run_layer "product names" label_product_names.sh || return 1
  run_layer "excerpts" label_excerpts.sh || return 1
  run_layer "representative comments" label_comment_picks.sh || return 1
}

pending_count(){
  python3 - "$REPO" <<'PY'
import csv, glob, os, sys
csv.field_size_limit(10**7)
total = 0
for path in glob.glob(os.path.join(sys.argv[1], "artifacts", "pending-grounding-*.csv")):
    with open(path, encoding="utf-8-sig", newline="") as handle:
        total += sum(1 for _ in csv.DictReader(handle))
print(total)
PY
}

run_all_layers || exit 1

pending="$(pending_count)"
if [ "${pending:-0}" -gt 0 ]; then
  echo "[required-labels] $pending rewrite(s) held for grounding adjudication"
  run_layer "grounding verdicts" verify_grounding.sh || exit 1
  echo "[required-labels] second pass for the held rows"
  run_all_layers || exit 1
  still="$(pending_count)"
  if [ "${still:-0}" -gt 0 ]; then
    echo "[required-labels] NOTE: $still rewrite(s) still held after adjudication" >&2
  fi
fi
