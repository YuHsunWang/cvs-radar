# Data layout

This repository adopts four lifecycle layers. The layer describes a dataset's
role, not whether Git tracks it. `catalog/datasets.toml` is the authoritative
inventory; this document is the placement and compatibility policy.

## Lifecycle layers and physical homes

| Layer | Purpose | Physical paths |
|---|---|---|
| Raw | Source-aligned facts and ingestion state. Preserve source meaning and access controls. | `data/posts.jsonl`, `data/raw/` |
| Staging | Restartable exports, labeling batches, quarantine queues, and unreviewed annotations. Nothing here is a public contract. | `data/staging/`, `artifacts/`, `data/labels/to_label_v1.csv` |
| Curated | Reviewed or model-adjudicated decisions that make downstream rebuilds deterministic. | `data/labels/` except `data/labels/to_label_v1.csv` |
| Generated | Reproducible scoring, evaluation, and publication outputs. Never hand-merge these files. | `data/results.json`, `outputs/`, `web/public/data.json`, `web/out/data.json` |

The ignored raw and staging homes intentionally contain local data. Their
placeholder ignore files keep the directories available in a fresh checkout.
The four files in `artifacts/` remain at their established path because their
importers and adjudication scripts already treat that directory as a protected,
ignored staging interface.

No persisted SQLite/Postgres relation or GA4 export was present in the audit on
2026-08-31. If one is introduced, it is a new dataset and must follow the rule
below rather than being inferred as part of an existing entry.

## Downstream compatibility contracts

- Raw posts are append-oriented and keyed by `id`. Source fields keep their
  source meaning; a same-ID refresh may replace the stored snapshot, but a new
  producer must not renumber IDs, truncate history, or publish this identity-
  bearing store.
- Curated caches are immutable to downstream code at the declared key and
  prompt-version boundary. Preserve each CSV's existing encoding, line endings,
  header names, and fingerprint inputs. A changed prompt/input contract creates
  new cache misses; it must not reinterpret old rows in place.
- `data/results.json` is a de-identified, atomic snapshot keyed by
  `reports.product_key`. It is generated from raw posts plus curated labels and
  must be rebuilt, never text-merged or treated as primary source facts.
- `web/public/data.json` is the browser contract keyed by `products.id`; its
  `generatedAt`, `siteBuiltAt`, and `products` fields are stable to the web app.
  `web/out/data.json` is only the replaceable copy from the most recent local
  static build and may lag the browser contract until that build runs again.
- Staging data has no downstream stability guarantee. A pipeline may consume it
  only through an explicit validator/importer. A failed run must preserve enough
  staging state to diagnose or resume safely.
- `data/results.json` is intentionally an intermediate input to category export
  and public-data generation. That lineage is allowed only because both consumers
  are explicit in the catalog and the file remains classified as generated.

## Rule for every new data file

1. Put an unmodified external capture or ingestion checkpoint in `data/raw/`.
2. Put a retryable transform, export, queue, or scratch batch in `data/staging/`
   (or the established `artifacts/` validator interface).
3. Put a reviewed decision used to make builds deterministic in `data/labels/`.
4. Put a fully reproducible product, evaluation, or publication output in its
   owning generated path (`data/`, `outputs/`, or `web/`).
5. In the same commit, add a catalog entry, declare the real key (or an empty key
   plus `known_gap`), update all producers/consumers, and add retention/ignore
   handling. Do not create persisted datasets at the repository root.

## Migration log

| Date | Decision | Migration | Compatibility |
|---|---|---|---|
| 2026-08-31 | Adopt raw/staging/curated/generated lifecycle layers and the dataset catalog. | Catalogued every persisted dataset found; no dataset content changed. | Documentation and tests only. |
| 2026-08-31 | Remove stray local data from the repository root. | Crawl state and the legacy backfill snapshot moved into `data/raw/`; rebackfill chunks moved into `data/staging/rebackfill_work/`. | Crawler configuration and the rebackfill script were updated in the same commit. |
| 2026-08-31 | Freeze established runtime paths for phase 1. | Kept `data/posts.jsonl`, `data/results.json`, `data/labels/`, `artifacts/`, and `web/public/data.json` in place. | No crawler, scoring, or web behavior change. |
