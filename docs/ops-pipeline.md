# Ops: data-refresh pipeline, scheduling & freshness (review #9)

This documents how the live CVS Radar data is refreshed, scheduled, and
monitored, so the process is reproducible from the repo rather than only from
the author's machine. For raw-store loss recovery see
[`runbook-data-recovery.md`](./runbook-data-recovery.md).

## Architecture (current)

Since 2026-07-21 the publisher is a **local cron pipeline**, not GitHub Actions.
`.github/workflows/refresh-data.yml` is kept only as a **manual** fallback
(`workflow_dispatch`) for when the local machine is unavailable.

The pipeline scripts are versioned in this repo:

| Script | Role |
|---|---|
| [`scripts/ops/rebackfill.sh`](../scripts/ops/rebackfill.sh) | the full refresh: crawl → backfill review text → sentiment labeling → product-name labeling → excerpt labeling → representative-comment labeling → atomically save de-identified results → category labeling → `build_data` → commit (+push) |
| [`scripts/ops/rebackfill-cron.sh`](../scripts/ops/rebackfill-cron.sh) | scheduled wrapper: full PATH, records last-success, runs the freshness check |
| [`scripts/check_data_freshness.py`](../scripts/check_data_freshness.py) | freshness SLO check on the **published** `web/public/data.json` |

The **Codex labeling steps require a local Codex CLI subscription** and are
not reproducible in CI. Each layer must export, validate and import successfully;
any failure exits before recompute, commit or push, leaving the raw store for retry.
Every other step is standard Python + git.

### Category labeling runs after the recompute (since 2026-08-18)

`scripts/label_product_categories.sh` is the fifth Codex-labelled layer
(`data/labels/product_category_labels.csv`). It is **not** part of
`run_required_label_layers.sh`, because its fingerprint is keyed to the product
name the pipeline settled on — that name only exists once the recompute has
written `data/results.json`. So it runs between the recompute and `build_data`:

```
recompute -> results.json -> label_product_categories.sh -> build_data -> data.json
```

`web/build_data.py` resolves every product's category through the cache when it
projects the public payload, so labels imported at that point reach the snapshot
without a second recompute. Products with no label keep the `config.yaml`
keyword result, which is what makes a CI rebuild deterministic; a manual
`category` in `data/labels/product_overrides.csv` is applied afterwards and
still outranks both.

### Labeling runs in two passes (since 2026-08-13)

`run_required_label_layers.sh` runs all three layers, then — if anything was held
— adjudicates and runs them again:

```
product names -> excerpts -> representative comments      (pass 1)
        |  any rewrite the overlap screen could not clear
        v
   verify_grounding.sh    (a model judges rewrite vs cited source)
        |  verdicts cached in data/labels/grounding_verdicts.csv
        v
product names -> excerpts -> representative comments      (pass 2)
```

The importers have **three** outcomes per row, not two:

| Outcome | When | Where it goes |
|---|---|---|
| accepted | passes every check | the label cache |
| quarantined | definitely wrong: cross-product rewrite, bad source index, model-confirmed hallucination | `artifacts/rejected-*.csv`; above a 2% failure rate the whole file is refused instead |
| **held** | only the character-overlap screen failed | `artifacts/pending-grounding-*.csv`, awaiting a verdict |

Nothing is ever repaired. A quarantined or held row simply stays out of the cache,
so the next export sees it as unlabelled again and re-labels it.

`artifacts/` and the `*_work/` scratch directories are gitignored: quarantine and
adjudication files carry raw comment/review text, same rule as `data/posts.jsonl`.

**Known behaviour:** a row whose rewrite is cached as `ungrounded` is re-labelled
on every full run, very likely produces the same rewrite, and is rejected again by
the cached verdict. It churns rather than converging. Bounded and harmless at the
current scale (6 rows as of 2026-08-13); fixing it needs a per-row attempt counter.

### Semantic cache keys

Each current SHA-256 key includes its prompt version and every value shown to the
labeler:

