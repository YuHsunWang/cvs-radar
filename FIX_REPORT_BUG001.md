# BUG-001 / DEV-193 Fix Report

## Summary

Soft-serve flavour separators are preserved through product-name extraction and
the affected label caches and derived payload have been migrated. The final
public payload contains 113 soft-serve products, 19 names with a literal
`x`/`X`/`×`, and 20 dual-flavour products under the frontend rule (the extra one
is the existing `DUAL_FLAVOR_OVERRIDES` entry).

## Root cause

Both product-name cleanup paths replaced every Han-`x`-Han sequence with a
space. That was correct for collaboration syntax but destroyed the only flavour
boundary available to `web/lib/soft-serve.ts`. The extractor now retains the
separator for soft-serve/ice-cream names while still removing explicit
collaboration separators (`cvs_radar/scoring/identity.py:27-29, 569-607`).

## Fix

- Preserve a canonical lowercase `x` for a Han-`x`-Han sequence in a name that
  contains `霜淇淋` or `冰淇淋`.
- Keep the historical removal for non-ice products and for `聯名x...` /
  `...x聯名` syntax.
- Re-key dependent cache fingerprints and migrate only values supported by
  their own source text.
- Pin `泰式奶茶x起司蛋糕霜淇淋` as a two-flavour product from the committed
  public payload (`web/lib/soft-serve.test.ts:48-55`).

## Migration

The existing re-runnable `scripts/migrate_soft_serve_separator.py` was used; no
second migration was created. Its first applied pass reported 26 candidate
fingerprints and re-keyed 18 product-name, 7 excerpt, 3 comment-pick, 2 category,
and 0 sentiment rows. One identical category collision was deduplicated. No
override ID matched a changed product ID. The override CSV was restored to its
required CRLF/no-BOM encoding after the earlier pass had added a BOM.

Value verdicts, grounded in `data/labels/product_name_labels.csv` CSV records
and guarded by `scripts/migrate_soft_serve_separator.py:59-79,117-165`:

| Stored name | Verdict | Source text |
|---|---|---|
| `芭樂芋頭牛奶霜淇淋` | restored to `芭樂x芋頭牛奶霜淇淋` | record 2054 title: `全家霜淇淋 芭樂x芋頭牛奶` |
| `泰式奶茶起司蛋糕霜淇淋` | restored to `泰式奶茶x起司蛋糕霜淇淋` | record 1493 title/raw name both contain `泰式奶茶x起司蛋糕霜淇淋` |
| `伊藤園抹茶咖啡綜合霜淇淋` | restored to `伊藤園抹茶x咖啡綜合霜淇淋` | records 2210/2326 contain `伊藤園抹茶+咖啡` / `伊藤園抹茶X咖啡綜合霜淇淋` |
| `青森蘋果藍莓霜淇淋` | restored to `青森蘋果x藍莓霜淇淋` | record 788 title contains `青森蘋果x藍莓霜淇淋` |
| `海鹽檸檬霜淇淋` | deliberately unchanged | record 2493 raw name lists two products: `海鹽檸檬霜淇淋、海鹽檸檬x草莓優格霜淇淋`; the separator belongs only to the second item |

LLM calls: **0**.

## Proof

### 1. No orphan regression

The same local `data/posts.jsonl` was evaluated with base (`8e4cbd6`) labels and
legacy extraction, then final labels and extraction. Counts are cache rows whose
fingerprint is absent from the pipeline-produced active set:

| Cache | Base | Final |
|---|---:|---:|
| product name | 1 | 0 |
| excerpt | 5 | 4 |
| comment picks | 1414 | 1414 |
| category | 46 | 46 |
| sentiment | 10860 | 10860 |

No final count exceeds base.

### 2. Intended product-set change

Both base and final contain 2368 products. There are five removed and five added
IDs. Four are direct separator restorations:

- `伊藤園抹茶咖啡綜合霜淇淋` → `伊藤園抹茶x咖啡綜合霜淇淋`
- `哈尼午茉綠香芋牛奶霜淇淋` → `哈尼午茉綠x香芋牛奶霜淇淋`
- `泰式奶茶起司蛋糕霜淇淋` → `泰式奶茶x起司蛋糕霜淇淋`
- `芭樂芋頭牛奶霜淇淋` → `芭樂x芋頭牛奶霜淇淋`

