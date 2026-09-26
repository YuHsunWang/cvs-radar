#!/usr/bin/env bash
# rebackfill.sh — the production data-refresh pipeline for CVS Radar (review #9).
#
# This is the reproducible, versioned copy of the pipeline that keeps the live
# site up to date. It is committed here so the process is documented and
# recoverable from the repo alone, rather than living only on the author's
# machine. See docs/ops-pipeline.md for how it is scheduled and monitored.
#
# Pipeline: crawl fresh PTT data -> backfill author review text -> export the
# still-unlabeled delta -> label it with TypeSafe Jev -> import (validates) into
# data/labels/sentiment_fingerprint_labels.csv -> recompute scores ->
# atomically save de-identified results -> build public data.json -> commit (+push).
# Re-runnable: each run only labels comments not already in the cache/legacy.
#
# NOTE: sentiment labeling needs TYPESAFE_API_KEY and the other label layers need
# a local Codex CLI (RUNNER); neither is reproducible in CI; everything else is
# standard python + git and portable.
#
# Env overrides: REPO BRANCH WT STORE_SEED PAGES REFRESH_DAYS CONC
#                DO_COMMIT PUSH RUNNER TYPESAFE_ENV
set -uo pipefail

REPO="${REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
BRANCH="${BRANCH:-main}"   # label cache lives on main since PR #12/#13 merged
WT="${WT:-$HOME/.cache/cvs-rebackfill-wt}"
STORE_SEED="${STORE_SEED:-$REPO/data/posts.jsonl}"   # persistent posts.jsonl seed
PAGES="${PAGES:-12}"
REFRESH_DAYS="${REFRESH_DAYS:-14}"
CONC="${CONC:-8}"
DO_COMMIT="${DO_COMMIT:-1}"
PUSH="${PUSH:-0}"   # default: commit in the worktree only; you push to main or open a PR
RUNNER="${RUNNER:-$HOME/.claude/skills/codex-direct/scripts/run-codex.mjs}"

log(){ echo "[rebackfill] $*"; }
die(){ echo "[rebackfill] FAILED: $*" >&2; exit 1; }

command -v node >/dev/null || die "node not found"
[ -f "$RUNNER" ] || die "run-codex.mjs not found at $RUNNER"
# Sentiment, category and grounding are labelled by TypeSafe Jev; its key lives
# outside the repo.
TYPESAFE_ENV="${TYPESAFE_ENV:-$HOME/.config/typesafe/env}"
# shellcheck source=/dev/null
[ -n "${TYPESAFE_API_KEY:-}" ] || { [ -f "$TYPESAFE_ENV" ] && . "$TYPESAFE_ENV"; }
[ -n "${TYPESAFE_API_KEY:-}" ] || die "TYPESAFE_API_KEY not set (put it in $TYPESAFE_ENV)"
python3 -c "import typesafe_sdk" 2>/dev/null || die "typesafe-sdk not installed (pip install typesafe-sdk)"

# --- 0. worktree on BRANCH (reuse if present, always reset to origin) ---
cd "$REPO" || die "no repo at $REPO"
git fetch -q origin "$BRANCH" || die "git fetch $BRANCH"
if git worktree list --porcelain | grep -q "worktree $WT"; then
  git -C "$WT" fetch -q origin "$BRANCH"
  git -C "$WT" checkout -q "$BRANCH" 2>/dev/null \
    || git -C "$WT" checkout -q -B "$BRANCH" "origin/$BRANCH" 2>/dev/null
  # git refuses to check out a branch another worktree already holds, and both
  # attempts above then fail quietly. The reset below would still succeed — it
  # would move whichever branch this worktree is on to BRANCH's commit — and the
  # run would crawl, label, recompute and commit onto that branch without a word.
  # A 2026-08-27 run put its data commit on the main clone's feature branch that
  # way. Confirm the checkout took before anything writes.
  on_branch="$(git -C "$WT" rev-parse --abbrev-ref HEAD 2>/dev/null || echo HEAD)"
  [ "$on_branch" = "$BRANCH" ] || die \
    "worktree $WT is on '$on_branch', not '$BRANCH' (another worktree probably holds that branch)"
  # A run whose push was rejected leaves its commit here, and the reset below would
  # destroy it together with every label that run paid for. Park it on a branch first
  # so the labels can still be recovered by hand.
  if ! git -C "$WT" merge-base --is-ancestor HEAD "origin/$BRANCH" 2>/dev/null; then
    keep="rebackfill-unpushed-$(date -u +%Y%m%dT%H%M%SZ)"
    git -C "$WT" branch "$keep" HEAD && log "kept an unpushed commit as branch $keep"
  fi
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
# The worktree store is the working copy; the seed is its mirror, refreshed from
# it at the end of every successful run. Reconcile BOTH ways before crawling.
# Seeding only when the worktree store was missing meant a seed replaced out of
# band -- a corpus backfill published straight into $REPO/data -- sat unused
# while the run recomputed and published from the older worktree copy, dropping
# every post the backfill had added (2026-08-26: 2,342 products -> 812) and then
# mirroring the smaller store back over the seed at the end. The reconcile is
# append-only on post id, so the worktree's fresher comment snapshots always win
# and neither side can lose posts.
mkdir -p data
if [ ! -s data/posts.jsonl ] && [ -s "$STORE_SEED" ]; then
  cp "$STORE_SEED" data/posts.jsonl
  log "seeded posts.jsonl from $STORE_SEED ($(wc -l < data/posts.jsonl) posts)"
elif [ -s "$STORE_SEED" ]; then
  python3 - "$STORE_SEED" data/posts.jsonl <<'PY' || die "seed reconcile"
import json, os, sys

seed, store = sys.argv[1], sys.argv[2]


def rows(path):
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)