| Layer | Fingerprinted input |
|---|---|
| sentiment | source URL/ID, tag, comment text, brand, raw product name, post title, prompt version |
| product name | brand, title, raw product-name field, rule guess, prompt version |
| excerpt | post ID, product name, review text, brand, sibling products, candidate sentences, prompt version |
| representative comments | brand, product name, ordered comment/body candidates, sibling products, prompt version |
| category | brand, final product name, keyword rule guess, prompt version |
| grounding verdict | rewrite text, cited source text, prompt version |

The manual `.github/workflows/refresh-data.yml` fallback runs none of these five
labelers. It can rebuild only from already committed labels; new rows use rule
fallbacks, so it is an availability/recovery path, not equivalent to the local
publisher and must not be treated as a semantically complete refresh.

### Where the prompts live

Four of the five prompts are files under `scripts/prompts/`
(`product-name-labeling.md`, `excerpt-labeling.md`, `comment-picks-labeling.md`,
`product-category-labeling.md`, plus `grounding-verification.md`). **The sentiment
prompt is not one of them** — it is an inline heredoc in
[`scripts/ops/rebackfill.sh`](../scripts/ops/rebackfill.sh) (`prompt_template.md`,
around line 126). Looking only in `scripts/prompts/` and concluding the sentiment
prompt was never versioned is a mistake that has been made; grep the `scripts/ops/*.sh`
heredocs too before reconstructing one from scratch. A reconstructed prompt scores
the same comments differently, which silently splits the cache into two conventions.

### Key environment overrides

`REPO` `BRANCH` `WT` `STORE_SEED` `PAGES` `REFRESH_DAYS` `CHUNK` `CONC`
`DO_COMMIT` `PUSH` `RUNNER` (rebackfill.sh); `CVS_CRON_PATH` `LAST_SUCCESS_FILE`
`CVS_DATA_STALE_DAYS` `CVS_FRESHNESS_WEBHOOK` (cron wrapper / freshness check).
Defaults target the author's WSL setup; override them on any other host.

## Scheduling

Scheduling is external to this repository. To enable it, point cron at the
**repo copy** so the repo is the single source of truth
(avoids drift with any older copy under `~/.claude/tools/`):

```cron
30 8 * * *  /bin/bash /home/user/github-work/YuHsunWang/cvs-radar-clean/scripts/ops/rebackfill-cron.sh >> ~/.claude/logs/cvs-rebackfill.cron.log 2>&1
```

`PUSH=1` (the wrapper's default) publishes to `origin/main`; set `PUSH=0` for a
dry run that commits only in the worktree.

## Freshness SLO & monitoring

- **SLO:** published data must be at most `DATA_STALE_DAYS` = **14** days old
  (mirrored in `web/build_data.py`; override with `CVS_DATA_STALE_DAYS`).
- **Check:** `python3 scripts/check_data_freshness.py` reads `data.json`'s
  `generatedAt` (the data-snapshot time, not the build time) and exits
  `0` fresh / `1` stale / `2` unknown. The non-zero exit is the alert signal;
  set `CVS_FRESHNESS_WEBHOOK` to also POST a JSON alert when stale.
- **Last success:** the cron wrapper writes `LAST_SUCCESS_FILE`
  (default `~/.claude/logs/cvs-rebackfill.last-success`); the wrapper also runs
  the freshness check after every successful run.
- **Existing local alerts** (WSL cron, outside the repo): `cvs-ci-healthcheck.py`
  and `cvs-rebackfill-healthcheck.py` post to Discord on prolonged failure.

Run the freshness check anywhere (CI, a monitor, manually) to detect a silently
stale site independently of the pipeline host.

## Backup

`data/posts.jsonl` (raw store, contains real PTT accounts — **never committed**,
the repo is public) is snapshotted weekly to `D:\Claude\backups\cvs-radar\`
(8 retained). Encrypted/durable off-host backup is tracked as review #9 part C
and not yet implemented.
