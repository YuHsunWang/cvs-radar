#!/usr/bin/env bash
# label_product_categories.sh — label the product-category delta with TypeSafe Jev.
#
# Export the products that have no category label yet, let Jev pick a category
# for each, then import (which validates) into data/labels/product_category_labels.csv.
#
# Unlike the other layers this one exports from data/results.json, not posts.jsonl:
# a category is keyed to the product name the pipeline settled on, so this runs
# AFTER the recompute — see the call site in scripts/ops/rebackfill.sh.
#
# Needs TYPESAFE_API_KEY and is NOT reproducible in CI, which is why the answers
# are cached in a committed CSV.
#
# Env overrides: REPO CONC DELTA TYPESAFE_ENV
set -uo pipefail

REPO="${REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
CONC="${CONC:-8}"

log(){ echo "[label-product-categories] $*"; }
die(){ echo "[label-product-categories] FAILED: $*" >&2; exit 1; }

# The key lives outside the repo; rebackfill.sh exports it, this covers a manual run.
TYPESAFE_ENV="${TYPESAFE_ENV:-$HOME/.config/typesafe/env}"
# shellcheck source=/dev/null
[ -n "${TYPESAFE_API_KEY:-}" ] || { [ -f "$TYPESAFE_ENV" ] && . "$TYPESAFE_ENV"; }
[ -n "${TYPESAFE_API_KEY:-}" ] || die "TYPESAFE_API_KEY not set (put it in $TYPESAFE_ENV)"
cd "$REPO" || die "no repo at $REPO"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/label-product-categories.XXXXXX")" || die "mktemp"
trap 'rm -rf "$WORK"' EXIT
DELTA="${DELTA:-$WORK/delta.csv}"

# --- 1. export the still-unlabelled products ---
python3 scripts/export_product_categories.py --out "$DELTA" 2>&1 | tail -1 || die "export"
N="$(python3 -c "import csv;print(sum(1 for _ in csv.DictReader(open('$DELTA',encoding='utf-8-sig'))))")"
[ "$N" -eq 0 ] && { log "nothing new to label — done."; exit 0; }
log "delta: $N product(s)"

# --- 2. label with TypeSafe Jev (the rubric lives in scripts/jev_labelers.py) ---
log "labeling with Jev, concurrency $CONC"
python3 scripts/jev_labelers.py category "$DELTA" --out "$WORK/all_labeled.csv" \
        --concurrency "$CONC" 2>&1 | tail -1 || die "Jev category labeling"

# --- 6. import into the committed cache ---
python3 scripts/import_product_categories.py "$WORK/all_labeled.csv" --source "$DELTA" \
        --model-tag jev 2>&1 | tail -1 || die "import"
log "DONE. delta labeled=$N"
