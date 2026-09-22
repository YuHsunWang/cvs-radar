# Fix Report

## Summary

- Confirmed: 10 (`BUG-001`, `BUG-002`, `BUG-004`, `BUG-006`, `BUG-008`–`BUG-013`).
- Fixed: 10 (`BUG-002`, `BUG-004`–`BUG-011`, `BUG-013`); this includes the two partially correct findings.
- Rejected findings: 1 (`BUG-003`, Incorrect).
- Remaining: 2 (`BUG-001`, migration proof unavailable; `BUG-012`, paid-service verification forbidden in this round).
- Partially correct: 2 (`BUG-005`, `BUG-007`).

## Implemented

### BUG-002 — merged low-evidence recommendation score

- **Status:** Confirmed; fixed.
- **Files changed:** `web/build_data.py:248-260,365-386`; `tests/test_web_build_data.py:505-534`.
- **Root cause:** The merge path calculated `recommendationScore` before calculating the evidence gate, while the single-report path filtered low-confidence and insufficient-data reports.
- **Fix:** Added one `_has_publishable_score` predicate and used it for merged scores, single-report calibration, and distributions. A low-evidence merged product now retains its internal `fairScore` but publishes neither a recommendation score nor percentages.
- **Tests added:** `test_merged_low_evidence_product_shows_no_recommendation_score`. Verified red before the fix (`recommendationScore` was `67`) and green after it.
- **Tests executed:** Targeted test: `1 passed in 0.15s`; final suite is recorded under Verification.
- **Linear:** No issue named in `AUDIT.md`. Proposed issue — **“Merged low-evidence products expose recommendation scores”**. Problem/reproduction: merge two same-id members whose combined `n_eff < 3`; expected: no score or distribution; root cause: duplicated projection logic; implementation: shared publishability predicate; coverage: the new low-evidence merge regression.
- **GitHub:** No issue or PR was created; the audit records zero repository issues and zero open PRs.

### BUG-004 — dead refresh fallback branch

- **Status:** Confirmed; fixed.
- **Files changed:** `.github/workflows/refresh-data.yml:51-61`; `.github/workflows/export-llm-backfill.yml:35-47`; `tests/test_docs_runtime.py:62-74`.
- **Root cause:** The privacy purge removed `ui/mobile-redesign`, but the manual recovery workflow still failed soft and continued from an empty store. The adjacent export workflow also pointed operators back to `refresh-data.yml`, which can no longer recover a cache miss.
- **Fix:** Both workflows now fail loudly on an empty cache and direct the operator to `seed-cache.yml` plus `docs/runbook-data-recovery.md`.
- **Tests added:** `test_manual_refresh_never_seeds_private_posts_from_a_git_branch`. Verified red before each workflow correction and green afterward.
- **Tests executed:** `git ls-remote --heads origin` returned only `chore/data-architecture-phase1`, `design/direction-02-retail-shelf-system`, and `main`; targeted test: `1 passed in 0.20s`.
- **Linear:** `DEV-109` is Done. Recommendation: leave it Done because its privacy-purge scope is complete; link this follow-up fix rather than reopening it.
- **GitHub:** No issue or PR was created.

### BUG-005 — 美廉社 taxonomy

- **Status:** Partially correct; fixed. The taxonomy defect was real, but the claimed current-corpus impact was not: programmatic inspection found 4/2 mentions of `美廉社`/`美聯社` across all fields and zero in authoritative `vendor`/`title` fields, so no current product was shown to be misattributed.
- **Files changed:** `config.yaml:26-28`; `cvs_radar/config.py:13-19`; `web/lib/data.ts:49`; `web/components/ShelfExplorer.tsx:37-44,319-341`; `web/components/ShelfCard.tsx:13-19`; current identity/design docs; Python and web tests.
- **Root cause:** The Associated Press spelling `美聯社` was used as the canonical store name and copied into the UI. The correct spelling was only present in one rail-colour map.
- **Fix:** Made `美廉社` canonical end-to-end, retained `美聯社` only as an input alias, removed the hidden-brand workaround, and aligned current docs. `product_overrides.csv` contains zero rows for either spelling.
- **Tests added:** Parser inference and `displayBrand` regressions. Both were verified red before the fix (`其他`) and green afterward (`美廉社`).
- **Tests executed:** Python target `1 passed in 0.21s`; web target `31 passed`; `npx tsc --noEmit` exited 0.
- **Linear:** No issue named in `AUDIT.md`. Proposed issue — **“Canonicalize the 美廉社 brand across parser and UI”**. Problem/reproduction: `infer_brand('', '[商品] 美廉社 …')` and `displayBrand('美廉社')` returned `其他`; expected: `美廉社`; root cause: copied canonical typo; implementation: canonical key plus backward-compatible typo alias and UI cleanup; coverage: parser and TypeScript regressions.
- **GitHub:** No issue or PR was created.

