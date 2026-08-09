# CLAUDE.md — rules and traps for agents working in this repo

Domain vocabulary lives in `CONTEXT.md`; scoring decisions in
`docs/DECISIONS.md`; the publishing pipeline in `docs/ops-pipeline.md`. This
file is only the things that will break something if you don't know them.

## What actually ships

The live product is the **Next.js app in `web/`**, deployed to Vercel with a
GitHub Pages mirror. It has two static routes over the same
`web/public/data.json`: `/` renders `components/ShelfExplorer.tsx`, and
`/soft-serve/` renders `components/SoftServeZone.tsx`. There is no server at
runtime and no API in production.

The Python side is a batch pipeline: `crawl_job.py` fetches PTT posts into the
local `data/posts.jsonl` store, `cvs_radar/pipeline.py` scores them into
`data/results.json`, and `web/build_data.py` projects that into
`web/public/data.json` for the frontend.

Live data is published by a **local cron**, not by CI — see
`scripts/ops/rebackfill-cron.sh` and `docs/ops-pipeline.md`. The
`refresh-data.yml` workflow is a manual-dispatch fallback only. If the site's
data looks stale, check the local machine, not GitHub Actions.

## Before you push

CI runs all of these. Run them locally first — pushing and watching CI go red
wastes a full cycle.

```bash
python -m pytest -q            # from the repo root
ruff check .
cd web && npm run build:data   # then: git diff --exit-code -- web/public/data.json
cd web && npm test
cd web && npm run build
```

Three of those are gates people forget:

- **A docs-only change is not exempt from `pytest`.** `tests/test_docs_runtime.py`
  reads `README.md`, `CVS-Radar-PRD-v0.2.md`, `docs/ops-pipeline.md` and
  `docs/crawl_plan.md` as text and asserts specific sentences are present — plus
  one overclaim (`公開快照每日自動更新`) that must stay absent, because the repo
  cannot prove the external scheduling host exists. Rewriting prose in any of
  those four files can turn CI red without a line of code changing. Reasoning
  "it's only the README, the gates don't apply" is how that happens.
- **`npm run build:data` + `git diff --exit-code -- web/public/data.json`.** CI
  rebuilds the public payload and fails if the committed one differs. Any change
  to `web/build_data.py`'s output fields *must* land together with a rebuilt
  `data.json` in the same commit.
- **`ruff check .`** with no `[lint] select` in `ruff.toml`, meaning Ruff's
  default rule set — whatever the installed version considers default. This is
  why `pyproject.toml` pins `ruff>=0.6,<0.16`: 0.16 widened the defaults and
  turned clean code into hundreds of errors overnight. Raising that ceiling
  requires writing an explicit `select` list first.

## Invariants (violating one is a bug, not a preference)

- **No account identities in published data.** This is enforced at the write
  boundary, not by a cleanup step: `cvs_radar.store.save_results` empties
  `contributors`/`profiles` and then `validate_publishable_results` raises if
  anything identity-bearing survives. Don't route around it by writing
  `data/results.json` some other way. (`scripts/strip_profiles.py` is a
  standalone leftover, referenced only by the fallback workflow.)
- **`data/posts.jsonl` never enters the repo.** It holds real PTT accounts and
  is gitignored. The repo's history was rewritten once to purge identity data;
  don't undo that.
- **Low-sample products don't show a recommendation score** or a percentage
  distribution. The gating is deliberate, not a rendering bug.

## Traps

**1. Changing product-name extraction silently breaks four other things.**
Extraction lives in `cvs_radar/scoring/` (`_common.py` regexes, `identity.py`
extraction, `excerpt.py` excerpt selection). The extracted name becomes the
`product_id` (`{brand}::{productName}`), and that id is the key for:

- `data/labels/product_overrides.csv` — manual category/price/excerpt/exclude
  fixes, applied at build time by `web/build_data.py`
- `data/labels/excerpt_labels.csv` — its fingerprint includes the product name
- `data/labels/comment_picks.csv` — same

Rows keyed to the old name don't error. They just stop matching, and the fix
they encoded silently disappears. After touching extraction, migrate the
affected keys and confirm zero orphaned override rows.

**2. Label-cache fingerprints must include everything the labeller saw.**
Every field exported to the LLM that could change its answer belongs in the
fingerprint. The product-name layer once keyed on `(brand, raw field)` while the
model was actually reading the *title*; posts whose raw field was junk (`：49`)
all hashed alike, so one label overwrote 28 posts and four different products
shared one score. The key is now `(brand, title, raw field)`.

**3. One post can cover several products.** `preprocess_posts` splits a post
into multiple items but each item keeps the **whole** `review_text`. Any rule
that picks a sentence from the body will attribute the neighbouring product's
comment to this one. The working fix is to export an `other_products` column so
the LLM can exclude them — both the excerpt and comment-pick layers depend on it.

**4. The label CSVs don't share an encoding.** There is no `.gitattributes`, so
whatever you write is what lands. As of 2026-08-03, all five label caches are
**CRLF**; `product_overrides.csv` has **no BOM** while `comment_picks.csv`,
`excerpt_labels.csv`, `product_name_labels.csv` and
`sentiment_fingerprint_labels.csv` are **BOM-prefixed**. Check the file you're
about to touch and write it back the same way — rewriting a whole CSV with
different settings produces a diff where every line changed and hides the one
line you meant to change. For small fixes, edit rows in place.

**5. The cron worktree resets hard to `origin/main` on every run.** Step 0 of
`scripts/ops/rebackfill.sh` runs `git reset --hard`, so any uncommitted label
file in that worktree is destroyed before the run starts. Every cache a run
writes has to be committed by that same run.

**6. Don't compare product sets across the wrong key.** `group_products` keys
are lowercased by `normalize_product`; `data.json` ids come from
`representative_product_name` (case preserved) and have already had overrides
applied. Comparing the two produces a flood of fake differences. Compare
`score_all` report names against report names.

**7. Ordering matters in the label pipeline.** Excerpt and comment-pick
fingerprints both contain the product name, so names must be settled before
those layers export their deltas. `scripts/ops/run_required_label_layers.sh`
encodes the order; don't reorder it casually.

**8. The soft-serve zone reads flavour count out of the product name.** There is
no flavour field anywhere in the pipeline, so `web/lib/soft-serve.ts` decides
single-vs-swirl by splitting the name on `x`/`X`/`×`. Consequences:

- A swirl whose name shipped **without** the separator (`起司蛋糕比利時巧克力霜
  淇淋`) reads as one flavour, and both of its comparisons quietly vanish — no
  error, just a card that never appears. `DUAL_FLAVOR_OVERRIDES` names those by
  hand, and the list only grows when someone notices.
- Trap 1 applies here too: product-name extraction feeds this split, so a change
  there silently adds or removes whole comparison cards.
- A swirl is filed under **both** of its flavours on purpose, so the same
  product renders on two cards, and its verdict can differ between them (a
  swirl can beat one half's solo score while tying the other's). The leftover
  list below is a set-difference over product ids; "deduplicating" the two
  appearances breaks that split.

The zone derives everything at render time from fields already in `data.json` —
no pipeline stage, no new data file, nothing to rebuild.

## Verifying a claim about behaviour

The pipeline is deterministic given the same posts and labels, so the honest way
to check "did my change alter results?" is to run the full pipeline before and
after on the same `data/posts.jsonl` and diff the report set. The one field that
always drifts is time-decay weighting, which reads `datetime.now()` — two runs
of identical code differ there too. Don't read that as a regression.
