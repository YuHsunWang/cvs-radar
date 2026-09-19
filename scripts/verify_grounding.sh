#!/usr/bin/env bash
# verify_grounding.sh — adjudicate the rewrites the overlap screen could not clear.
#
# The importers hold, rather than reject, any rewrite whose character overlap with
# its cited source is below threshold. On Traditional Chinese that screen flags
# roughly four faithful paraphrases for every invention, so a model decides which
# is which (TypeSafe Jev) and the answers are cached in data/labels/grounding_verdicts.csv.
#
# Run this between two import passes: import (holds rows) -> verify -> import again
# (the held rows now resolve). scripts/ops/run_required_label_layers.sh does that
# for you; run this directly only when adjudicating a queue by hand.
#
# This needs TYPESAFE_API_KEY and is NOT reproducible in CI — which is exactly why
# the answers are cached in a committed CSV.
#
# Env overrides: REPO CONC TYPESAFE_ENV
set -uo pipefail

REPO="${REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
CONC="${CONC:-8}"

log(){ echo "[verify-grounding] $*"; }
die(){ echo "[verify-grounding] FAILED: $*" >&2; exit 1; }

# The key lives outside the repo; rebackfill.sh exports it, this covers a manual run.
TYPESAFE_ENV="${TYPESAFE_ENV:-$HOME/.config/typesafe/env}"
# shellcheck source=/dev/null
[ -n "${TYPESAFE_API_KEY:-}" ] || { [ -f "$TYPESAFE_ENV" ] && . "$TYPESAFE_ENV"; }
[ -n "${TYPESAFE_API_KEY:-}" ] || die "TYPESAFE_API_KEY not set (put it in $TYPESAFE_ENV)"
cd "$REPO" || die "no repo at $REPO"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/verify-grounding.XXXXXX")" || die "mktemp"
trap 'rm -rf "$WORK"' EXIT

# --- 1. collect every pending queue the importers wrote ---
DELTA="$WORK/pending.csv"
python3 - "$REPO" "$DELTA" <<'PY' || die "collect"
import csv, glob, os, sys
csv.field_size_limit(10**7)
repo, out = sys.argv[1], sys.argv[2]
header, rows, seen = None, [], set()
for path in sorted(glob.glob(os.path.join(repo, "artifacts", "pending-grounding-*.csv"))):
    with open(path, encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        header = header or list(reader.fieldnames or [])
        for row in reader:
            key = row.get("fingerprint", "")
            if not key or key in seen:
                continue
            seen.add(key)
            rows.append(row)
if not header:
    print(0)
    raise SystemExit
with open(out, "w", encoding="utf-8-sig", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=header)
    writer.writeheader()
    writer.writerows(rows)
print(len(rows))
PY

[ -f "$DELTA" ] || { log "no pending queue — nothing to adjudicate."; exit 0; }
N="$(python3 -c "import csv;csv.field_size_limit(10**7);print(sum(1 for _ in csv.DictReader(open('$DELTA',encoding='utf-8-sig'))))")"
[ "$N" -eq 0 ] && { log "nothing pending — done."; exit 0; }
log "pending: $N rewrite(s)"

# --- 2. adjudicate with TypeSafe Jev (the rubric lives in scripts/jev_labelers.py) ---
log "adjudicating with Jev, concurrency $CONC"
python3 scripts/jev_labelers.py grounding "$DELTA" --out "$WORK/all_labeled.csv" \
        --concurrency "$CONC" 2>&1 | tail -1 || die "Jev grounding adjudication"

# --- 3. import into the committed cache ---
python3 scripts/import_grounding_verdicts.py "$WORK/all_labeled.csv" --source "$DELTA" \
        --model-tag jev 2>&1 | tail -1 || die "import"
log "DONE. adjudicated=$N"