### BUG-006 — TypeScript gate

- **Status:** Confirmed; fixed.
- **Files changed:** `web/lib/soft-serve.test.ts:12-40`; `.github/workflows/ci.yml:58-65`; `AGENTS.md:29-39`.
- **Root cause:** One `Product` fixture missed required `reviewProvisional`; Vitest does not type-check and Next did not include this test file in its build graph.
- **Fix:** Completed the fixture and added `npx tsc --noEmit` to CI and the pre-push list.
- **Tests added:** The CI type-check step is the regression gate. No unit test was appropriate.
- **Tests executed:** Verified pre-fix `TS2322`; post-fix `npx tsc --noEmit` exited 0 with no output.
- **Linear:** No issue named in `AUDIT.md`. Proposed issue — **“Type-check all web sources and tests in CI”**. Problem/reproduction: run `cd web && npx tsc --noEmit`; expected: exit 0; root cause: incomplete fixture plus absent gate; implementation: fixture field and CI/pre-push type-check; coverage: project-wide compiler gate.
- **GitHub:** Historical cause is PR #24 per `AUDIT.md`; no issue or PR was created.

### BUG-007 — standalone script imports

- **Status:** Partially correct; fixed. Both scripts failed exactly as reported, but the claimed shared root cause with BUG-003 was wrong: direct script execution puts `scripts/`, not the repository root, at `sys.path[0]`; `python -m pytest` did not have that problem.
- **Files changed:** `scripts/crawl_family_food.py:4-14`; `scripts/strip_profiles.py:6-18`; `.github/workflows/ci.yml:29-34`.
- **Root cause:** These were the only two Python script entry points importing `cvs_radar` without the repository-root bootstrap used by the other scripts.
- **Fix:** Added the established bootstrap to both. CI now uninstalls the built package after dependency installation and runs `--help` on every `scripts/*.py`, ensuring source-tree importability is actually tested.
- **Tests added:** The all-script CI smoke loop. Pre-fix both named scripts exited 1 with `ModuleNotFoundError`; post-fix all 23 Python scripts accepted `--help`.
- **Tests executed:** `PASS: 23 standalone Python scripts accepted --help`.
- **Linear:** No issue named in `AUDIT.md`. Proposed issue — **“Keep standalone Python script entry points importable without package installation”**. Problem/reproduction: run either named script with `--help`; expected: help/exit 0; root cause: missing root bootstrap; implementation: bootstrap and uninstalled-package CI loop; coverage: all 23 scripts.
- **GitHub:** No issue or PR was created.

### BUG-008 — timezone-aware snapshot timestamp

- **Status:** Confirmed; fixed.
- **Files changed:** `cvs_radar/store.py:8-15,350-354`; `web/build_data.py:40-64`; `tests/test_store.py:22-40`; `tests/test_web_build_data.py:55-70`.
- **Root cause:** The producer serialized host-local naive time while the consumer rigidly parsed one legacy format and retagged it as Taipei.
- **Fix:** The producer writes an aware Taipei ISO timestamp. The reader uses `fromisoformat`, preserves explicit offsets, and treats old naive snapshots as Taipei for backward compatibility. The frozen `siteBuiltAt` remained `2026-08-25T01:15:01.401105+00:00`.
- **Tests added:** A real-time UTC-instant assertion around `save_results` and an explicit-offset preservation test. Both were verified red before the fix and green after it.
- **Tests executed:** Timestamp targets: `3 passed in 0.18s` (including legacy-format compatibility).
- **Linear:** No issue named in `AUDIT.md`. Proposed issue — **“Serialize result snapshot timestamps with an explicit timezone”**. Problem/reproduction: parse `generated_at` from `save_results`; expected: aware instant independent of host TZ; root cause: naive producer/retagging consumer; implementation: aware Taipei producer and backward-compatible ISO reader; coverage: producer instant, aware input, legacy naive input.
- **GitHub:** No issue or PR was created.

