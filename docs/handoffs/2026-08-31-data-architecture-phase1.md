# Data architecture phase 1 handoff — 2026-08-31

## Delivered

- Adopted the lifecycle and placement policy in
  `docs/architecture/data-layout.md`.
- Added `catalog/datasets.toml` with all 28 logical persisted datasets found in
  raw crawl data, label caches, evaluation fixtures/outputs, validation queues,
  rebackfill batches, scored snapshots, and public/static payloads.
- Recorded evidence-backed risks in
  `docs/architecture/data-quality-findings.md`.
- Moved local crawl state and the legacy backfill snapshot into `data/raw/`, and
  moved rebackfill working chunks into `data/staging/rebackfill_work/`. These
  remain ignored and were not added to Git.
- Added `tests/test_dataset_catalog.py` to enforce catalog shape and path rules.

## Rules for future contributors

1. Do not persist a data file at the repository root. Classify it as raw,
   staging, curated, or generated before choosing its path.
2. Add or update its catalog entry in the same commit as the producer/consumer.
3. Declare only a key that is actually unique. Use `primary_key = []` and a
   `known_gap` when uniqueness is not true today.
4. Raw facts are not silently truncated; curated decisions retain fingerprints,
   prompt versions, encodings, and line endings; generated snapshots are rebuilt,
   never hand-merged.
5. Ignored raw/staging files may contain identities or review text. Never force-add
   them to Git, fixtures, logs, or public artifacts.
6. A new database table or analytics export is a persisted dataset and needs its
   own catalog entry, retention rule, owner, and migration decision.

## Deliberately not done

- No crawler, scoring, web-app, merge, schema, or CI/deploy configuration changed;
  the required catalog test adds only data-contract checks to the existing suite.
- The two conflicting duplicate `product_id` pairs were documented, not edited.
- No schema-version framework, completeness gate, revision-aware seed merge, or
  lineage/run ID was implemented.
- No label/cache columns were deleted; runtime-unused provenance may still support
  manual review or external analysis.
- The legacy backfill snapshot and second rebackfill batch were retained because
  their current producer and decommission authority are unknown.
