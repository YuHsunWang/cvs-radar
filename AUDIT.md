# Project Audit — CVS Radar

Read-only audit. No source file was modified. Date: 2026-09-22.

> **Corrections, 2026-09-22 (after Codex independently re-validated every finding).**
> Two things in this report were wrong and have been fixed in place below:
> **BUG-003 is WITHDRAWN** — the pre-push pytest gate is not broken; the failure it was
> built on could not be reproduced. **The "24 merged products" figure was wrong** — the
> published payload contains **zero** merged products; the 24 is the number of products
> excluded by `product_overrides.csv`. That makes BUG-002 and BUG-013 fully latent rather
> than lightly exercised. Both corrections are marked where they occur.

- Repository: `git@github.com:YuHsunWang/cvs-radar.git` (public)
- Local checkout: `~/github-work/YuHsunWang/cvs-radar-clean`, detached at `origin/main` = `01dc1a0`
- Main branch: `main`
- Linear: team `Shane_wang` (DEV), project **CVS Radar** (`P-DEV-1`)

---

## Executive Summary

### Areas inspected

| Area | Files |
|---|---|
| Batch pipeline (Python) | `crawl_job.py`, `cvs_radar/**` (25 modules incl. `scoring/` package) |
| Public data projection | `web/build_data.py` (533 lines) |
| Frontend (static Next.js export) | `web/app/**`, `web/components/**`, `web/lib/**` |
| Ops / publishing | `scripts/ops/rebackfill.sh`, `rebackfill-cron.sh`, `run_required_label_layers.sh`, `scripts/check_data_freshness.py` |
| LLM label layers | `scripts/jev_labelers.py`, `scripts/label_sentiment_jev.py`, `scripts/verify_grounding.sh`, `scripts/import_*.py`, `cvs_radar/label_validation.py` |
| API (not deployed) | `cvs_radar/api.py`, `cvs_radar/api_auth.py`, `cvs_radar/service.py`, `cvs_radar/reporting.py` |
| Privacy invariants | `cvs_radar/store.py`, `scripts/strip_profiles.py`, `tests/test_publish_privacy.py` |
| CI / deployment | 5 GitHub Actions workflows, Vercel + GitHub Pages mirror |
| Docs | `AGENTS.md`, `README.md`, `CONTEXT.md`, `docs/TRAPS.md`, `docs/ops-pipeline.md`, `docs/DECISIONS.md`, `CVS-Radar-PRD-v0.2.md` |

There is **no database and no runtime server**. The product is a static export over a
single committed `web/public/data.json`. Sections of the requested template that assume
a DB, session auth, or a live API surface therefore have nothing to report; that is a
property of the architecture, not an omission.

### Tests executed

| Command | Result |
|---|---|
| `python -m pytest -q` (repo root, as `AGENTS.md` documents) | **353 passed** — see the BUG-003 withdrawal note; an earlier run of this command reported a collection error that could not be reproduced |
| `PYTHONPATH=. python -m pytest -q` | **353 passed** (identical result) |
| `ruff check .` | clean (ruff 0.15.20) |
| `cd web && npm test` | **55 passed**, 4 files (vitest 4.1.10) |
| `cd web && npx tsc --noEmit` | **FAILS — 1 error**, `lib/soft-serve.test.ts(13,3) TS2322` (see BUG-006) |
| `cd web && npm run build` | passed, 8 static pages exported, exit 0 |
| `cd web && npm run build:data` + `git diff --exit-code -- web/public/data.json` | **no drift** — the CI reproducibility gate holds |

### GitHub context reviewed