### BUG-009 — drifting README snapshot statistics

- **Status:** Confirmed; fixed.
- **Files changed:** `README.md:118`; `tests/test_docs_runtime.py:30-42`.
- **Root cause:** Exact daily-snapshot counts were embedded in durable explanatory prose.
- **Fix:** Replaced the stale `2,342 / 567 / 24.2%` claim with the stable, accurate “about one quarter” statement already used elsewhere in the README.
- **Tests added:** The docs runtime test now requires the stable wording in the `n_eff` explanation. Verified red before the prose fix and green afterward.
- **Tests executed:** Recomputed current snapshot: `products=2368 no_score=538 share=22.7%`; targeted docs test: `1 passed in 0.18s`.
- **Linear:** No issue named in `AUDIT.md`. Proposed issue — **“Remove daily-snapshot counts from the README evidence-gating explanation”**. Problem/reproduction: compare README counts with `web/public/data.json`; expected: non-drifting truthful explanation; root cause: exact volatile counts; implementation: stable approximate wording; coverage: docs runtime assertion.
- **GitHub:** No issue or PR was created.

### BUG-010 — tracked TypeScript build artifact

- **Status:** Confirmed; fixed.
- **Files changed:** `web/.gitignore:1-6`; deleted tracked `web/tsconfig.tsbuildinfo` from the index.
- **Root cause:** Incremental TypeScript output had no ignore rule and was committed.
- **Fix:** Ignored `tsconfig.tsbuildinfo` and removed it from version control while preserving the user's local modified artifact on disk.
- **Tests added:** None; a unit test is not warranted for repository tracking state.
- **Tests executed:** Before: `git ls-files -- web/tsconfig.tsbuildinfo` printed the path. After commit, the same command must print nothing; final repository checks are under Verification.
- **Linear:** No issue named in `AUDIT.md`. Proposed issue — **“Stop tracking TypeScript incremental build output”**. Problem/reproduction: type-check then inspect `git status`; expected: no artifact churn; root cause: missing ignore rule plus tracked cache; implementation: ignore and untrack; coverage: repository-state verification.
- **GitHub:** No issue or PR was created.

### BUG-011 — floating GitHub Action tags

- **Status:** Confirmed; fixed.
- **Files changed:** `.github/workflows/export-llm-backfill.yml:18-59`; `.github/workflows/seed-cache.yml:57-63`; `tests/test_docs_runtime.py:77-82`.
- **Root cause:** The earlier supply-chain pinning pass did not cover two manual/data workflows.
- **Fix:** Resolved the official action tags with `git ls-remote` and pinned checkout `11d596…`, setup-python `a26af69…`, cache `005785…`, and upload-artifact `ea165f…`, retaining major-version comments.
- **Tests added:** A repository-wide assertion that every `uses: actions/...` reference is a 40-character lowercase SHA. Verified red on `@v4` and green after pinning.
- **Tests executed:** Targeted test: `1 passed in 0.21s`.
- **Linear:** No issue named in `AUDIT.md`. Proposed issue — **“Enforce immutable SHA pins for every GitHub Action”**. Problem/reproduction: scan workflow `uses:` lines; expected: full SHA; root cause: partial rollout; implementation: pin remaining tags and add lint assertion; coverage: all workflow YAML files.
- **GitHub:** No issue or PR was created.

### BUG-013 — merged distinct-count inflation

