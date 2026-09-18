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
- **Category comes from the label cache, not from `config.yaml`.**
  `data/labels/product_category_labels.csv` decides; the `PRODUCT_CATEGORIES`
  keywords are a frozen fallback for unlabelled products only. Adding a keyword
  to fix a miscategorised product does nothing — every published product already
  has a label, and the label wins. Fix it with a label (or, for a one-off,
  `product_overrides.csv`, which outranks both).
- **Low-sample products don't show a recommendation score** or a percentage
  distribution. The gating is deliberate, not a rendering bug.

## Traps

Each entry is a failure that has actually happened. Full write-ups in
`docs/TRAPS.md` — read the numbered entry there before touching the area.

| # | Touching this? | Read it first |
|---|---|---|
| 1 | product-name extraction (`cvs_radar/scoring/`) | the id is the label-cache key; old rows stop matching silently |
| 2 | a label-cache fingerprint | it must include every field the LLM saw, or labels collide |
| 3 | anything that picks a sentence from `review_text` | one post covers several products; use `other_products` |
| 4 | a CSV under `data/labels/` | encodings differ per file; check bytes, and `wc -l` overcounts |
| 5 | the cron worktree | step 0 of `rebackfill.sh` hard-resets; commit within the run |
| 6 | comparing product sets | `group_products` keys are lowercased, `data.json` ids are not |
| 7 | label-layer order | `run_required_label_layers.sh` encodes it; category sits outside on purpose |
| 8 | importer tests | override `rejects_path`/`pending_path` or fixtures pollute real `artifacts/` |
| 9 | `MIN_MEANINGFUL_OVERLAP` | character overlap cannot judge a Chinese paraphrase; it is a screen, not a verdict |
| 10 | a labelling prompt | rules are global; small batch first, watch total item count |
| 11 | the sentiment prompt | it is a heredoc in `scripts/ops/rebackfill.sh`, not in `scripts/prompts/` |
| 12 | merging a branch older than a day | union the 5 label CSVs, regenerate the 2 JSONs, never hand-merge |
| 13 | `web/lib/soft-serve.ts` | flavour count is parsed out of the product name; trap 1 feeds it |

## Verifying a claim about behaviour

The pipeline is deterministic given the same posts and labels, so the honest way
to check "did my change alter results?" is to run the full pipeline before and
after on the same `data/posts.jsonl` and diff the report set. The one field that
always drifts is time-decay weighting, which reads `datetime.now()` — two runs
of identical code differ there too. Don't read that as a regression.
