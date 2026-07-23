#!/usr/bin/env bash
# rebackfill.sh — the production data-refresh pipeline for CVS Radar (review #9).
#
# This is the reproducible, versioned copy of the pipeline that keeps the live
# site up to date. It is committed here so the process is documented and
# recoverable from the repo alone, rather than living only on the author's
# machine. See docs/ops-pipeline.md for how it is scheduled and monitored.
#
# Pipeline: crawl fresh PTT data -> backfill author review text -> export the
# still-unlabeled delta -> label it with a local subscription Codex CLI
# (concurrency) -> independently verify -> import into
# data/labels/sentiment_fingerprint_labels.csv -> recompute scores ->
# strip_profiles (de-identify) -> build public data.json -> commit (+push).
# Re-runnable: each run only labels comments not already in the cache/legacy.
#
# NOTE: the Codex labeling step (RUNNER) requires a local Codex CLI and is NOT
# reproducible in CI; everything else is standard python + git and portable.
#
# Env overrides: REPO BRANCH WT STORE_SEED PAGES REFRESH_DAYS CHUNK CONC
#                DO_COMMIT PUSH RUNNER
set -uo pipefail

REPO="${REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
BRANCH="${BRANCH:-main}"   # label cache lives on main since PR #12/#13 merged
WT="${WT:-$HOME/.cache/cvs-rebackfill-wt}"
STORE_SEED="${STORE_SEED:-$REPO/data/posts.jsonl}"   # persistent posts.jsonl seed
PAGES="${PAGES:-12}"
REFRESH_DAYS="${REFRESH_DAYS:-14}"
CHUNK="${CHUNK:-300}"
CONC="${CONC:-5}"
DO_COMMIT="${DO_COMMIT:-1}"
PUSH="${PUSH:-0}"   # default: commit in the worktree only; you push to main or open a PR
RUNNER="${RUNNER:-$HOME/.claude/skills/codex-direct/scripts/run-codex.mjs}"

log(){ echo "[rebackfill] $*"; }
die(){ echo "[rebackfill] FAILED: $*" >&2; exit 1; }

command -v node >/dev/null || die "node not found"
[ -f "$RUNNER" ] || die "run-codex.mjs not found at $RUNNER"

# --- 0. worktree on BRANCH (reuse if present, always reset to origin) ---
cd "$REPO" || die "no repo at $REPO"
git fetch -q origin "$BRANCH" || die "git fetch $BRANCH"
if git worktree list --porcelain | grep -q "worktree $WT"; then
  git -C "$WT" fetch -q origin "$BRANCH"
  git -C "$WT" checkout -q "$BRANCH" 2>/dev/null || git -C "$WT" checkout -q -B "$BRANCH" "origin/$BRANCH"
  git -C "$WT" reset -q --hard "origin/$BRANCH"
else
  rm -rf "$WT"
  git worktree add -f "$WT" "$BRANCH" >/dev/null 2>&1 || die "worktree add"
fi
cd "$WT" || die "cd worktree"
# keep the scratch working dir out of git without touching the repo .gitignore
# (in a worktree .git is a file, so resolve the real info/exclude path)
_excl="$(git rev-parse --git-path info/exclude 2>/dev/null)"
[ -n "$_excl" ] && { grep -qxF 'rebackfill_work/' "$_excl" 2>/dev/null || echo 'rebackfill_work/' >> "$_excl"; }

# --- persistent posts.jsonl so we only ever crawl the delta ---
mkdir -p data
if [ ! -s data/posts.jsonl ] && [ -s "$STORE_SEED" ]; then
  cp "$STORE_SEED" data/posts.jsonl
  log "seeded posts.jsonl from $STORE_SEED ($(wc -l < data/posts.jsonl) posts)"