- **Status:** Confirmed; fixed with the conservative option explicitly offered by the audit.
- **Files changed:** `web/build_data.py:201-218`; `tests/test_web_build_data.py:465-477`.
- **Root cause:** The projection treated additive event counts and set cardinalities identically after identities had already been removed.
- **Fix:** Continue summing posts/raw/eligible event counts, but use `max()` as a privacy-preserving lower bound for `nComments`, `uniqueEligibleCommenters`, and `independentThreads`. This can undercount disjoint sets but cannot falsely claim overlap is distinct; exact union remains impossible at this boundary.
- **Tests added:** Tightened the existing override-collision merge regression to assert conservative cardinalities. Verified red on the sum implementation (`8` vs expected `6`) and green after the fix.
- **Tests executed:** Targeted merge test: `1 passed in 0.19s`. Rebuilding the current snapshot produced no `web/public/data.json` drift.
- **Linear:** No issue named in `AUDIT.md`. Proposed issue — **“Do not sum distinct-person/thread counts during public product merges”**. Problem/reproduction: merge same-id members with overlapping populations; expected: no overstatement; root cause: generic sum loop after privacy stripping; implementation: conservative maxima; coverage: override-collision regression. A future exact-union design would require moving canonical merging upstream without publishing identities.
- **GitHub:** No issue or PR was created.

## Rejected / Not Reproducible

### BUG-003 — local `python -m pytest` collection failure

- **Status:** Incorrect on the audited commit and stated environment; no change made to `pyproject.toml`.
- **Reason:** The documented command uses `python -m pytest`, for which Python placed the current directory on `sys.path`. Pytest 9.1.1 successfully imported the source tree even though the distribution was not installed. Adding `pythonpath = ["."]` would encode a workaround for a failure that does not occur and could hide invocation/environment differences.
- **Evidence:** `python -m pip show cvs-radar` exited 1 (`Package(s) not found`); `sys.path[0] == ''`; `cvs_radar.__file__` resolved inside this checkout; the unmodified baseline command completed `353 passed, 2 warnings, 69 subtests passed in 219.59s`; post-change collection found 358 tests and exited 0. The audit's `ModuleNotFoundError` could not be reproduced.

## Remaining issues

### BUG-001 — soft-serve separator loss (DEV-193)

