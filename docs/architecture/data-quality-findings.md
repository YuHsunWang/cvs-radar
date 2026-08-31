# Data quality findings

Audit date: 2026-08-31. Findings are recommendations only; phase 1 deliberately
does not change crawling, scoring, merge semantics, or the web application.

## Critical

### DQ-01 — A valid but incomplete raw store can still publish a fresh partial snapshot

Evidence: the production script documents the prior 2,342-to-812 product
regression and now reconciles missing post IDs before crawling
(`scripts/ops/rebackfill.sh:66-109`). However, recompute accepts every non-empty
store and writes a new result snapshot without a historical row/product floor
(`scripts/ops/rebackfill.sh:306-312`). The freshness check validates age only,
not record completeness (`scripts/check_data_freshness.py:80-100`).

Failure scenario: a parse/configuration regression yields a syntactically valid
but much smaller store. The job creates a current timestamp, publishes the smaller
product set, and the freshness monitor reports healthy. Add pre-publish floors for
post count, product count, and newest/oldest source dates, with an explicit
override for intentional resets.

### DQ-02 — Seed reconciliation is ID-preserving but not revision-aware

Evidence: reconciliation appends only IDs absent from the worktree store
(`scripts/ops/rebackfill.sh:92-109`), then the worktree copy replaces the seed
after the labeling phase (`scripts/ops/rebackfill.sh:284-286`). The normal store
writer also skips an already-present ID (`cvs_radar/store.py:122-136`); comment
snapshot replacement occurs only in the bounded recent-refresh path
(`cvs_radar/backfill.py:107-158`).

Failure scenario: an out-of-band backfill has newer comments for an ID already
present in the cron worktree. Reconciliation sees no missing ID, keeps the older
worktree revision, and later overwrites the newer seed. Introduce a revision merge
policy (for example, explicit fetched-at metadata plus comment completeness), not
only set union by ID.

## High

### DQ-03 — Product overrides have conflicting duplicate lookup keys

Evidence: the audit found conflicting duplicates at rows 14/41 and 29/37 of
`data/labels/product_overrides.csv`. The loader assigns rows into a dictionary by
`product_id`, so the later row silently replaces the earlier one
(`web/build_data.py:76-94`). The catalog therefore records no stable primary key
instead of claiming `product_id` is unique.

Failure scenario: reordering rows, resolving a merge, or changing CSV tooling
changes which reviewed correction wins, producing a different category, price,
excerpt, or exclusion with no error. Add uniqueness validation and adjudicate the
two conflicts in a later data-correction change.

### DQ-04 — Schema drift is tolerated without a dataset schema version

Evidence: the raw audit found 2 top-level post schemas (267 of 2,733 rows lack
`raw`) and 2 comment schemas (4,689 of 46,710 comments lack `backend`). The reader
fills many fields with defaults and ignores unknown fields
(`cvs_radar/store.py:56-89`), while it rejects only rows that cannot deserialize
(`cvs_radar/store.py:167-185`). Several label readers return an empty cache when a
required header is missing (`cvs_radar/excerpt_labels.py:94-113` and
`cvs_radar/comment_labels.py:134-161`).

Failure scenario: a renamed optional field silently falls back to an empty/default
value, changing scoring or causing wholesale cache misses without identifying a
migration boundary. Add explicit schema versions and report accepted legacy
versions and dropped-row counts before enforcing migrations.

## Medium

### DQ-05 — Freshness and completeness cover the public artifact only partially

Evidence: `web/build_data.py` warns when the generated source is older than 14
days but still writes output (`web/build_data.py:37-56`), and the operational
checker reads only the public `generatedAt` timestamp
(`scripts/check_data_freshness.py:60-100`). There is no check for raw-store age,
expected crawl pages, label coverage, report count, or public/raw reconciliation.

Failure scenario: a daily job keeps rebuilding old or incomplete facts, so the
timestamp remains recent while source coverage degrades. Persist and validate
per-stage counts, maximum source time, and label-cache hit rates before publish.

### DQ-06 — Generated snapshots are intentionally reused as inputs

Evidence: category export defaults to the scored snapshot
(`scripts/export_product_categories.py:24-25`), and public generation loads the
same snapshot (`web/build_data.py:467-487`). An optional legacy excerpt override
loader also treats a CSV artifact as an input and silently returns an empty map
when it is absent (`cvs_radar/scoring/excerpt.py:35-47`).

The audit also found that the local static-export copy contains 2,342 products
while the browser contract contains 2,344 products; their `generatedAt` values
show that the copy predates the current contract (`web/out/data.json:2` and
`web/public/data.json:2`). This is allowed for ignored build output, but confirms
that it must not be selected as an authoritative input.

Failure scenario: running either consumer against a stale generated snapshot
creates category labels or a public payload that is internally valid but does not
represent the current raw/curated state. Require lineage metadata or a build-run
identifier across raw, result, category delta, and public output.

### DQ-07 — Merge keys are deterministic, but collision policy is often last-write-wins

Evidence: raw duplicate IDs retain the last valid row on load
(`cvs_radar/store.py:167-185`); the sentiment importer converts existing rows to a
fingerprint-keyed dictionary (`scripts/import_llm_backfill.py:26-37`); public
products group by ID before asserting final uniqueness (`web/build_data.py:157-166`
and `web/build_data.py:290-295`).

Failure scenario: two semantically different rows collide on a key and one answer
disappears before validation can compare them. Add collision reports that
distinguish identical duplicates from conflicting payloads at every merge boundary.

## Low

### DQ-08 — Several columns are provenance-only or currently unused at runtime

Evidence: comment-pick loading consumes fingerprint, prompt version, and rewrite
columns but not `brand`, `product_name`, or `model`
(`cvs_radar/comment_labels.py:134-161`). Product-category loading consumes only
fingerprint and category (`cvs_radar/product_categories.py:111-120`). The gold
reader requires five fields while the predictors additionally read only comment
text/tag/user and post brand (`cvs_radar/evaluation.py:47-73` and
`cvs_radar/evaluation.py:94-102`).

Failure scenario: contributors assume every stored column affects runtime output,
or delete audit context because it appears dead. Mark these fields as provenance
in a future schema specification; do not remove them until downstream notebooks
and manual workflows are inventoried.

## Coverage notes

The audit found no persisted database tables and no GA4 export. GA4 event emission
in the web client is an external analytics sink, not a repository dataset. The
catalog intentionally contains no invented entries for either category.