fi
[ -s data/posts.jsonl ] || die "no posts.jsonl seed available (set STORE_SEED)"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/rebackfill.XXXXXX")" || die "mktemp"
mkdir -p "$WORK/chunks" "$WORK/prompts" "$WORK/logs" rebackfill_work/chunks
# On failure, preserve the Codex chunk logs before cleaning up — otherwise the
# "see $WORK/logs" hint in die() points at a directory this trap just deleted.
cleanup(){
  local status=$?
  if [ "$status" -ne 0 ] && [ -d "$WORK/logs" ]; then
    local dest="$HOME/.claude/logs/rebackfill-failures/$(date -u +%Y%m%dT%H%M%SZ)"
    mkdir -p "$dest"
    cp -r "$WORK/logs" "$dest/" 2>/dev/null
    [ -f "$WORK/manifest.tsv" ] && cp "$WORK/manifest.tsv" "$dest/" 2>/dev/null
    echo "[rebackfill] failure logs preserved at $dest" >&2
  fi
  rm -rf "$WORK"
}
trap cleanup EXIT

# --- 1. crawl fresh data ---
log "crawl: pages=$PAGES refresh_recent_days=$REFRESH_DAYS"
python3 crawl_job.py --pages "$PAGES" --refresh-recent-days "$REFRESH_DAYS" \
        --skip-recompute --store data/posts.jsonl 2>&1 | tail -1 || die "crawl"

# --- 1b. backfill missing author review text (best effort; needs PTT) ---
# Fills post.review_text for stored articles whose body was never parsed, which
# is what the excerpt step reads. Non-fatal: a flaky/expired PTT fetch must not
# block the labeling+recompute pipeline.
log "backfill missing author reviews"
python3 scripts/backfill_reviews.py --delay 0.5 2>&1 | tail -2 \
        || log "backfill_reviews had errors (continuing)"

# --- 2. export the still-unlabeled delta (excludes cache + legacy) ---
python3 scripts/export_llm_backfill.py --posts data/posts.jsonl \
        --out "$WORK/delta.csv" 2>&1 | tail -1 || die "export"
N="$(python3 -c "import csv;print(sum(1 for _ in csv.DictReader(open('$WORK/delta.csv',encoding='utf-8-sig'))))")"
log "delta unlabeled comments: $N"
[ "$N" -eq 0 ] && { log "nothing new to label — done."; exit 0; }

# --- 3. chunk ---
python3 - "$WORK/delta.csv" "$WORK/chunks" "$CHUNK" <<'PY' || die "chunk"
import csv,sys,os
src,outdir,size=sys.argv[1],sys.argv[2],int(sys.argv[3])
with open(src,encoding="utf-8-sig",newline="") as f:
    r=csv.reader(f); h=next(r); rows=list(r)
for i in range(0,len(rows),size):
    n=i//size+1
    with open(f"{outdir}/chunk_{n:02d}.csv","w",encoding="utf-8-sig",newline="") as g:
        w=csv.writer(g); w.writerow(h); w.writerows(rows[i:i+size])