- **Status:** Confirmed; deliberately not implemented. Completeness-contract path **(b)** was selected.
- **Evidence:** `cvs_radar/scoring/identity.py:373` and `:572` delete a CJK-flanked `x/X/×`; `extract_products_and_prices_by_rules('起司蛋糕x莊園牛奶霜淇淋 45元', '全家')` returned `('起司蛋糕莊園牛奶霜淇淋', 45)`. The committed payload contains 113 soft-serve products and only 15 names with a separator (not the audit's stale count of 16). There are 45 distinct product-name fingerprints whose raw name has CJK-`x`-CJK.
- **Blocking proof:** No deterministic source currently distinguishes those 45 flavour separators from marketing/cross-product `x` uses. Changing either regex changes the rule guess embedded in the v2 fingerprint (`identity.py:76-87`), so a code-only fix can orphan paid labels even when a legacy key happens to mask some rows. This round has neither an approved deterministic classification of those rows nor a migrated-cache before/after pipeline proof.
- **File-level implementation plan:**
  1. Add an audited deterministic mapping/classifier for the 45 affected raw-field fingerprints, separating soft-serve flavours from marketing `x`.
  2. Normalize approved flavour separators to canonical `×` in both `identity.py:373` and `:572`, and preserve `×` in the final allowed-character cleanup at `:584`.
  3. Add `scripts/migrate_soft_serve_separator_labels.py`. It must preserve each CSV's BOM/CRLF convention; recompute old/new rule guesses and v2 fingerprints; replace complete item sets per fingerprint in `product_name_labels.csv`; re-key matching `excerpt_labels.csv`, `comment_picks.csv`, `product_category_labels.csv`, and any `product_overrides.csv` IDs; never hand-edit caches.
  4. Programmatically replay all posts and prove zero orphaned product-name, excerpt, comment-pick, category, and override rows before and after migration.
  5. Run the full pipeline twice on the same `data/posts.jsonl`, compare case-correct report-name sets, whitelist only audited separator renames, and separately ignore only documented time-decay drift. Rebuild the public payload and prove `siteBuiltAt` is unchanged.
  6. Only then add the pipeline-level extraction regression and exact `splitFlavors` published-name regression requested by the audit.
- **Linear:** `DEV-193` is Ready/High according to `AUDIT.md`. Recommendation: keep it Ready until the deterministic mapping and zero-orphan migration proof exist; then move to In Progress for the dedicated migration PR.
- **GitHub:** Historical feature PR #16 is named in `AUDIT.md`; no issue or PR was created.

### BUG-012 — duplicated paid-label shell drivers

- **Status:** Confirmed; not implemented by explicit scope prohibition.
- **Evidence:** Both scripts are 136 lines; the audit's normalization command produced 24 changed lines (12 hunks). This is maintainability risk, not a currently reproduced output defect.
- **Blocker:** Acceptance requires before/after cache equivalence, but meaningful verification invokes paid live LLM layers. This round explicitly forbids those calls. A shell refactor without that proof would violate the task's safety boundary.
- **Next action:** In a separately authorized paid-service window, extract the shared driver while retaining each layer's chunk size/columns, run both old and new drivers against the same fixture delta, and compare imported caches byte-for-byte before replacing the wrappers.
- **Linear:** No issue named in `AUDIT.md`. Proposed issue — **“Deduplicate excerpt and representative-comment labeling drivers”**. Problem/reproduction: normalize layer names and observe 24 changed duplicate lines across equal 136-line scripts; expected: one shared control flow; root cause: copy-based layer growth; implementation: parameterized driver plus thin wrappers; coverage: byte-identical old/new cache imports under an authorized live verification run.
- **GitHub:** No issue or PR was created.

## Verification

Final-tree results (all commands run from the stated directory):

- `python -m pytest -q` (repository root) — `358 passed, 2 warnings, 69 subtests passed in 228.74s (0:03:48)`.
- `ruff check .` — `All checks passed!`
- `cd web && npm run build:data && cd .. && git diff --exit-code -- web/public/data.json` — `Wrote 2368 products to web/public/data.json`; diff exited 0 with no output.
- `cd web && npm test` — `Test Files 4 passed (4)`; `Tests 56 passed (56)`.
- `cd web && npm run build` — exit 0; `Compiled successfully`, `Generating static pages (8/8)`, and `Exporting (2/2)`.
- `cd web && npx tsc --noEmit` — exit 0 with no output.

Additional checks:

- `for script in scripts/*.py; do python "$script" --help ...; done` — `PASS: 23 standalone Python scripts accepted --help`.
- `git diff --check` — exit 0, no output.
- `npm run build:data` preserved `siteBuiltAt=2026-08-25T01:15:01.401105+00:00` and produced no payload drift.

## Proposed PR description

### Summary

Validate all 13 audit findings independently and fix the 10 that were both actionable and reproducible in this round. Restore evidence gating in merged products, make recovery workflows fail safely, add missing CI gates, correct the 美廉社 taxonomy, make result timestamps timezone-aware, pin Actions, stop tracking TypeScript build output, and prevent distinct-count inflation.

### Bugs fixed

- Fixed BUG-002, BUG-004 through BUG-011, and BUG-013.
- Classified BUG-005 and BUG-007 as partially correct and fixed their reproduced behavior.
- Rejected BUG-003 with a clean, uninstalled-package pytest reproduction.
- Left BUG-001 for a dedicated cache migration and BUG-012 for an authorized paid-service verification window.

### Root causes

The fixes address duplicated projection gates, a stale privacy-purge fallback, missing compile/import CI coverage, a copied brand typo, naive cross-process timestamps, volatile documentation statistics, an ignored-build-cache omission, partial Action pinning, and treating set cardinalities as additive counts.

### Testing

New regressions were demonstrated red-before/green-after for BUG-002, BUG-004, BUG-005, BUG-008, BUG-009, BUG-011, and BUG-013. BUG-006 is covered by a project-wide TypeScript compiler gate; BUG-007 by a 23-script uninstalled-package smoke loop. All repository gates and exact final results are listed above.

### Linear

- DEV-193: keep Ready/High until the separator migration proof is ready.
- DEV-109: keep Done; its privacy purge remains complete, and this PR only repairs a stale downstream fallback.
- Proposed issue drafts for every other confirmed/partially correct finding are included in this report. No Linear state was read or changed outside the `AUDIT.md` record.

### Risks

`BUG-013` intentionally uses a conservative lower bound because identities are unavailable at publish time. `BUG-005` changes the canonical brand for future matching but retains the old typo as an alias; the current corpus has no authoritative 美廉社 title/vendor and no matching override. Workflow changes make cache loss fail visibly instead of attempting a truncated publish. No label cache, raw post store, or frozen `siteBuiltAt` value changed.