have = {row["id"] for row in rows(store)}
missing = [row for row in rows(seed) if row["id"] not in have]
if not missing:
    print("seed reconcile: store already covers the seed")
else:
    with open(store, encoding="utf-8") as handle:
        body = handle.read()
    if body and not body.endswith("\n"):
        body += "\n"
    tmp = store + ".reconcile"
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(body)
        for row in missing:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, store)
    print(f"seed reconcile: appended {len(missing)} post(s) from {seed}")
PY
fi
[ -s data/posts.jsonl ] || die "no posts.jsonl seed available (set STORE_SEED)"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/rebackfill.XXXXXX")" || die "mktemp"
mkdir -p "$WORK/logs"
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
# Only the sentiment layer can be empty here. The product-name, excerpt and
# comment-pick layers can still have a delta (a new post with no comments produces
# exactly that), and the recompute/publish steps must run either way or a crawled
# post never reaches the site. So skip the sentiment steps, not the whole run.
# The steps below are left unindented on purpose: they embed heredocs whose
# terminators and Python bodies must stay at column 0.
before=0; after=0
if [ "$N" -eq 0 ]; then
log "no new comments to label — skipping the sentiment layer only"
else
# --- 3. label with TypeSafe Jev (the rubric lives in scripts/label_sentiment_jev.py) ---
log "labeling $N comment(s) with Jev, concurrency $CONC"
python3 scripts/label_sentiment_jev.py "$WORK/delta.csv" --out "$WORK/all_labeled.csv" \
        --concurrency "$CONC" 2>&1 | tail -1 || die "Jev sentiment labeling"

# --- 7. import into the real cache ---
before="$(python3 -c "import csv;print(sum(1 for _ in csv.DictReader(open('data/labels/sentiment_fingerprint_labels.csv',encoding='utf-8-sig'))))" 2>/dev/null || echo 0)"
python3 scripts/import_llm_backfill.py "$WORK/all_labeled.csv" \
        --labels data/labels/sentiment_fingerprint_labels.csv 2>&1 | tail -1 || die "import"
after="$(python3 -c "import csv;print(sum(1 for _ in csv.DictReader(open('data/labels/sentiment_fingerprint_labels.csv',encoding='utf-8-sig'))))")"
fi
# refresh the persistent seed so the next run continues from here
cp data/posts.jsonl "$STORE_SEED" 2>/dev/null || true

# --- 7a. the remaining LLM label layers, in dependency order ---
# Each of these is a judgement an LLM makes once and caches in a committed CSV, the
# same pattern as the sentiment step above. Running them here — after the crawl and
# before the recompute — is what lets a post crawled this morning reach the site with
# its labels today; 近期推薦 puts the newest products on the front page, so anything
# still on the rule fallback is exactly what visitors see first.
#
# Order matters: the excerpt and comment-pick fingerprints both include the product
# name, so names have to be settled before those two export their deltas. Each script
# exports its own delta, so it sees the names the step before it just imported.
#
# A failure leaves the new raw store available for retry but must not recompute,
# commit, or publish a rule-fallback snapshot as though semantic labeling succeeded.
bash scripts/ops/run_required_label_layers.sh || die "required semantic labeling"

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
# --- 7c. categories: label the products the recompute just settled on ---
# This layer is not in run_required_label_layers.sh because it cannot run there:
# its fingerprint is keyed to the final product name, which only exists once the
# recompute above has written results.json. build_data resolves each category
# through the cache, so labels imported here reach the snapshot without a second
# recompute. Like the layers above it, a failure stops the run rather than
# shipping a snapshot whose categories quietly fell back to the keyword rule.
bash scripts/label_product_categories.sh || die "category labeling"

# --- 7d. official calories (7-11 + FamilyMart catalogues) ---
# Optional by design: a catalogue outage must not cost the day's publish. On
# failure the committed official_kcal.csv is left as it was and build_data uses it.
# FamilyMart opens a real Chrome window through WSLg (its API refuses scripts).
python3 scripts/fetch_official_kcal.py 2>&1 | tail -2 \
  || log "WARN: official calorie refresh failed; publishing with the cached values"

python3 web/build_data.py 2>&1 | tail -1 || die "build_data"

# --- 8. commit (+push): labels + recomputed, de-identified public data ---
if [ "$DO_COMMIT" = "1" ]; then
  # Every label cache this run may have written has to be committed. Step 0 resets the
  # worktree to origin, so an uncommitted label file is silently destroyed before the
  # next run — and the layer would be paid for and re-labelled every single day.
  # grounding_verdicts.csv was missing from this list until 2026-08-27 and was being
  # re-adjudicated daily for exactly that reason.
  git add data/labels/sentiment_fingerprint_labels.csv \
          data/labels/product_name_labels.csv \
          data/labels/excerpt_labels.csv \
          data/labels/comment_picks.csv \
          data/labels/product_category_labels.csv \
          data/labels/grounding_verdicts.csv \
          data/labels/official_kcal.csv \
          data/results.json web/public/data.json
  if git diff --cached --quiet; then
    log "no data change to commit"
  else
    git commit -q -m "chore: refresh live data + LLM labels (sentiment cache ${before}→${after})

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>" || die "git commit"
    # This script runs without `set -e`, so a rejected push (main moved while the run
    # was labelling) used to fall through to DONE, exit 0, and let the cron mark the
    # day a success while the site stayed stale. It has to fail the run.
    if [ "$PUSH" = "1" ]; then
      git push -q origin "$BRANCH" \
        || die "git push to origin/$BRANCH (the commit stays in $WT; the next run parks it on a branch)"
      log "pushed to origin/$BRANCH"
    fi
  fi
fi

log "DONE. delta labeled=$N | cache ${before} -> ${after} | pushed=${PUSH}"