The fifth is a representative-name change within the same five-post group:
`草莓牛奶煉乳牛奶霜淇淋` → `不二家草莓牛奶霜淇淋`. Its five `postUrls`
are identical before and after. Restoring the member name
`草莓牛奶x煉乳牛奶霜淇淋` changed which existing member is selected as the
representative; it did not add or remove evidence.

Among 2363 common IDs, 61 have field differences. Fifty-six differ only in
time-weighted score/distribution/confidence fields; 30 have a fair or
recommendation score change, all within -1..+1. Five common IDs have legacy
rebuild-alignment changes in representative comments/provisional status (and
two also in eligible counts): `7-11::台灣啤酒18天生啤酒`,
`7-11::多力多滋咖啡`, `7-11::小美冰淇淋香草`, `全家::多力多滋香菜`, and
`全家::紅豆牛奶霜淇淋`. These five already differed in the branch's pre-final
payload (`c529eae`) and were not introduced by the final value-restoration
rebuild; the final rebuild added only three direct rename pairs and time-derived
common-field drift. Top-level `generatedAt` advanced; `siteBuiltAt` remained
exactly `2026-08-25T01:15:01.401105+00:00`.

### 3. Feature counts

| Metric | Base `8e4cbd6` | Final |
|---|---:|---:|
| soft-serve products | 113 | 113 |
| literal separator names | 15 | 19 |
| dual flavour under `soft-serve.ts` (includes one override) | 16 | 20 |
| flavour groups with at least two products | 18 | 21 |
| groups containing both a single and a swirl | 15 | 19 |

The brief's `113 / 15` base figure is correct for literal separators. Under the
actual frontend rule it is `113 / 16` because the existing override also counts
as dual flavour.

## Tests

- Python regression covers separator preservation and collaboration cleanup.
- Frontend regression reads `web/public/data.json` and asserts that the migrated
  Thai-tea/cheesecake name splits into two flavours.
- Focused pre-gate results: `2 passed, 167 deselected`; frontend file
  `1 passed`, `16 tests passed`.

## Verification

Final gate results are recorded after running on the report-bearing tree:

- `python -m pytest -q` — `360 passed, 2 warnings, 69 subtests passed in 264.39s (0:04:24)`
- `ruff check .` — `All checks passed!`
- `cd web && npm run build:data && cd .. && git diff --exit-code -- web/public/data.json` — `Wrote 2368 products to web/public/data.json`; diff command exited 0 with no output
- `cd web && npm test` — `Test Files 4 passed (4)`; `Tests 57 passed (57)`
- `cd web && npm run build` — compiled successfully, generated 8/8 static pages, exported 2/2, exit 0
- `cd web && npx tsc --noEmit` — exit 0 with no output

## DEV-193 re-scope

The ticket's claim that about 87% of soft-serve names are unjudgeable should be
replaced. Of 296 product-name label rows whose source/name concerns soft serve,
38 rows (34 distinct fingerprints) have a Han-`x`-Han separator in their own
title/raw source. The final published set has 113 soft-serve products: 19 have a
literal separator, 20 are dual under the frontend rule, and 93 are single
flavour under that rule. Most names are ordinary single-flavour products, not
unjudgeable missing separators.

Recommendation for Linear: keep DEV-193 open until this branch is reviewed and
merged, then close it as fixed with the `38 rows / 34 fingerprints` source scope
and `113 total / 20 dual / 93 single` published scope. Do not preserve the 87%
claim.

## Residual risk

- The extractor uses the presence of `霜淇淋`/`冰淇淋` plus Han characters
  around `x`; unusual collaboration wording without an adjacent `聯名` marker
  can still be ambiguous.
- `青森蘋果x藍莓霜淇淋` is correctly migrated in the cache but is not in the
  current 2368-product public payload.
- The five pre-existing rebuild-alignment differences above should be audited
  separately if exact historical representative-comment reproducibility is a
  requirement; they do not change the product set or the separator feature.

## Proposed PR description

Fix soft-serve flavour separators lost during product-name cleanup. Preserve
Han-`x`-Han for ice-cream names while retaining collaboration cleanup, migrate
and re-key dependent caches without LLM calls, rebuild results/public data, and
add extraction plus published-payload regressions. The public payload stays at
113 soft-serve products and increases from 15 to 19 literal separator names
(16 to 20 dual products under the full frontend rule). All source-specific
verdicts, orphan comparisons, product-set diffs, and repository gates are
documented in this report.
