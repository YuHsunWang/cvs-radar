#!/usr/bin/env bash
# label_excerpts.sh — label the review-excerpt delta with a local Codex CLI.
#
# Mirrors label_product_names.sh: export the products whose candidate pool has no
# pick yet, chunk them, let an LLM choose which author sentences a shopper should see, verify the answers mechanically, then
# import into data/labels/excerpt_labels.csv.
#
# Like the other labelling steps this needs a local Codex CLI and is NOT reproducible
# in CI — which is exactly why the answers are cached in a committed CSV.
#
# Env overrides: REPO CHUNK CONC MODEL RUNNER DELTA
set -uo pipefail

REPO="${REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
CHUNK="${CHUNK:-100}"
CONC="${CONC:-5}"
MODEL="${MODEL:-gpt-5.6-terra}"
RUNNER="${RUNNER:-$HOME/.claude/skills/codex-direct/scripts/run-codex.mjs}"
PROMPT="${PROMPT:-$REPO/scripts/prompts/excerpt-labeling.md}"

log(){ echo "[label-excerpts] $*"; }
die(){ echo "[label-excerpts] FAILED: $*" >&2; exit 1; }

command -v node >/dev/null || die "node not found"
[ -f "$RUNNER" ] || die "run-codex.mjs not found at $RUNNER"
[ -f "$PROMPT" ] || die "prompt template not found at $PROMPT"
cd "$REPO" || die "no repo at $REPO"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/label-excerpts.XXXXXX")" || die "mktemp"
trap 'rm -rf "$WORK"' EXIT
DELTA="${DELTA:-$WORK/delta.csv}"

# --- 1. export the still-unlabelled products ---
python3 scripts/export_excerpts.py --out "$DELTA" 2>&1 | tail -1 || die "export"
N="$(python3 -c "import csv,sys;csv.field_size_limit(10**7);print(sum(1 for _ in csv.DictReader(open('$DELTA',encoding='utf-8-sig'))))")"
[ "$N" -eq 0 ] && { log "nothing new to label — done."; exit 0; }
log "delta: $N pair(s)"

# --- 2. chunk into the scratch dir the prompt refers to ---
mkdir -p excerpt_work/chunks "$WORK/prompts"
rm -f excerpt_work/chunks/*.csv
python3 - "$DELTA" excerpt_work/chunks "$CHUNK" <<'PY' || die "chunk"
import csv, sys
csv.field_size_limit(10**7)
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
for f in excerpt_work/chunks/chunk_*.csv; do
  nn="$(basename "$f" .csv | sed 's/chunk_//')"
  rows="$(python3 -c "import csv;csv.field_size_limit(10**7);print(sum(1 for _ in csv.DictReader(open('$f',encoding='utf-8-sig'))))")"
  sed -e "s#__CHUNK__#chunk_${nn}#g" -e "s#__N__#${rows}#g" "$PROMPT" > "$WORK/prompts/prompt_${nn}.md"
done

# --- 4. label with Codex ---
log "labeling $(ls excerpt_work/chunks/chunk_*.csv | wc -l) chunk(s), concurrency $CONC"
: > "$WORK/manifest.tsv"
run_one(){
  local nn="$1"
  node "$RUNNER" "$WORK/prompts/prompt_${nn}.md" --cwd "$REPO" --model "$MODEL" \
       --timeout 2400000 --inactivity-timeout 600000 > "$WORK/chunk_${nn}.log" 2>&1
  printf '%s\t%s\n' "$nn" "$?" >> "$WORK/manifest.tsv"
}
export -f run_one; export RUNNER WORK REPO MODEL
ls excerpt_work/chunks/chunk_*.csv | sed -E 's/.*chunk_([0-9]+)\.csv/\1/' \
  | xargs -P"$CONC" -I{} bash -c 'run_one "$@"' _ {}
bad="$(awk -F'\t' '$2!=0' "$WORK/manifest.tsv" | wc -l)"
[ "$bad" -eq 0 ] || die "$bad chunk(s) had a non-zero Codex exit — see $WORK"

# --- 5. verify independently, then combine ---
# Only structural checks here; scripts/import_excerpts.py re-validates every
# index against its candidate cell and refuses the file rather than repairing it.
python3 - excerpt_work/chunks "$WORK/all_labeled.csv" <<'PY' || die "verification failed"
import csv, glob, os, sys
csv.field_size_limit(10**7)
source_dir, out = sys.argv[1], sys.argv[2]
errors, header, combined = [], None, []
for src in sorted(glob.glob(f"{source_dir}/chunk_*.csv")):
    if src.endswith(".labeled.csv"):
        continue
    labeled = src[:-4] + ".labeled.csv"
    if not os.path.exists(labeled):
        errors.append(f"missing {os.path.basename(labeled)}")
        continue
    source_rows = list(csv.DictReader(open(src, encoding="utf-8-sig", newline="")))
    rows = list(csv.DictReader(open(labeled, encoding="utf-8-sig", newline="")))
    header = header or list(rows[0].keys())
    want = {r["fingerprint"] for r in source_rows}
    got = {r["fingerprint"] for r in rows}
    name = os.path.basename(labeled)
    if want - got:
        errors.append(f"{name}: {len(want - got)} fingerprint(s) dropped")
    if got - want:
        errors.append(f"{name}: unknown fingerprint(s) added")
    # review_text is the ground truth an excerpt must be quoted from, so a chunk
    # that rewrote it would let an unverifiable excerpt through.
    original = {r["fingerprint"]: r for r in source_rows}
    for i, row in enumerate(rows, 1):
        source = original.get(row["fingerprint"])
        if source is None:
            continue
        for column in ("post_id", "product_name", "review_text"):
            if row.get(column, "") != source.get(column, ""):
                errors.append(f"{name} r{i}: {column} was modified")
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
python3 scripts/import_excerpts.py "$WORK/all_labeled.csv" 2>&1 | tail -1 || die "import"
rm -rf excerpt_work
log "DONE. delta labeled=$N"
