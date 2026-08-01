#!/usr/bin/env bash
# label_product_names.sh — label the product-name delta with a local Codex CLI.
#
# Mirrors the sentiment labelling step in rebackfill.sh: export the fields that
# have no label yet, chunk them, let an LLM decide what each field names, verify
# the answers mechanically, then import into data/labels/product_name_labels.csv.
#
# Like the sentiment step, this needs a local Codex CLI and is NOT reproducible in
# CI — which is exactly why the answers are cached in a committed CSV.
#
# Env overrides: REPO CHUNK CONC MODEL RUNNER DELTA
set -uo pipefail

REPO="${REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
CHUNK="${CHUNK:-120}"
CONC="${CONC:-4}"
MODEL="${MODEL:-gpt-5.6-luna}"
RUNNER="${RUNNER:-$HOME/.claude/skills/codex-direct/scripts/run-codex.mjs}"
PROMPT="${PROMPT:-$REPO/scripts/prompts/product-name-labeling.md}"

log(){ echo "[label-product-names] $*"; }
die(){ echo "[label-product-names] FAILED: $*" >&2; exit 1; }

command -v node >/dev/null || die "node not found"
[ -f "$RUNNER" ] || die "run-codex.mjs not found at $RUNNER"
[ -f "$PROMPT" ] || die "prompt template not found at $PROMPT"
cd "$REPO" || die "no repo at $REPO"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/label-product-names.XXXXXX")" || die "mktemp"
trap 'rm -rf "$WORK"' EXIT
DELTA="${DELTA:-$WORK/delta.csv}"

# --- 1. export the still-unlabelled fields ---
python3 scripts/export_product_names.py --out "$DELTA" 2>&1 | tail -1 || die "export"
N="$(python3 -c "import csv;print(sum(1 for _ in csv.DictReader(open('$DELTA',encoding='utf-8-sig'))))")"
[ "$N" -eq 0 ] && { log "nothing new to label — done."; exit 0; }
log "delta: $N field(s)"

# --- 2. chunk into the scratch dir the prompt refers to ---
mkdir -p product_name_work/chunks "$WORK/prompts"
rm -f product_name_work/chunks/*.csv
python3 - "$DELTA" product_name_work/chunks "$CHUNK" <<'PY' || die "chunk"
import csv, sys
src, outdir, size = sys.argv[1], sys.argv[2], int(sys.argv[3])
with open(src, encoding="utf-8-sig", newline="") as f:
    reader = csv.reader(f)
    header = next(reader)
    rows = list(reader)
for index in range(0, len(rows), size):
    number = index // size + 1
    with open(f"{outdir}/chunk_{number:02d}.csv", "w", encoding="utf-8-sig", newline="") as g:
        writer = csv.writer(g)
        writer.writerow(header)
        writer.writerows(rows[index:index + size])
print("chunks", (len(rows) + size - 1) // size)
PY

# --- 3. one prompt per chunk ---
for f in product_name_work/chunks/chunk_*.csv; do
  nn="$(basename "$f" .csv | sed 's/chunk_//')"
  rows="$(python3 -c "import csv;print(sum(1 for _ in csv.DictReader(open('$f',encoding='utf-8-sig'))))")"
  sed -e "s#__CHUNK__#chunk_${nn}#g" -e "s#__N__#${rows}#g" "$PROMPT" > "$WORK/prompts/prompt_${nn}.md"
done

# --- 4. label with Codex ---
log "labeling $(ls product_name_work/chunks/chunk_*.csv | wc -l) chunk(s), concurrency $CONC"
: > "$WORK/manifest.tsv"
run_one(){
  local nn="$1"
  node "$RUNNER" "$WORK/prompts/prompt_${nn}.md" --cwd "$REPO" --model "$MODEL" \
       --timeout 2400000 --inactivity-timeout 600000 > "$WORK/chunk_${nn}.log" 2>&1
  printf '%s\t%s\n' "$nn" "$?" >> "$WORK/manifest.tsv"
}
export -f run_one; export RUNNER WORK REPO MODEL
ls product_name_work/chunks/chunk_*.csv | sed -E 's/.*chunk_([0-9]+)\.csv/\1/' \
  | xargs -P"$CONC" -I{} bash -c 'run_one "$@"' _ {}
bad="$(awk -F'\t' '$2!=0' "$WORK/manifest.tsv" | wc -l)"
[ "$bad" -eq 0 ] || die "$bad chunk(s) had a non-zero Codex exit — see $WORK"

# --- 5. verify independently, then combine ---
python3 - product_name_work/chunks "$WORK/all_labeled.csv" <<'PY' || die "verification failed"
import csv, glob, os, sys
source_dir, out = sys.argv[1], sys.argv[2]
errors, header, combined = [], None, []
for src in sorted(glob.glob(f"{source_dir}/chunk_*.csv")):
    if src.endswith(".labeled.csv"):
        continue
    labeled = src[:-4] + ".labeled.csv"
    if not os.path.exists(labeled):
        errors.append(f"missing {os.path.basename(labeled)}")
        continue
    want = {r["fingerprint"] for r in csv.DictReader(open(src, encoding="utf-8-sig", newline=""))}
    rows = list(csv.DictReader(open(labeled, encoding="utf-8-sig", newline="")))
    header = header or list(rows[0].keys())
    got = {r["fingerprint"] for r in rows}
    if want - got:
        errors.append(f"{os.path.basename(labeled)}: {len(want - got)} fingerprint(s) dropped")
    if got - want:
        errors.append(f"{os.path.basename(labeled)}: unknown fingerprint(s) added")
    seen: dict[str, set[int]] = {}
    for i, row in enumerate(rows, 1):
        price = row["price"].strip()
        if price and not price.isdigit():
            errors.append(f"{os.path.basename(labeled)} r{i}: non-integer price {price!r}")
        if price and not row["product_name"].strip():
            errors.append(f"{os.path.basename(labeled)} r{i}: price without a name")
        try:
            seen.setdefault(row["fingerprint"], set()).add(int(row["item_index"]))
        except ValueError:
            errors.append(f"{os.path.basename(labeled)} r{i}: bad item_index")
    for fingerprint, indexes in seen.items():
        if indexes != set(range(len(indexes))):
            errors.append(f"{fingerprint[:12]}: item_index gap {sorted(indexes)}")
    combined.extend(rows)
if errors:
    print("VERIFY ERRORS:", errors[:12])
    sys.exit(1)
with open(out, "w", encoding="utf-8-sig", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=header)
    writer.writeheader()
    writer.writerows(combined)
print(f"verified {len(combined)} labeled rows -> {out}")
PY

# --- 6. import into the committed cache ---
python3 scripts/import_product_names.py "$WORK/all_labeled.csv" --model-tag "$MODEL" 2>&1 | tail -1 || die "import"
rm -rf product_name_work
log "DONE. delta labeled=$N"