- Open PRs: **0**. Open issues: **0** (the repo has no issues at all, open or closed).
- Last 15 Actions runs (CI + Deploy GitHub Pages): **all success**, most recent `2026-09-22T01:01:20Z`.
- Recent merged PRs reviewed: #34, #33, #32, #31, #30, #29, #28, #27, #26, #25, #24, #22.
- `git blame`/`git show` used on `0d8d5a4` (PR #33, the newest behaviour change). It is
  well-scoped, measured before/after on the real corpus, and carries tests. No regression found.
- Two remote branches are unmerged and stale: `chore/data-architecture-phase1` (55 commits
  behind), `design/direction-02-retail-shelf-system` (42 behind).
- No TODO/FIXME/XXX/HACK markers exist anywhere in the Python, TS or shell sources.

### Linear context reviewed

47 issues in project CVS Radar. 1 Ready+High (DEV-193), 1 In Progress (DEV-144),
1 Backlog (DEV-108), 4 Canceled, 7 Ready+Low (roadmap wishes), rest Done.
Detail in **Linear discrepancies** below.

### Findings by severity

| Severity | Count |
|---|---|
| P0 | 0 |
| P1 | 1 |
| P2 | 2 |
| P3 | 9 |
| **Total** | **12** |
| *Withdrawn* | *1 (BUG-003)* |

Plus 3 items listed under *Suspected issues requiring manual verification*.

Overall the codebase is in unusually good shape: privacy is enforced at the write
boundary rather than by a cleanup step, the publish path has atomic writes, a
product-count collapse gate and a freshness SLO, and nearly every non-obvious decision
carries a comment explaining the incident that caused it. The findings below are real
but none is a live outage or a data-loss risk.

---

## Findings

### BUG-001 — Product-name extraction deletes the `x` between Chinese characters, so the soft-serve zone reads ~86% of swirls as single flavours

**Severity:** P1
**Confidence:** High
**Component:** pipeline / scoring (`cvs_radar/scoring/identity.py`) → frontend `/soft-serve`
**Related Linear:** [DEV-193](https://linear.app/shane-wang/issue/DEV-193) — status **Ready**, priority High
**Related GitHub:** feature landed in PR #16 (`feat/soft-serve-zone`); no fix PR exists

**Affected files:**
- `cvs_radar/scoring/identity.py:373`
- `cvs_radar/scoring/identity.py:572`
- `web/lib/soft-serve.ts:7` (`FLAVOR_SEPARATOR`), `web/lib/soft-serve.ts:14` (`DUAL_FLAVOR_OVERRIDES`)
- `web/components/SoftServeZone.tsx`

**Expected behavior:**
`/soft-serve` compares a flavour eaten alone against the same flavour in a two-flavour
swirl. `web/lib/soft-serve.ts` derives the flavour count purely from the product name:
a swirl is spelled `A x B霜淇淋`. Every dual-flavour product should therefore reach
`data.json` with its `x`/`X`/`×` intact.

**Actual behavior:**
Both name-cleaning paths run
`re.sub(r"(?<=[一-鿿])[xX×](?=[一-鿿])", " ", s)` and then collapse all
whitespace, so any separator sitting between two Chinese characters is deleted. The
swirl arrives at the frontend as one run-on name, is read as a single flavour, and its
comparison card silently never renders. There is no error and no log line.

**Evidence** (measured against the committed `web/public/data.json` at `01dc1a0`, today):

```
soft-serve products (name contains 霜淇淋) : 113
names still carrying x / X / ×            :  16   (14%)
flavour groups the zone can build         :  18
groups with both a single and a swirl     :  15
```

`起司蛋糕比利時巧克力霜淇淋` is in the payload as a visibly de-separated swirl — it is the
single entry in the hand-maintained `DUAL_FLAVOR_OVERRIDES` map, which exists only
because of this bug. The numbers are unchanged from the 2026-09-18 measurement recorded
on DEV-193, so nothing has regressed or improved since the ticket was filed.

**Root cause:**
The `x`-between-CJK rule was written to strip marketing cross-product noise
(`聯名x品牌`) during name cleaning. It cannot distinguish that from the flavour
separator, and it runs before the name is frozen into the label-cache key. Once
stripped, the information is gone — the frontend has no other flavour-count signal
(`web/lib/soft-serve.ts:3-6` says so explicitly).

**Reproduction steps:**
1. `cd ~/github-work/YuHsunWang/cvs-radar-clean`
2. `python3 -c "import json,re; d=json.load(open('web/public/data.json')); ss=[p for p in d['products'] if '霜淇淋' in p['productName']]; print(len(ss), sum(1 for p in ss if re.search('[xX×]', p['productName'])))"`
3. Observe `113 16`.
4. Open `/soft-serve/` in the built site and count the comparison cards: 18 groups, of which 15 are actually comparable.

**Suggested fix (do not implement):**
Preserve the separator through extraction instead of reconstructing it in the frontend.
Either (a) narrow the regex so it only fires when the `x` is *not* flanked by two
plausible flavour tokens, or (b) — more robust — normalise the separator to a single
canonical character (e.g. `×`) early in `_clean_extracted_product_name` and add it to
the allowed character class at `identity.py:585`, rather than deleting it. Whichever
path is taken, **trap 1 applies**: the product name is the label-cache key, so changing
it re-keys `product_name_labels.csv`, `excerpt_labels.csv` and `comment_picks.csv`.
A migration that rewrites the existing cache keys must land in the same change, and the
verification must be a full before/after pipeline run diffing the report name set — not
a unit test (see `AGENTS.md`, "Verifying a claim about behaviour").

**Regression test needed:**
A pipeline-level test in `tests/test_core.py` asserting that a post titled
`[商品] 全家 起司蛋糕x莊園牛奶霜淇淋 45元` produces a report whose `product_name`
still contains a flavour separator, plus a `web/lib/soft-serve.test.ts` case asserting
`splitFlavors` returns two flavours for that exact published name. The existing
soft-serve tests all feed hand-written names that already contain `x`, so they cannot
fail on this bug.

**Risk of fixing:**
High blast radius. Re-keying the label caches without a migration orphans thousands of
paid LLM labels and silently re-labels them (money + drift). Product names also feed
`product_overrides.csv` ids and the public `data.json` `id` field, so stale override
rows would stop matching. Expect the product count and several scores to move; the
`assert_no_product_collapse` gate (20%) will catch a catastrophic mistake but not a
subtle one.

---

### BUG-002 — A merged product with insufficient evidence still ships a recommendation score, violating a documented invariant

**Severity:** P2
**Confidence:** High (deterministically reproduced)
**Component:** public data projection (`web/build_data.py`)
**Related Linear:** none
**Related GitHub:** none. Listed as a known-unfixed item in the 2026-09-15 data-engineering review (PR #28's description), never ticketed.

**Affected files:**
- `web/build_data.py:240-243` (merged path sets `recommendationScore` unconditionally)
- `web/build_data.py:244-267` (the same block suppresses the percentage distribution but not the score)
- `web/build_data.py:352-360` (`calibrate_recommendation_scores`, the single-product path, which *does* gate)

**Expected behavior:**
`AGENTS.md`, under *Invariants*: "**Low-sample products don't show a recommendation
score** or a percentage distribution. The gating is deliberate, not a rendering bug."
The single-product path honours this — `calibrate_recommendation_scores` skips any
report whose `confidence == "低"` or `consensus == "資料不足"`, so those products reach
the payload with `recommendationScore: null`.

**Actual behavior:**
When two or more source reports canonicalize to the same public id, `merge_products`
recomputes the aggregate itself. It assigns
`merged["recommendationScore"] = calibrate_recommendation_score(merged_fair_score)`
*before* it computes `merged["confidence"]` and `merged["consensus"]`, and never
revisits it. The distribution is correctly nulled a few lines later; the score is not.
A merged product can therefore display a headline number while simultaneously
displaying "資料不足" and no sentiment bar.

**Evidence** — deterministic, run at `01dc1a0`:

```
$ PYTHONPATH=. python3 -c "
import sys; sys.path.insert(0,'web')
from build_data import merge_products
base = dict(id='A::B', ..., consensus='資料不足', confidence='低',
            _scoreWeight=0.5, _scoreWeightedSum=0.35, _scoreWeightSquareSum=0.25, ...)
out = merge_products([dict(base), dict(base)])[0]
print(out['confidence'], out['consensus'], out['recommendationScore'], out['positivePct'])"
低 資料不足 67 None
```

A low-confidence, "insufficient data" product comes out with a recommendation score of
**67/100** and a suppressed distribution.

Current live exposure is **zero**, and more completely so than this report first claimed.
`merge_products` currently produces **no merged groups at all**: the pipeline emits 2,392
reports and `product_overrides.csv` excludes 24 of them, which is the whole of the
2,392 → 2,368 gap. (An earlier draft read that 24 as a merge count; it is not.) The defect
is therefore entirely latent — reachable code that no published product currently enters.
Consistent with that, `[p for p in products if (p['confidence']=='低' or p['consensus']=='資料不足') and p['recommendationScore'] is not None]` returns `[]`.

**Root cause:**
The merge path re-implements the scoring projection instead of reusing the gate. The
gate lives in `calibrate_recommendation_scores`, which only ever runs over the
pre-merge reports.

**Reproduction steps:**
1. `cd ~/github-work/YuHsunWang/cvs-radar-clean`
2. Build two product dicts that share an `id` and each carry tiny `_scoreWeight` values (n_eff below `CONSENSUS.n_eff_min`).
3. Call `merge_products([a, b])`.
4. Observe `confidence == '低'`, `consensus == '資料不足'`, and a non-null `recommendationScore`.

**Suggested fix (do not implement):**
In `merge_products`, after `merged["confidence"]` and `merged["consensus"]` are
computed, apply the same predicate `calibrate_recommendation_scores` uses:
if `confidence == "低"` or `consensus == "資料不足"`, set both `fairScore` and
`recommendationScore` to `None` alongside the percentages. Better still, extract the
predicate into one named helper (e.g. `def has_publishable_score(confidence, consensus)`)
and call it from both paths so they cannot drift again.

**Regression test needed:**
In `tests/test_web_build_data.py`, a test named for the invariant — e.g.
`test_merged_low_evidence_product_shows_no_recommendation_score` — that merges two
members whose combined `n_eff` is below `CONSENSUS["n_eff_min"]` and asserts
`merged["recommendationScore"] is None` **and** `merged["positivePct"] is None`.
Asserting both is what makes it fail on a logic change rather than on a rendering
tweak. The file already has merge tests (`:288`, `:447`) but every one of them uses
high-evidence members, so none can catch this.

**Risk of fixing:**
Low. It can only remove scores, never add them. Any product it blanks would move from a
score to "資料不足" on the shelf — which is the documented intent. It will change
`web/public/data.json`, so the fix must land together with a rebuilt payload or CI's
`git diff --exit-code -- web/public/data.json` gate goes red.

---

### BUG-003 — WITHDRAWN: the documented pre-push test command is not broken

**Severity:** ~~P2~~ — **withdrawn, not a defect**
**Confidence:** High that the original finding was wrong
**Component:** test infrastructure
**Related Linear:** none
**Related GitHub:** none

**What this finding claimed:**
That `python -m pytest -q` from the repo root — the gate `AGENTS.md:29-35` tells
contributors to run before pushing — fails on a clean local machine with
`ModuleNotFoundError: No module named 'cvs_radar'`, because pytest 9 no longer inserts
the invocation directory into `sys.path` and the repo has no `conftest.py` or
`pythonpath` setting. The proposed fix was `[tool.pytest.ini_options] pythonpath = ["."]`.

**Why it is withdrawn:**
The failure is not reproducible. Checked three ways:

```
# 1. The baseline commit, in an isolated worktree with no prior state
$ git worktree add --detach /tmp/baseline-wt 01dc1a09b9caea693490b9b69884a82ad69a5ccb
$ cd /tmp/baseline-wt && python -m pytest -q --collect-only
353 tests collected in 1.32s          # exit 0, zero ModuleNotFoundError

# 2. The same command in the main checkout, after the fix branch landed
$ python -m pytest -q
358 passed, 2 warnings, 69 subtests passed in 231.09s      # zero ModuleNotFoundError

# 3. The single module that had failed, re-run directly
$ python -m pytest -q tests/test_store.py
16 passed in 0.49s
```

No `conftest.py`, no `[tool.pytest.ini_options]`, no `PYTHONPATH`, and `pip show
cvs-radar` reports the package is not installed — that is, the exact configuration the
finding described, collecting and running cleanly. Nothing in the fix branch touched
`pyproject.toml` or added a conftest, so the difference cannot be attributed to a fix.

The collection errors that produced this finding were real output, observed more than
once, but they are intermittent and I could not characterise the trigger. They correlated
with a second pytest process running concurrently in the same checkout, which would fit a
race on import/bytecode state — but that is an untested hypothesis, and stating it as the
cause would be exactly the error this finding already made once. The honest conclusion is
that the evidence never supported a repository defect.

**Consequences for the rest of this report:**
- The "Tests executed" table has been corrected: the gate passes.
- BUG-007 is a genuine and *separate* problem. Its root cause is that a script run as
  `python3 scripts/x.py` puts `scripts/` — not the repo root — at `sys.path[0]`. The claim
  in this report that BUG-003 and BUG-007 "share an import-path root cause" was wrong.
- The suggested CI job "run the suite without installing the package" is no longer
  motivated by a known failure. It is still cheap insurance against a future pytest
  behaviour change, but it is a nice-to-have, not a fix.

**Suggested fix:** none. Do not add `pythonpath = ["."]` to work around a failure that
cannot be demonstrated.

---

### BUG-004 — The manual fallback refresh workflow seeds the corpus from a branch that no longer exists

**Severity:** P2
**Confidence:** High
**Component:** CI / disaster recovery
**Related Linear:** [DEV-109](https://linear.app/shane-wang/issue/DEV-109) — "徹底從 git 歷史抹除 ui/mobile-redesign 的 raw posts.jsonl", status **Done**
**Related GitHub:** `.github/workflows/refresh-data.yml`

**Affected files:**
- `.github/workflows/refresh-data.yml:50-66` ("Seed crawl history on cache miss")
- `docs/improvement-plan-2026-07-20.md:129` (same dead reference, historical doc)

**Expected behavior:**
`refresh-data.yml` is the documented manual fallback "for when the local machine is
unavailable" (`.github/workflows/refresh-data.yml:5-9`, echoed in `AGENTS.md`). On an
Actions cache miss it is supposed to seed `data/posts.jsonl` from the
`ui/mobile-redesign` branch "so the live dataset keeps its existing ~772 products
instead of collapsing to a single 10-page window".

**Actual behavior:**
`ui/mobile-redesign` was deleted as part of the PII history purge (DEV-109, Done). The
remote now holds exactly three branches:

```
$ git ls-remote --heads origin
refs/heads/chore/data-architecture-phase1
refs/heads/design/direction-02-retail-shelf-system
refs/heads/main
```

The seed step is written to fail soft (`echo "Seed branch unavailable; starting fresh"`),
so a cache-miss run proceeds with an empty store, crawls a 10-page window, and — because
this workflow pushes straight to `main` — publishes a drastically smaller dataset. The
`assert_no_product_collapse` gate in `web/build_data.py:88` is the only thing standing
between that and a 2,368 → ~100 product publish, and it only fires because the committed
`data.json` happens to be there to compare against.

`seed-cache.yml` exists as the real recovery path (operator supplies a temporary URL),
and `docs/runbook-data-recovery.md` documents it — but `refresh-data.yml` never mentions
it, so someone reaching for the fallback in an emergency reads a comment describing a
recovery route that cannot work.

**Evidence:**
- `git ls-remote --heads origin` (above) — no `ui/mobile-redesign`.
- `.github/workflows/refresh-data.yml:59`: `if git fetch --depth=1 origin ui/mobile-redesign; then`
- `export-llm-backfill.yml:34-44` correctly does *not* have a seed fallback and fails loudly instead, with the fix spelled out in the error — the pattern `refresh-data.yml` should follow.

**Root cause:**
The branch was deleted for privacy reasons; the workflow that depended on it was not
updated. Nothing tests a manual-dispatch workflow, so nothing caught it.

**Reproduction steps:**
1. Confirm no `cvs-posts-*` Actions cache exists (or wait for the 7-day eviction — this workflow has not run since 2026-07-21, so the cache is almost certainly already gone).
2. `gh workflow run refresh-data.yml` on `main`.
3. Observe the seed step print "Seed branch unavailable; starting fresh" and the crawl proceed against an empty store.

**Suggested fix (do not implement):**
Delete the seed-from-branch step and replace it with the same fail-loud guard
`export-llm-backfill.yml` already uses: if `data/posts.jsonl` is empty after cache
restore, error out and point the operator at `seed-cache.yml` and
`docs/runbook-data-recovery.md`. Do not add a new seed branch — committing
`posts.jsonl` anywhere is the invariant the history rewrite was done to establish.

**Regression test needed:**
A cheap lint test in `tests/test_docs_runtime.py` style: parse the workflow YAML files
and assert that every `git fetch origin <branch>` / `origin/<branch>` reference names a
branch that still exists on the remote, or is explicitly allow-listed. Alternatively
assert the narrower fact — that the string `ui/mobile-redesign` appears in no file under
`.github/`.

**Risk of fixing:**
Low; the workflow is manual-dispatch only and has not been run since 2026-07-21. The
change makes a broken path fail visibly instead of silently, which is the point.

---

### BUG-005 — The convenience-store chain 美廉社 is misspelled 美聯社 throughout the pipeline, so its products can never be attributed

**Severity:** P3
**Confidence:** High
**Component:** config / brand taxonomy → frontend filters
**Related Linear:** none
**Related GitHub:** documented but never fixed in `web/UI_REDESIGN_PLAN.md:102-104`

**Affected files:**
- `config.yaml:26-27` (`"美聯社": ["美聯社"]`)
- `cvs_radar/config.py:18` (same, as the frozen default)
- `web/lib/data.ts:49` (`brands = [..., '美聯社', '其他']`)
- `web/components/ShelfCard.tsx:18` (colour keyed `美聯社`)
- `web/components/ShelfExplorer.tsx:42` (colour keyed **美廉社**) and `:46` (`HIDDEN_BRANDS = new Set(['美聯社'])`)
- `CONTEXT.md:22`, `CVS-Radar-PRD-v0.2.md:385`, `web/DESIGN.md:82`, `docs/redesign/README.md:14,21`

**Expected behavior:**
The Taiwanese chain is **美廉社**. Posts about it should be attributed to that brand and
appear under its own filter chip.

**Actual behavior:**
Every alias entry says 美聯社 (which is the Chinese name of the Associated Press, not a
shop). `infer_brand` therefore never matches a 美廉社 post; those products fall through
to `其他`. `web/lib/data.ts:brands` carries the misspelling too, so `displayBrand()` maps
any correctly-spelled 美廉社 brand to `其他` even if the pipeline ever produced one. The
frontend has then accumulated two pieces of dead code around the mistake: `ShelfExplorer`
defines a rail colour for the *correct* spelling (which nothing can ever key into) while
hiding the *incorrect* one, and `ShelfCard` defines a colour for the incorrect one.

**Evidence:**

```
$ grep -c 美廉社 data/posts.jsonl     # correct chain name in the raw corpus
4
$ grep -c 美聯社 data/posts.jsonl     # the misspelling
2
$ python3 -c "import json,collections; d=json.load(open('web/public/data.json')); print(collections.Counter(p['brand'] for p in d['products']))"
Counter({'全家': 1258, '7-11': 948, '萊爾富': 140, 'OK': 16, '其他': 6})
```

No `美聯社` and no `美廉社` bucket exists in the published payload. The comment at
`ShelfExplorer.tsx:45` — "美聯社 in lib/data is a typo for 美廉社 and has no products" —
diagnoses the bug correctly and then works around it instead of fixing it.

**Root cause:**
A typo in the original brand table, propagated by copy into the frontend constant, the
PRD, the design docs and `CONTEXT.md`. Because the misspelled brand matches nothing, it
produces no products, and "no products" was then read as "this chain is not discussed"
rather than "this brand key is wrong".

**Reproduction steps:**
1. `grep -n 美聯社 config.yaml cvs_radar/config.py web/lib/data.ts`
2. `grep -c 美廉社 data/posts.jsonl` → 4 posts exist.
3. Confirm no `美廉社` or `美聯社` brand appears in `web/public/data.json`.

**Suggested fix (do not implement):**
Correct the alias in `config.yaml` and `cvs_radar/config.py` to `美廉社` (keeping
`美聯社` as an *additional* alias is defensible — people do mistype it), correct
`web/lib/data.ts:brands`, delete `HIDDEN_BRANDS` and the duplicate colour entry, and
align `ShelfCard.tsx`. Update `CONTEXT.md` and `web/DESIGN.md`; leave the PRD alone, it
is marked a historical document. Expect a handful of products to move from `其他` to
`美廉社`, which will change `data.json` — rebuild it in the same commit.

**Regression test needed:**
A test asserting `infer_brand("", "[商品] 美廉社 XXX")` returns `美廉社`, and a
`web/lib/data.test.ts` case asserting `displayBrand('美廉社') === '美廉社'`. Also worth
a cheap consistency test that the Python brand list and the TS `brands` constant contain
the same names — that single assertion would have caught this the day the frontend was
written.

**Risk of fixing:**
Low, but it touches the brand taxonomy, which is a grouping key. Products moving out of
`其他` change their public `id` (`brand::productName`), so any `product_overrides.csv`
row keyed to the old `其他::…` id stops matching — check that file for affected rows
before shipping.

---

### BUG-006 — `tsc --noEmit` fails and no gate catches it

**Severity:** P3
**Confidence:** High
**Component:** web / test infrastructure
**Related Linear:** none
**Related GitHub:** the `reviewProvisional` field was added in PR #24

**Affected files:**
- `web/lib/soft-serve.test.ts:12-40` (the `product()` fixture)
- `.github/workflows/ci.yml:56-64` (the `web` job — runs `npm test` and `npm run build`, never `tsc --noEmit`)
- `AGENTS.md:29-35` (the pre-push list also omits it)

**Expected behavior:**
`web/tsconfig.json` sets `"strict": true` and includes `**/*.ts`, so the project should
typecheck cleanly.

**Actual behavior:**

```
$ cd web && npx tsc --noEmit; echo "exit=$?"
lib/soft-serve.test.ts(13,3): error TS2322: Type '{ ... }' is not assignable to type 'Product'.
  Types of property 'reviewProvisional' are incompatible.
    Type 'boolean | undefined' is not assignable to type 'boolean'.
exit=1
```

The `product()` helper builds a base object literal that omits `reviewProvisional`, then
spreads `...overrides` (typed `Partial<Product>`) over it, so the field's type is
`boolean | undefined` while `Product` requires `boolean`. The sibling fixtures in
`lib/data.test.ts:46` and `components/ShelfCard.test.ts:44` both include the field — only
this one was missed.

Nothing catches it: `npm test` (vitest) does not typecheck, and `next build` exits 0
because Next's type check does not reach files outside the app's import graph.

**Root cause:**
`reviewProvisional` was added to the `Product` type in PR #24 and back-filled into two of
the three test fixtures. The third was missed, and there is no typecheck gate to notice.

**Reproduction steps:**
1. `cd ~/github-work/YuHsunWang/cvs-radar-clean/web`
2. `npx tsc --noEmit`
3. Observe exit 1 with the error above.

**Suggested fix (do not implement):**
Add `reviewProvisional: false,` to the base literal in `soft-serve.test.ts`, then add
`npx tsc --noEmit` as a step in the `web` CI job and as a sixth line in the `AGENTS.md`
pre-push list. Adding the gate without adding it to `AGENTS.md` just relocates the
surprise to CI.

**Regression test needed:**
The CI step *is* the test. No unit test can express "the project typechecks".

**Risk of fixing:**
None for the one-line fixture fix. Adding the CI gate may surface further pre-existing
type errors in files `next build` does not reach — run it locally first and budget for
whatever else it finds.

---

### BUG-007 — Two scripts crash on import when run as documented from the repo root

**Severity:** P3
**Confidence:** High
**Component:** scripts / developer workflow
**Related Linear:** none
**Related GitHub:** `scripts/crawl_family_food.py` shipped in PR #21

**Affected files:**
- `scripts/crawl_family_food.py:9` (`from cvs_radar.family_food_crawler import FamilyFoodCrawler`)
- `scripts/strip_profiles.py`
- `README.md:192-193` (documents the `crawl_family_food.py` invocation)
- contrast: `web/build_data.py:17-19` does the `sys.path` bootstrap correctly

**Expected behavior:**
`README.md` gives `crawl_family_food.py` as a runnable command. Running it from the repo
root should work, exactly as `python web/build_data.py` does.

**Actual behavior:**

```
$ for s in scripts/*.py; do python3 "$s" --help >/dev/null 2>&1 || echo "FAILS: $s"; done
FAILS: scripts/crawl_family_food.py   -> ModuleNotFoundError: No module named 'cvs_radar'
FAILS: scripts/strip_profiles.py      -> ModuleNotFoundError: No module named 'cvs_radar'
```

All 27 other scripts in `scripts/` start fine. These two are the only ones importing
`cvs_radar` without the `sys.path` bootstrap that `web/build_data.py` uses.

Impact is limited: `strip_profiles.py` is only invoked by `refresh-data.yml`, which
`pip install`s the package first, and the privacy invariant no longer depends on it
(`cvs_radar/store.py:save_results` enforces it at the write boundary). `crawl_family_food.py`
is a documented manual tool. CI's only script smoke test is
`python scripts/backfill_reviews.py --help` (`ci.yml:22-23`), which passes.

**Root cause:**
A script executed as `python3 scripts/x.py` gets `scripts/` — not the repo root — as
`sys.path[0]`, so `import cvs_radar` cannot resolve unless the module bootstraps the root
itself, the way `web/build_data.py:17-19` does. (An earlier draft attributed this to the
same cause as BUG-003; that was wrong, and BUG-003 has since been withdrawn.)

**Reproduction steps:**
1. `cd ~/github-work/YuHsunWang/cvs-radar-clean`
2. `python3 scripts/crawl_family_food.py --help`
3. Observe `ModuleNotFoundError`.

**Suggested fix (do not implement):**
Either copy the four-line `ROOT`/`sys.path`
bootstrap from `web/build_data.py:16-19` into both scripts, or extend CI's smoke-test
step to loop over every file in `scripts/*.py` with `--help` so the next one is caught
immediately.

**Regression test needed:**
Replace the single-script smoke test in `ci.yml` with a loop over `scripts/*.py`
asserting `--help` exits 0 for each. Run it in a job that does *not* `pip install .`,
otherwise it cannot fail.

**Risk of fixing:**
None. Adding a `sys.path` bootstrap is inert when the package is already importable.

---

### BUG-008 — `data/results.json` records a naive timestamp that the reader re-interprets as Asia/Taipei

**Severity:** P3
**Confidence:** Medium (correct today; correct only because of an unstated environment assumption)
**Component:** pipeline ↔ public data projection
**Related Linear:** none
**Related GitHub:** the timezone work landed across PRs #28 (`53c21ea`) and earlier review batch #5

**Affected files:**
- `cvs_radar/store.py:save_results` — `"generated_at": datetime.now().isoformat(sep=" ", timespec="seconds")`
- `web/build_data.py:47-50` — `datetime.strptime(source_generated_at, "%Y-%m-%d %H:%M:%S").replace(tzinfo=TAIPEI_TIMEZONE)`
- `scripts/check_data_freshness.py:38-45` — raises `ValueError` on a timestamp with no timezone

**Expected behavior:**
Timestamps that cross a process boundary should carry their offset. `check_data_freshness.py`
takes this seriously enough to *refuse* a naive `generatedAt` rather than guess.

**Actual behavior:**
The producer writes a naive local timestamp; the consumer, two files away, unconditionally
stamps it `Asia/Taipei` and only then does the value become well-defined. The two halves
never agree in code — they agree because the publishing machine happens to be on
`Asia/Taipei` (verified: `/etc/timezone` = `Asia/Taipei`, `date` prints CST). Run the
pipeline on a UTC host — a container, a CI fallback, a new laptop — and every snapshot
is tagged eight hours later than it was produced, which inflates freshness and would let
a stale dataset pass the 14-day SLO for an extra third of a day.

The format coupling is equally implicit: `strptime` with `"%Y-%m-%d %H:%M:%S"` throws if
the producer ever emits microseconds or a `T` separator. That holds today only because
`save_results` passes `sep=" ", timespec="seconds"`.

**Evidence:**

```
$ python3 -c "import json; print(json.load(open('data/results.json'))['generated_at'])"
2026-09-22 09:01:05                     # naive
$ python3 -c "import json; print(json.load(open('web/public/data.json'))['generatedAt'])"
2026-09-22T09:01:05+08:00               # offset attached by the reader, not the writer
$ cat /etc/timezone
Asia/Taipei
```

**Root cause:**
`save_results` was not updated when the rest of the datetime handling was moved to
timezone-aware Taipei values (`cvs_radar/filters.normalize_datetime` does this correctly
everywhere else in the pipeline).

**Reproduction steps:**
1. `TZ=UTC python3 -c "from cvs_radar.pipeline import ...; save_results(...)"` (or simply `TZ=UTC date` to see the shift).
2. Run `python3 web/build_data.py`.
3. Compare `generatedAt` in the output against the real wall-clock time: it is eight hours ahead.

**Suggested fix (do not implement):**
Write an aware timestamp in `save_results` —
`datetime.now(TAIPEI_TZ).isoformat(timespec="seconds")` — and change
`resolve_data_timestamps` to `datetime.fromisoformat(...)`, treating a naive value as
Taipei only as a backward-compatibility fallback for snapshots written before the change.
`fromisoformat` also removes the format coupling.

**Regression test needed:**
A test in `tests/test_store.py` that monkeypatches `TZ=UTC`, calls `save_results`, and
asserts the written `generated_at` parses to a timezone-aware datetime whose UTC instant
matches `datetime.now(timezone.utc)` within a few seconds. A test that merely asserts the
string shape would pass on the buggy code.

**Risk of fixing:**
Low, but it changes the `generatedAt` string in `web/public/data.json`, so the fix must
ship with a rebuilt payload or CI's no-drift gate fails. Also confirm
`existing_site_built_at` (`build_data.py:69-79`) still parses the committed
`siteBuiltAt` — note that value is deliberately frozen at 2026-08-25 as the
reproducibility anchor and **must not be changed**.

---

### BUG-009 — README's headline statistics no longer match the published data

**Severity:** P3
**Confidence:** High
**Component:** documentation
**Related Linear:** none
**Related GitHub:** corrected once in PR #25's batch (`40a38a2`), drifted again since

**Affected files:**
- `README.md:118`

**Expected behavior:**
The README explains the "no score below `n_eff < 3`" rule with a concrete count. The
count should match the snapshot in the repo.

**Actual behavior:**

| | README claims | actual (`web/public/data.json` at `01dc1a0`) |
|---|---|---|
| products | 2,342 | **2,368** |
| without a score | 567 | **538** |
| share | 24.2% | **22.7%** |

**Evidence:**

```
$ python3 -c "
import json; d=json.load(open('web/public/data.json')); ps=d['products']
no=[p for p in ps if p['recommendationScore'] is None]
print(len(ps), len(no), f'{len(no)/len(ps)*100:.1f}%')"
2368 538 22.7%
```

**Root cause:**
Hard-coded numbers in prose next to a dataset that a cron job rewrites daily.
`tests/test_docs_runtime.py` asserts several README *sentences* but not these numbers,
so nothing notices.

**Reproduction steps:** compare `README.md:118` against the command above.

**Suggested fix (do not implement):**
Either round the claim to a stable form ("約四分之一的商品"), or — better, and in keeping
with how this repo already treats docs as testable — add the assertion to
`tests/test_docs_runtime.py` so the number is a gate rather than a decoration. Note that
making it a gate means every daily data refresh could turn CI red, so the tolerance has
to be a band, not an equality.

**Regression test needed:** the `test_docs_runtime.py` assertion described above.

**Risk of fixing:** none, unless the test is written as an exact match — then the
publishing cron starts breaking CI daily.

---

### BUG-010 — A tracked TypeScript build artifact

**Severity:** P3
**Confidence:** High
**Component:** repo hygiene
**Related Linear:** none

**Affected files:** `web/tsconfig.tsbuildinfo`

**Expected behavior:** `.tsbuildinfo` is an incremental-compilation cache; it belongs in
`.gitignore`.

**Actual behavior:** `git ls-files | grep tsbuildinfo` returns `web/tsconfig.tsbuildinfo`.
It is tracked, so it produces spurious diffs whenever anyone typechecks, and it can make
`git status` dirty in the cron worktree — which `scripts/ops/rebackfill.sh:75` hard-resets
each run, so the churn is invisible but real.

**Evidence:** `git ls-files | grep tsbuildinfo` → `web/tsconfig.tsbuildinfo`

**Root cause:** `"incremental": true` in `web/tsconfig.json` with no matching ignore rule.

**Reproduction steps:** `cd web && npx tsc --noEmit && cd .. && git status --short`

**Suggested fix (do not implement):** `git rm --cached web/tsconfig.tsbuildinfo` and add
it to `web/.gitignore`.

**Regression test needed:** none warranted.

**Risk of fixing:** none.

---

### BUG-011 — Two of five workflows use floating action tags while the other three are SHA-pinned

**Severity:** P3
**Confidence:** High
**Component:** CI / supply chain
**Related Linear:** none
**Related GitHub:** PR #24's batch pinned `ci`, `pages` and `refresh-data`; these two were not in scope

**Affected files:**
- `.github/workflows/export-llm-backfill.yml:25,28,34,52,57` (`@v4`, `@v5`)
- `.github/workflows/seed-cache.yml:60` (`@v4`)

**Expected behavior:**
The repo's stated posture (`AGENTS.md` and the PR #24 work) is that Actions are pinned to
a full commit SHA so a compromised or retagged action cannot change what runs.
`ci.yml`, `pages.yml` and `refresh-data.yml` all do this.

**Actual behavior:**
`export-llm-backfill.yml` and `seed-cache.yml` still use mutable major-version tags. Both
are `workflow_dispatch`-triggered, and `export-llm-backfill.yml` additionally runs on
push to `main` when `scripts/export_llm_backfill.py` changes — so it is not purely manual.
`export-llm-backfill.yml` handles the raw crawl store (the file with real PTT handles),
which makes it the *last* workflow that should run unpinned code.

**Evidence:**

```
$ grep -n "uses:" .github/workflows/export-llm-backfill.yml .github/workflows/seed-cache.yml
export-llm-backfill.yml:25:        uses: actions/checkout@v4
export-llm-backfill.yml:28:        uses: actions/setup-python@v5
export-llm-backfill.yml:34:        uses: actions/cache@v4
export-llm-backfill.yml:57:        uses: actions/upload-artifact@v4
seed-cache.yml:60:        uses: actions/cache@v4
```

versus `ci.yml:14`: `uses: actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803 # v6`.

**Root cause:** partial rollout — the pinning pass covered the three workflows that run
on every push and stopped there.

**Reproduction steps:** the grep above.

**Suggested fix (do not implement):** pin all five to full SHAs with a `# vN` trailing
comment, matching the existing style. Consider adding Dependabot for `github-actions` so
the pins stay current without hand-editing.

**Regression test needed:** a lint assertion that every `uses:` line under `.github/`
matches `@[0-9a-f]{40}`. It is three lines of Python and would have caught this.

**Risk of fixing:** low — pin to the SHA the tag currently points at, then verify each
workflow still dispatches successfully.

---

### BUG-012 — `label_excerpts.sh` and `label_comment_picks.sh` are 136-line near-duplicates

**Severity:** P3
**Confidence:** High
**Component:** LLM labelling layers
**Related Linear:** none
**Related GitHub:** flagged as unfixed in the 2026-09-15 review ("6 支標記腳本複製漂移")

**Affected files:**
- `scripts/label_excerpts.sh` (136 lines)
- `scripts/label_comment_picks.sh` (136 lines)
- `scripts/label_product_names.sh` (129 lines)
- `scripts/label_product_categories.sh` (48 lines — already the slim, non-chunking shape)

**Expected behavior:**
The four label-layer drivers share one control flow: export delta → chunk → run the
model → verify → import. A fix to that flow should apply everywhere at once.

**Actual behavior:**
Normalising the layer name away, `label_excerpts.sh` and `label_comment_picks.sh` differ
in **12 hunks**, almost all of them prose and a handful of column names and chunk sizes
(`CHUNK=100` vs `CHUNK=50`). The logic is otherwise identical and copied. `AGENTS.md`
trap 7 already warns that the layer order is encoded in `run_required_label_layers.sh`;
the layer *bodies* have no such single source.

This is a latent-defect generator, not a live bug: a correctness fix applied to one
script (a retry rule, a chunk-boundary guard, a rejection threshold) silently does not
apply to the other, and the divergence is invisible because the two files have the same
shape.

**Evidence:**

```
$ diff <(sed 's/excerpt/LAYER/g' scripts/label_excerpts.sh) \
       <(sed 's/comment_pick/LAYER/g;s/comment-pick/LAYER/g' scripts/label_comment_picks.sh) | grep -c '^[<>]'
24          # 12 hunks, essentially all comments + column lists + CHUNK size
```

**Root cause:** each new layer was created by copying the previous one.

**Reproduction steps:** the diff above.

**Suggested fix (do not implement):**
Extract the shared driver into one parameterised script (layer name, labels path, chunk
size, immutable column list, prompt path) and reduce each `label_*.sh` to a short
wrapper — the shape `label_product_categories.sh` already has at 48 lines. Do this as a
standalone change with a before/after label-cache diff on the same corpus, not bundled
with a behaviour fix.

**Regression test needed:**
Run each layer against a fixture delta and assert the imported cache is byte-identical
before and after the refactor. Because these scripts need a live LLM key and are not
reproducible in CI, that comparison has to be done by hand on the publishing machine and
recorded in the PR.

**Risk of fixing:**
Medium — these scripts spend money and write the committed label caches. A refactor that
subtly changes chunking or the fingerprint re-labels rows that were already paid for
(and, per trap 2, can collide labels). Keep the two chunk sizes distinct; they are tuned,
not accidental.

---

### BUG-013 — Merging two products sums their unique-commenter counts

**Severity:** P3
**Confidence:** Medium
**Component:** public data projection (`web/build_data.py`)
**Related Linear:** none

**Affected files:**
- `web/build_data.py:201-211` (the `for field in (...)` sum over merged members)
- `web/build_data.py:406-412` (`nComments` is `report.n_unique_commenters`, not a raw count)

**Expected behavior:**
`nComments` and `uniqueEligibleCommenters` are *distinct-person* counts —
`cvs_radar/scoring/compute.py:score_product` computes them as
`len({comment.user for comment in eligible_comments})`. The whole point of the field is
that one person cannot inflate it.

**Actual behavior:**
When two source reports merge into one public product, `merge_products` adds those
counts together. Someone who commented on both source threads is counted twice. The same
applies to `uniqueEligibleCommenters` and `independentThreads`. `rawComments` and
`nPosts` are genuine totals and are correctly summed.

The visible effect is a slightly overstated "how many people said this" figure on merged
products, which also feeds `discussionHeat` and `recentRecommendationScore` sorting in
`web/lib/data.ts:215-221`. It does not affect `fairScore` or `recommendationScore`,
which are recomputed from weights rather than counts.

**Evidence:**
`web/build_data.py:201-211` sums `nComments` and `uniqueEligibleCommenters` across
members; there is no de-duplication, and by the time `build_data` runs the identities are
gone — `save_results` blanks `contributors` at the write boundary, so the information
needed to de-duplicate does not exist in `data/results.json`. **Correction:** an earlier
draft said "24 of the 2,368 published products are merges". That is wrong — there are
currently **zero** merged products; the 24 is the count of products excluded by
`product_overrides.csv`. The defect is reachable but entirely latent today.

**Root cause:**
The merge loop treats every count field as additive. That is right for four of the six
fields and wrong for the two that are set cardinalities.

**Reproduction steps:**
1. Build two product dicts with the same `id`, each with `nComments: 5`.
2. `merge_products([a, b])`
3. Observe `nComments == 10`, with no way to know whether the same five people wrote both.

**Suggested fix (do not implement):**
This cannot be fixed inside `build_data.py` — the identities are (correctly) already
gone. The honest options are: (a) take `max()` rather than `sum()` for the two
set-cardinality fields, which understates rather than overstates; or (b) merge upstream,
in `cvs_radar/scoring`, where the commenter sets still exist, so the merged report is
computed from the union. (b) is correct; (a) is cheap. Do not "fix" it by publishing
contributor identities — that breaks the privacy invariant.

**Regression test needed:**
A test in `tests/test_web_build_data.py` merging two members that represent the same five
commenters and asserting the merged `nComments` does not exceed the true distinct count —
which requires the fixture to state that truth explicitly, i.e. the test only means
something under fix (b).

**Risk of fixing:**
(a) is trivial and changes `data.json` for ~24 products. (b) touches
`cvs_radar/scoring/identity.group_products` and is a scoring change — it needs the full
before/after pipeline diff described in `AGENTS.md`.

---

## Linear discrepancies

| Issue | Status | Finding |
|---|---|---|
| **DEV-193** — 商品名稱抽取會吃掉中文之間的 x | Ready (High) | **Consistent.** Verified still present and unchanged: the 2026-09-18 measurement on the ticket (113 / 15 / 18 / 15) reproduces exactly today. See BUG-001. |
| **DEV-144** — 開通 GA4 資料流 | In Progress | **Not verifiable from here.** The code side is complete and correct: `web/lib/analytics.ts` is a no-op unless `NEXT_PUBLIC_GA_ID` is set, `app/layout.tsx` only injects the script when it is, and `pages.yml:40-46` deliberately points the mirror's canonical URL at Vercel so the unmeasured copy does not absorb search traffic. Whether the GA4 property is receiving data is outside the repo. |
| **DEV-107** — 接 GA4 事件埋點 | Done | **Consistent.** All five documented events exist (`trackSearch`, `trackProductExpand`, `trackFilterApply`, `trackSortChange`, `trackOutboundPttClick`) and `trackSearch` sends only `query_length`/`result_count`, never the raw query — matching the privacy note the DEV-24 batch added to the footer. |
| **DEV-108** — 一鍵回報 MVP | Backlog, blocked on DEV-144 | **Consistent.** No reporting UI or endpoint exists. Correctly blocked. |
| **DEV-11** — 增量重算 pipeline | Ready | **Consistent.** `scripts/ops/rebackfill.sh` still recomputes the whole corpus every night (`run_pipeline(load_posts(...))`). Not started, as the status says. |
| **DEV-113** — CVS Radar Web 頁面重新設計 | **Canceled** | **Discrepancy.** The ticket was canceled as superseded, but a local branch `dev-113-implementation` still exists, `web/UI_REDESIGN_PLAN.md` and `docs/redesign/` remain in the repo referencing deleted files, and separate redesign work ("direction C", weekly-shelf concept) is live outside the repo in `~/github-work/YuHsunWang/cvs-radar-redesign-c/`, stopped at four undecided questions. The canceled ticket does not represent the actual state of that workstream. Either reopen a successor ticket for direction C or record the decision somewhere the repo can see. |
| **DEV-48 / DEV-47 / DEV-46** | Canceled | **Consistent.** All three target the retired Streamlit UI. Correctly canceled. |
| **DEV-109** — 徹底從 git 歷史抹除 ui/mobile-redesign 的 raw posts.jsonl | Done | **Partially inconsistent.** The branch is genuinely gone from the remote (verified), so the ticket is legitimately Done — but `.github/workflows/refresh-data.yml` still depends on it, which means "Done" left a broken recovery path behind. See BUG-004. |
| **DEV-96** — 聲量等級只看留言數 | Done | **Consistent.** `display_confidence` (`build_data.py:363-368`) downgrades a single-thread 高 to 中, and `volume_label` is re-derived on merge. |
| **DEV-112** — 品名標籤 fingerprint 未含標題 | Done | **Consistent.** Now encoded as trap 2 in `AGENTS.md` and `docs/TRAPS.md`. |
| Project description | — | **Stale.** It states `origin/main` is at `cf684cc` (PR #32). `main` is now `01dc1a0`, three commits and two merged PRs later (#33 OK-alias fix, #34 AGENTS.md). |
| 7 × Ready + Low (DEV-14, 17, 19, 20, 21, 22, 23) | Ready | Roadmap wishes, none started, none contradicted by code. No action. |

No duplicated issues found. No issue marked Done was found whose implementation is
missing.

---

## GitHub discrepancies

1. **No open issues and no open PRs.** The repository has never had a GitHub issue; all
   tracking lives in Linear. Worth knowing if anyone expects GitHub to be the source of truth.
2. **CI is fully green** — 15/15 most recent runs succeeded across both workflows. The
   green is honest for what CI runs, but CI does not run `tsc --noEmit` (BUG-006) and
   installs the package before testing, which hides BUG-007.
3. **Dead branch reference** in `refresh-data.yml` (BUG-004).
4. **Unpinned actions** in two of five workflows (BUG-011).
5. **Two stale unmerged remote branches:**
   - `chore/data-architecture-phase1` (`079b2df`) — 55 commits behind `main`
   - `design/direction-02-retail-shelf-system` (`d947776`) — 42 commits behind `main`

   Neither is an ancestor of `main`. Given the repo's history of a PII purge, leaving
   long-lived branches around is a small ongoing risk surface; confirm they carry no raw
   store data before deciding to keep them.
6. **Local-only branches** with no remote counterpart: `dev-113-implementation`,
   `feat/soft-serve-zone`, `chore/rule-file-agents-md`, `main`. The last one cannot be
   checked out in this clone because the cron worktree at `~/.cache/cvs-rebackfill-wt`
   holds it; that is by design, not a defect.
7. **No reverted commits** in the recent history, and no bug-fix commit was found that
   re-introduced an earlier problem.

---

## Missing test coverage

Ranked by value.

1. **A pipeline-level soft-serve separator test** (BUG-001). Every existing
   `soft-serve.test.ts` case feeds a name that already contains `x`, so the whole suite
   is blind to the bug that breaks the feature. The test has to start from a post title
   and end at the published name.
2. **A merge-path invariant test** (BUG-002). `tests/test_web_build_data.py` has two
   merge tests, both with high-evidence members. One low-evidence case asserting *both*
   `recommendationScore is None` and `positivePct is None` closes the gap.
3. ~~A CI job that runs the suite without installing the package (BUG-003).~~
   **Dropped** — BUG-003 is withdrawn, so this gate has no known failure to protect
   against. Still cheap insurance against a future pytest behaviour change, but it no
   longer belongs near the top of this list.
4. **`npx tsc --noEmit` as a CI step** (BUG-006). One step; catches an entire error class
   that `next build` and `vitest` both miss.
5. **A `--help` smoke test over all of `scripts/*.py`** (BUG-007), replacing the
   single-script version at `ci.yml:22-23`.
6. **A workflow-reference lint**: assert no `.github/` file names a branch that does not
   exist on the remote, and that every `uses:` is SHA-pinned (BUG-004, BUG-011).
7. **A Python↔TypeScript constant-parity test** for the brand list (BUG-005). The typo
   survived because two languages hold the same list independently.
8. **Grounding-adjudication integration coverage.** `scripts/verify_grounding.sh` and the
   `jev_labelers.py grounding` layer landed on 2026-09-19 and, per the operator's own
   record, the verification layer has **never executed in a production run** (there were
   no pending rows on the day it went live). `tests/test_jev_labelers.py` covers
   `label_rows` with a fake `ask`, which is the right shape, but the shell-level
   two-pass flow in `run_required_label_layers.sh` — collect queues, adjudicate,
   re-import — has no test at all. There are 18 rows sitting in
   `artifacts/pending-grounding-*.csv` in this checkout right now, 17 of them without a
   cached verdict, so the path is reachable. This is the least-exercised code in the repo.
9. **`web/components/ShelfExplorer.tsx` has no component test.** At 587 lines it is the
   largest frontend file and the only one without one (`ShelfCard`, `lib/data`,
   `lib/soft-serve` all have suites). The filter/sheet/expand state machine — including
   the deliberate "same element rendered in two parents = two live instances" pattern at
   `:263` — is untested.

---

## Suspected issues requiring manual verification

Kept separate because I could not confirm them from the repository alone.

**S-1 — Repeated paid re-adjudication of held rewrites.**
`artifacts/` is untracked (`git ls-files artifacts/` is empty) and the cron worktree is
hard-reset every run, so the pending queues are rebuilt from scratch each night. Verdicts
*are* cached in the committed `data/labels/grounding_verdicts.csv` (164 rows), so a
second look at the same rewrite is free. But if a rewrite is adjudicated `ungrounded`,
the importer rejects it, the labelling layer generates a *new* rewrite the next night,
and that new text has a new fingerprint — which is a fresh paid adjudication. Whether
this loops on the same products indefinitely can only be answered by watching
`grounding_verdicts.csv` growth against the rejected-row counts over a few runs.
**To verify:** log the per-run `pending`/`still` counts printed by
`run_required_label_layers.sh` for a week and check whether the same `product_name`
values keep reappearing.

**S-2 — `siteBuiltAt` frozen at 2026-08-25.**
`web/public/data.json` carries `siteBuiltAt: 2026-08-25T01:15:01.401105+00:00` while
`generatedAt` tracks today. This is **deliberate** — it is the anchor that makes CI's
`git diff --exit-code -- web/public/data.json` gate reproducible, and
`build_data.resolve_data_timestamps:50-53` carries an explicit comment saying so. I am
listing it only because it looks exactly like a stuck timestamp and will be "fixed" by
someone eventually. **Do not change it.** If a real build time is ever needed, it has to
come with a different reproducibility strategy for the CI gate.

**S-3 — Whether the OK-alias guard (PR #33) under-attributes genuine OK Mart comments.**
`cvs_radar/scoring/attribution.py:_has_store_context` now requires a store word
(`超商/超市/便利商店/便利店/門市/mart`) immediately adjacent to a bare ASCII `OK` before it
counts as the chain. The commit measured this carefully — 193 comments swept, all 193
were the adjective, 146 products moved by at most ±2.5 points — and the trade-off is
explicitly the safer direction. Two residual questions I could not settle statically:
the adjacency check is a strict `startswith`/`endswith` on the casefolded token, so
`OK 超商` with a space between them does not match; and the guard applies to the post's
*own* brand as well as rivals, so an OK Mart post whose comments say "OK的比較好" loses
those mentions too. **To verify:** sweep the store for bare-`OK` matches with a store
word one or two characters away rather than adjacent, and count how many sit under
OK-brand posts.

---

## Prioritized implementation queue

Ordered by severity, then user impact, then whether one fix unblocks another.

1. ~~**BUG-003**~~ — **withdrawn**, not a defect. The pre-push pytest gate works; the
   failure this entry was built on could not be reproduced. Nothing to implement.
2. **BUG-001** — soft-serve separator loss (DEV-193). *Highest user impact: it silently
   disables most of one of the product's two pages. Needs its own change with a label-cache
   migration and a full before/after pipeline diff — do not bundle it with anything.*
3. **BUG-002** — merged low-evidence products still show a score. *Small, self-contained,
   restores a documented invariant before it starts shipping wrong numbers.*
4. **BUG-004** — dead disaster-recovery seed branch. *Cheap, and it is the path someone
   will reach for on the worst day.*
5. **BUG-006** — fix the type error and add `tsc --noEmit` to CI. *Closes a whole error
   class for one CI step.*
6. **BUG-007** — `sys.path` bootstrap in the two scripts + a `--help` loop in CI.
   *Pairs naturally with BUG-006 — both are CI-gate edits.*
7. **BUG-011** — SHA-pin the remaining two workflows. *Mechanical; pair it with BUG-004
   since both edit `.github/`.*
8. **BUG-005** — the 美廉社 brand typo. *Low traffic, but it is a permanent
   misclassification and touches an id-forming field, so it wants its own change with an
   override-file check.*
9. **BUG-008** — timezone-aware `generated_at`. *Correct today by accident of the host's
   clock; fix before anything ever runs the pipeline off the Taipei machine.*
10. **BUG-013** — merged unique-commenter double count. *Decide `max()` (cheap) vs
    upstream union (correct) first; the decision is the work.*
11. **BUG-009** — README statistics. *Bundle with whichever change next rebuilds
    `data.json`.*
12. **BUG-010** — untrack `web/tsconfig.tsbuildinfo`. *One command; fold into any PR.*
13. **BUG-012** — de-duplicate the label-layer shells. *Last: it spends real money to
    verify and carries the highest regression risk of anything on this list, with no user-
    visible payoff. Do it only when no behaviour work is in flight.*