print("chunks", (len(rows)+size-1)//size)
PY
cp "$WORK"/chunks/*.csv rebackfill_work/chunks/

# --- 4. write prompt template + per-chunk prompts (in $WORK, NOT codex-direct root) ---
cat > "$WORK/prompt_template.md" <<'TPL'
<task>
Label the sentiment of PTT convenience-store product comments in ONE CSV file:
`rebackfill_work/chunks/__CHUNK__.csv` (__N__ data rows). Read
`docs/labeling_guideline.md` first — that is the authoritative rubric. For EVERY
row read `comment_text` (context: `brand`, `product_name`, `post_title`, `tag`)
and judge its sentiment toward the product. Write
`rebackfill_work/chunks/__CHUNK__.labeled.csv`.

Judge each comment YOURSELF. Do NOT write a keyword/lexicon script or heuristic —
that defeats the purpose. Reason about irony, mixed sentiment, context per rubric.
</task>
<how_to_fill_each_row>
Keep all 12 columns and the same header. Keep `fingerprint`, `brand`,
`product_name`, `post_title`, `tag`, `comment_text`, `prompt_version` UNCHANGED,
rows in the SAME order. Fill:
- `is_relevant`: `true` if the comment carries any product evaluation (taste,
  quality, value, texture, would-buy, comparison verdict — even weak/mixed);
  `false` for pure questions, stock/where-to-buy, redemption/logistics, tagging
  friends, off-topic, personal state, empty.
- `llm_label`: exactly `正向`/`中性`/`負向` (map rubric 正->正向, 負->負向, 中性->中性).
  Irony by real meaning; brand aliases normalized; comparative verdict decides
  polarity. Every row needs a label, incl. is_relevant=false rows (use 中性).
- `llm_score`: float in [-1,1] ONLY when is_relevant=true, else EMPTY. Strong
  praise/回購 +0.6..+1.0; mild + +0.2..+0.5; neutral/mixed -0.1..+0.1 with 中性;
  mild - -0.2..-0.6; strong -/踩雷/難吃 -0.7..-1.0. Sign must match label.
- `reason`: SHORT (<=15 chars) zh-TW note. `model`: set to `codex`.
</how_to_fill_each_row>
<acceptance_criteria>
- `rebackfill_work/chunks/__CHUNK__.labeled.csv` exists, UTF-8 BOM, same header.
- Exactly __N__ rows, same order, SAME fingerprints.
- is_relevant in {true,false}; llm_label in {正向,中性,負向}; if relevant then
  llm_score float in [-1,1] with matching sign, else empty. No row skipped/dup.
- Verify: `python scripts/import_llm_backfill.py rebackfill_work/chunks/__CHUNK__.labeled.csv --labels rebackfill_work/__VALIDATE__.csv`
  must print 0 errors; then delete that validate file.
</acceptance_criteria>
<scope_constraints>
Do not modify anything under cvs_radar/, scripts/, tests/, .github/, data/, docs/.
Only create the labeled CSV (+ throwaway validate file). Do NOT git add/commit.
</scope_constraints>
<default_follow_through_policy>
Label all __N__ rows. Do not sample. Only stop if the rubric is genuinely contradictory.
</default_follow_through_policy>
<compact_output_contract>
Under 400 words: counts by label + is_relevant=false count; 3-5 tricky examples;
the exact import-validator line; anything unsure. No full CSV.
</compact_output_contract>
TPL

for f in "$WORK"/chunks/chunk_*.csv; do
  nn="$(basename "$f" .csv | sed 's/chunk_//')"
  rows="$(python3 -c "import csv;print(sum(1 for _ in csv.DictReader(open('$f',encoding='utf-8-sig'))))")"
  sed -e "s#__CHUNK__#chunk_${nn}#g" -e "s#__VALIDATE__#_validate_${nn}#g" \
      -e "s#__N__#${rows}#g" "$WORK/prompt_template.md" > "$WORK/prompts/prompt_${nn}.md"
done

# --- 5. label with Codex (concurrency $CONC) ---
log "labeling with Codex: $(ls "$WORK"/chunks/chunk_*.csv | wc -l) chunk(s), concurrency $CONC"
: > "$WORK/manifest.tsv"
run_one(){
  local nn="$1"
  node "$RUNNER" "$WORK/prompts/prompt_${nn}.md" --cwd "$WT" \
       --timeout 1800000 --inactivity-timeout 360000 > "$WORK/logs/chunk_${nn}.log" 2>&1
  printf '%s\t%s\n' "$nn" "$?" >> "$WORK/manifest.tsv"
}
export -f run_one; export RUNNER WORK WT
ls "$WORK"/chunks/chunk_*.csv | sed -E 's/.*chunk_([0-9]+)\.csv/\1/' \
  | xargs -P"$CONC" -I{} bash -c 'run_one "$@"' _ {}
bad="$(awk -F'\t' '$2!=0' "$WORK/manifest.tsv" | wc -l)"
[ "$bad" -eq 0 ] || die "$bad chunk(s) had non-zero Codex exit — see $WORK/logs"

# --- 6. independent verify + combine ---
python3 - "$WT/rebackfill_work/chunks" "$WORK/all_labeled.csv" <<'PY' || die "verification failed"
import csv,sys,glob,os
d,out=sys.argv[1],sys.argv[2]
VALID={"正向","中性","負向"}; errs=[]; header=None; combined=[]
for src in sorted(glob.glob(f"{d}/chunk_*.csv")):
    if src.endswith(".labeled.csv"): continue
    lab=src[:-4]+".labeled.csv"
    if not os.path.exists(lab): errs.append(f"missing {os.path.basename(lab)}"); continue
    S=list(csv.DictReader(open(src,encoding="utf-8-sig",newline="")))
    L=list(csv.DictReader(open(lab,encoding="utf-8-sig",newline="")))
    header=header or list(L[0].keys())
    if [r["fingerprint"] for r in S]!=[r["fingerprint"] for r in L]:
        errs.append(f"{os.path.basename(lab)}: fingerprint order mismatch")
    for i,r in enumerate(L,1):
        lbl=r["llm_label"].strip(); rel=r["is_relevant"].strip().lower(); sc=r["llm_score"].strip()
        if lbl not in VALID: errs.append(f"{os.path.basename(lab)}r{i} label"); continue
        if rel not in {"true","false"}: errs.append(f"{os.path.basename(lab)}r{i} rel"); continue
        if rel=="true":
            try: v=float(sc)
            except: errs.append(f"{os.path.basename(lab)}r{i} score"); continue
            if not -1<=v<=1 or (lbl=="正向" and v<=0) or (lbl=="負向" and v>=0):
                errs.append(f"{os.path.basename(lab)}r{i} sign/range")
        elif sc!="": errs.append(f"{os.path.basename(lab)}r{i} irrel score")
        combined.append(r)
if errs:
    print("VERIFY ERRORS:", errs[:12]); sys.exit(1)
with open(out,"w",encoding="utf-8-sig",newline="") as f:
    w=csv.DictWriter(f,fieldnames=header); w.writeheader(); w.writerows(combined)
print(f"verified {len(combined)} labeled rows -> {out}")
PY

# --- 7. import into the real cache ---
before="$(python3 -c "import csv;print(sum(1 for _ in csv.DictReader(open('data/labels/sentiment_fingerprint_labels.csv',encoding='utf-8-sig'))))" 2>/dev/null || echo 0)"
python3 scripts/import_llm_backfill.py "$WORK/all_labeled.csv" \
        --labels data/labels/sentiment_fingerprint_labels.csv 2>&1 | tail -1 || die "import"
after="$(python3 -c "import csv;print(sum(1 for _ in csv.DictReader(open('data/labels/sentiment_fingerprint_labels.csv',encoding='utf-8-sig'))))")"
rm -rf rebackfill_work
# refresh the persistent seed so the next run continues from here
cp data/posts.jsonl "$STORE_SEED" 2>/dev/null || true

# --- 7b. recompute scores (uses fresh labels) + de-identify + build public data ---
# This is the former GitHub Actions "refresh live data" work, moved local so the
# whole pipeline is one flow. run_pipeline reads posts.jsonl + the label cache.
log "recompute results from posts + labels"
python3 - <<'PY' || die "recompute"
from cvs_radar.pipeline import run_pipeline
from cvs_radar.store import load_posts, save_results
posts = load_posts("data/posts.jsonl")
reports, profiles = run_pipeline(posts)
save_results(reports, profiles, "data/results.json")
print(f"[recompute] {len(reports)} reports")
PY
# PRIVACY: strip per-account profiles before anything is committed/published.
python3 scripts/strip_profiles.py data/results.json || die "strip_profiles"
python3 web/build_data.py 2>&1 | tail -1 || die "build_data"

# --- 8. commit (+push): labels + recomputed, de-identified public data ---
if [ "$DO_COMMIT" = "1" ]; then
  git add data/labels/sentiment_fingerprint_labels.csv data/results.json web/public/data.json
  if git diff --cached --quiet; then
    log "no data change to commit"
  else
    git commit -q -m "chore: refresh live data + LLM sentiment labels (cache ${before}→${after})

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
    [ "$PUSH" = "1" ] && { git push -q origin "$BRANCH" && log "pushed to origin/$BRANCH"; }
  fi
fi

log "DONE. delta labeled=$N | cache ${before} -> ${after} | pushed=${PUSH}"
