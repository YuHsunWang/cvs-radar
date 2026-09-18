#!/usr/bin/env bash
# verify_grounding.sh — adjudicate the rewrites the overlap screen could not clear.
#
# The importers hold, rather than reject, any rewrite whose character overlap with
# its cited source is below threshold. On Traditional Chinese that screen flags
# roughly four faithful paraphrases for every invention, so a model decides which
# is which and the answers are cached in data/labels/grounding_verdicts.csv.
#
# Run this between two import passes: import (holds rows) -> verify -> import again
# (the held rows now resolve). scripts/ops/run_required_label_layers.sh does that
# for you; run this directly only when adjudicating a queue by hand.
#
# Like the other labelling steps this needs a local Codex CLI and is NOT reproducible
# in CI — which is exactly why the answers are cached in a committed CSV.
#
# Env overrides: REPO CHUNK CONC MODEL RUNNER EFFORT PENDING
set -uo pipefail

REPO="${REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
CHUNK="${CHUNK:-100}"
CONC="${CONC:-5}"
MODEL="${MODEL:-gpt-5.6-luna}"
RUNNER="${RUNNER:-$HOME/.claude/skills/codex-direct/scripts/run-codex.mjs}"
PROMPT="${PROMPT:-$REPO/scripts/prompts/grounding-verification.md}"

log(){ echo "[verify-grounding] $*"; }
die(){ echo "[verify-grounding] FAILED: $*" >&2; exit 1; }

command -v node >/dev/null || die "node not found"
[ -f "$RUNNER" ] || die "run-codex.mjs not found at $RUNNER"
[ -f "$PROMPT" ] || die "prompt template not found at $PROMPT"
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

# --- 2. chunk into the scratch dir the prompt refers to ---
mkdir -p grounding_work/chunks "$WORK/prompts"
rm -f grounding_work/chunks/*.csv
python3 - "$DELTA" grounding_work/chunks "$CHUNK" <<'PY' || die "chunk"
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

for f in grounding_work/chunks/chunk_*.csv; do
  nn="$(basename "$f" .csv | sed 's/chunk_//')"
  rows="$(python3 -c "import csv;csv.field_size_limit(10**7);print(sum(1 for _ in csv.DictReader(open('$f',encoding='utf-8-sig'))))")"
  sed -e "s#__CHUNK__#chunk_${nn}#g" -e "s#__N__#${rows}#g" "$PROMPT" > "$WORK/prompts/prompt_${nn}.md"
done

# --- 3. adjudicate with Codex ---
log "adjudicating $(ls grounding_work/chunks/chunk_*.csv | wc -l) chunk(s), concurrency $CONC"
: > "$WORK/manifest.tsv"
run_one(){
  local nn="$1" effort_args=()
  [ -z "${EFFORT:-}" ] || effort_args=(--effort "$EFFORT")
  node "$RUNNER" "$WORK/prompts/prompt_${nn}.md" --cwd "$REPO" --model "$MODEL" \
       "${effort_args[@]}" --timeout 2400000 --inactivity-timeout 600000 \
       > "$WORK/chunk_${nn}.log" 2>&1
  printf '%s\t%s\n' "$nn" "$?" >> "$WORK/manifest.tsv"
}
export -f run_one; export RUNNER WORK REPO MODEL EFFORT="${EFFORT:-}"
ls grounding_work/chunks/chunk_*.csv | sed -E 's/.*chunk_([0-9]+)\.csv/\1/' \
  | xargs -P"$CONC" -I{} bash -c 'run_one "$@"' _ {}
bad="$(awk -F'\t' '$2!=0' "$WORK/manifest.tsv" | wc -l)"
[ "$bad" -eq 0 ] || die "$bad chunk(s) had a non-zero Codex exit — see $WORK"

# --- 4. verify structurally, then combine ---
python3 - grounding_work/chunks "$WORK/all_labeled.csv" <<'PY' || die "verification failed"
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
    name = os.path.basename(labeled)
    if len(rows) != len(source_rows):
        errors.append(f"{name}: row count changed")
        continue
    original = {r["fingerprint"]: r for r in source_rows}
    for i, row in enumerate(rows, 1):
        source = original.get(row.get("fingerprint", ""))
        if source is None:
            errors.append(f"{name} r{i}: unknown fingerprint")
            continue
        # The verdict is only valid for the exact pair that was judged.
        for column in ("rewrite", "source_text", "product_name", "field"):
            if row.get(column, "") != source.get(column, ""):
                errors.append(f"{name} r{i}: {column} was modified")
        if row.get("verdict", "").strip() not in {"grounded", "ungrounded"}:
            errors.append(f"{name} r{i}: bad verdict {row.get('verdict')!r}")
    combined.extend(rows)
if errors:
    print("VERIFY ERRORS:", errors[:12])
    sys.exit(1)
with open(out, "w", encoding="utf-8-sig", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=header)
    writer.writeheader()
    writer.writerows(combined)
print(f"verified {len(combined)} verdicts -> {out}")
PY

# --- 5. import into the committed cache ---
python3 scripts/import_grounding_verdicts.py "$WORK/all_labeled.csv" --source "$DELTA" \
        --model-tag "$MODEL" 2>&1 | tail -1 || die "import"
rm -rf grounding_work
log "DONE. adjudicated=$N"
