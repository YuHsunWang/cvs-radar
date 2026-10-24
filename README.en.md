# CVS Radar

> Standing in front of the shelf, decide what to buy in 30 seconds.

[![CI](https://github.com/YuHsunWang/cvs-radar/actions/workflows/ci.yml/badge.svg)](https://github.com/YuHsunWang/cvs-radar/actions/workflows/ci.yml)
[![GitHub Pages](https://github.com/YuHsunWang/cvs-radar/actions/workflows/pages.yml/badge.svg)](https://github.com/YuHsunWang/cvs-radar/actions/workflows/pages.yml)
![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![Next.js](https://img.shields.io/badge/Next.js-15-000000?logo=nextdotjs&logoColor=white)
![TypeScript](https://img.shields.io/badge/TypeScript-5-3178C6?logo=typescript&logoColor=white)

**[Live demo](https://cvs-radar.vercel.app/)** ·
**[繁體中文](README.md)**

Whether a new convenience-store product is any good is an answer buried in a thousand-odd
reviews and replies on Taiwan's PTT CVS board. CVS Radar turns that into something you can
use while standing in the aisle: search it, compare it, see *why* people recommend it or
don't, and jump back to the original thread in one tap.

The site covers roughly 2,300 products, drawn from more than 2,700 posts and 46,000
comments going back to June 2024. Crawling, semantic reading, statistical scoring and
the frontend are all built here, recomputed and republished by a daily schedule, and
running live.

## Product preview

<p align="center">
  <img src="docs/screenshots/app-overview.png" width="920" alt="Home page: search, brand and category filters, recency and buzz sorting, consensus distribution" />
</p>

<p align="center">
  The default ranking surfaces recently well-reviewed products; switching to "buzz" shows
  what people are talking about right now.
</p>

<p align="center">
  <img src="docs/screenshots/app-mobile.png" width="260" alt="Mobile home: shelf header, search, ranked cards and a floating filter button" />
  &nbsp;&nbsp;
  <img src="docs/screenshots/product-detail.png" width="560" alt="Expanded product card: numbered per-review summaries, positive and negative evidence, links to each source thread" />
</p>

<p align="center">
  A mobile-first ranked card list. Expand any card to read a numbered summary of every
  review, the positive and negative points drawn from comments, and a link back to each
  original thread.
</p>

The home page includes quick filters on mobile. Its URL preserves search, brand,
category, date preset, sort order, the option to hide unscored products and the last opened product;
copy it to share the current shelf.

Product details can also reveal official nutrition labels: whole-package calories
from 7-11 and FamilyMart, plus per-serving nutrients, serving size and package serving
count for some FamilyMart products. Unmatched data stays blank.

## The problem

Discussion of a new convenience-store product is scattered across separate posts and
replies. Reading a single review means inheriting one person's palate; reading the replies
means judging sarcasm, off-topic tangents and sample size yourself. CVS Radar consolidates
those signals into comparable, product-level information:

- **What should I eat today?** Narrow down by hot food, dessert, ice cream, drinks, bread
  or snacks. (The labelling layer is finer-grained — 11 categories including bento, instant
  noodles, dairy and merchandise — which the frontend folds into these six plus "other".)
- **Is it worth buying?** The collapsed card already shows score, consensus, volume, date
  and price.
- **Why do people like or dislike it?** Expand to read the author's verdict, then comment
  sentiment, then the source.
- **Can I trust this number?** Low-sample products show **no** score and no percentage
  distribution. About a quarter of products stay blank for this reason — better to say
  nothing than to publish a precise-looking number that three people produced.

## From one review to a buying decision

<p align="center">
  <img src="docs/workflow-overview.png" width="1100" alt="Five stages: public posts, product consolidation, semantic reading, consensus aggregation, fast verification" />
</p>

1. **Collect public reviews** — read product posts and comments from the PTT CVS board.
2. **Consolidate into one product** — identify chain, product name and price, and merge
   entries that are named differently but are the same item.
3. **Preserve the actual experience** — author verdicts become concise summaries traceable to source sentences;
   comments are classified positive, neutral or negative, excluding tangents, bare
   agreement and talk about a different chain. When a post covers several products,
   sentences about the neighbouring product are excluded.
4. **Aggregate consensus and recency** — one person repeating themselves is not amplified,
   and insufficient samples get no score. Recency ranking balances rating against freshness
   (24-day half-life); buzz answers what people are discussing now.
5. **Return to the evidence** — the card gives the summary; expanding it still yields the
   author verdict, representative comments and links to the source.

## Architecture

<p align="center">
  <img src="docs/architecture-overview.png" width="1100" alt="Architecture: crawl, LLM labelling, scoring, frontend data build, static site" />
</p>

Both pages read the same `web/public/data.json` at build time; all semantic reading and
statistics happen in the batch pipeline before publication. Once loaded, search and
filtering run locally with no backend.

| Layer | Technology |
|---|---|
| Data collection | Python, Requests, Beautiful Soup |
| Semantic labelling | Five LLM layers (sentiment, product name, excerpt, representative comments, category), each cached by content fingerprint in `data/labels/*.csv` |
| Scoring | Rule-based sentiment, SnowNLP adapter, Bayesian shrinkage, configurable time decay (currently disabled) |
| Service layer | Framework-independent query API with a local FastAPI adapter; the public site makes no API calls |
| Web | Next.js 15, React 19, TypeScript, Tailwind CSS, Lucide |
| Quality | Pytest, Vitest, Ruff, TypeScript / Next.js production build |
| Deployment | Vercel (primary) plus a GitHub Actions / GitHub Pages static mirror |

## How scoring works

A comment is first checked for eligibility, then weighted and combined with the other
opinions about the product. The implementation is in `cvs_radar/scoring/compute.py`,
with parameters in `config.yaml`.

### 1. Weighting each opinion

```
weight = credibility(account) × role_weight(role) × exp(−λ · age_in_days)
```

- **Time decay** is currently disabled (`λ = 0.0`), so age does not change an opinion's
  scoring weight. The frontend's recency and buzz rankings still use a separate 24-day
  half-life.
- **Role weights** are `1.0` for both authors and commenters.
- **Account credibility** is `max(0.1, 1 − suspicion)`, reducing suspicious accounts'
  influence without removing them.

### 2. Suspicion signals (`cvs_radar/preference.py`)

Five weak signals are computed from account activity, but only three currently have
non-zero weights. Accounts with fewer than 5 eligible comments receive no penalty.

| Feature | Weight | Signal |
|---|---|---|
| `one_sided` | 0.00 | Praising one brand while criticizing others (observation only) |
| `single_brand` | 0.00 | Activity concentrated on one brand (observation only) |
| `extreme` | 0.15 | Sentiment repeatedly at \|sentiment\| ≥ 0.85 |
| `burst` | 0.45 | At least 3 comments about one brand within 24 hours |
| `template_like` | 0.40 | Repeated wording with character-bigram Jaccard similarity ≥ 0.8 |

The score **only reduces weight internally; no account is publicly labelled**.
`cvs_radar/store.py` removes and validates account identity fields at the write boundary;
`tests/test_publish_privacy.py` checks the published snapshot. Raw posts in
`data/posts.jsonl` are local pipeline input and are excluded from version control.

The separate `SHILL_DETECTION` mechanism discounts the accused post's author, rather
than everyone discussing the product. It requires at least two distinct accusers and
an accusation ratio of at least 5% in a thread with at least three non-empty comments.

### 3. One person, one stance

`per_user_cap` combines an account's author and comment contributions for the same
product into one weighted stance before product-level aggregation. Repeating a comment
does not turn one person into several voters.

### 4. Bayesian shrinkage and withholding a score

```
fair01 = (prior_strength · μ₀ + Σ wᵢsᵢ) / (prior_strength + Σ wᵢ)     # μ₀ = 0.5, prior_strength = 1.0
n_eff  = (Σ wᵢ)² / Σ wᵢ²
```

`n_eff` is the effective sample size: concentrated weights make it smaller. Below 3,
consensus becomes "insufficient data" and the frontend shows neither a score nor a
positive/neutral/negative percentage split. Roughly a quarter of products have no score.
`web/build_data.py` also requires at least 4 distinct eligible commenters; fewer means
low confidence and no score or split. Authors contribute to the score but cannot replace
those four commenters.

Consensus uses weighted mean `μ` and standard deviation `σ`: `σ ≥ 0.26` means polarized;
`μ ≥ 0.68` and `σ ≤ 0.25` means consistently positive; `μ ≤ 0.45` and `σ ≤ 0.25` means
consistently negative; everything else is mixed.

### 5. Reproducibility with LLM labels

All five semantic layers cache their results in version-controlled `data/labels/*.csv`.
Fingerprints include the context seen by the model and the prompt version. For example,
`sentiment_fingerprint_v2` in `cvs_radar/sentiment.py` hashes:

```
SHA-256( post ID | comment tag | NFKC-normalized comment | brand | product name | post title | prompt version )
```

Brand and product context can change the meaning of a comment, so changing that context
must invalidate its old label. Compare complete pipeline outputs before and after a
scoring change using the same posts and labels; unit tests alone do not establish the
effect on the catalogue.

## What this project is meant to show

- **Use an LLM without making the results irreproducible.** All five semantic layers are
  LLM-judged, but every result is cached into version control under a content fingerprint
  that includes the prompt version. The same input recomputes without calling the model
  again and yields identical scores — which is what makes CI viable and the cost bounded.
  It also makes growing the corpus nearly free: when the archive went from 800 to 2,700
  posts in August 2026, the re-crawled older threads hit the existing cache exactly, so
  only genuinely new material had to be paid for.
- **Don't overreach statistically.** Bayesian shrinkage, per-user caps, at least four eligible commenters, and no
  score at all below the sample threshold. Being willing to leave a gap in the product is
  harder than producing a good-looking ranking.
- **Built end to end, and actually running.** Crawler, labelling pipeline, scoring and
  static frontend, recomputed and republished on a daily schedule — not a one-off demo.
- **Acceptance criteria have to match what you actually want to verify.** The pipeline is
  deterministic given the same input, so a change is validated by running the full pipeline
  before and after and diffing the result set, not by watching unit tests go green.

Details in [scoring decisions](docs/DECISIONS.md), the
[labelling guideline](docs/labeling_guideline.md) and [the ops pipeline](docs/ops-pipeline.md).

## Repository structure

```text
cvs_radar/                 parsing, sentiment, scoring, service and reporting
config.yaml                scoring, sentiment and crawler parameters
crawl_job.py               PTT crawling, storage and recompute entry point
run.py                     offline demo, snapshot queries and pipeline CLI
scripts/                   audit, labelling and excerpt rebuild utilities
  ops/                     local publishing pipeline and cron wrapper
tests/                     backend and data-build regression tests
web/
  app/                     Next.js App Router entry
  components/              filters, product cards and detail views
  lib/                     typed search, filter and sort logic
  build_data.py            projects results and label caches into public data
  public/data.json         product-level payload the browser reads
data/results.json          precomputed product-level snapshot
data/labels/               LLM labels, manual overrides and official nutrition caches
docs/screenshots/          screenshots generated from the production build
.github/workflows/         CI and the GitHub Pages mirror deployment
```

## Run locally

Python 3.12 or newer is required; frontend CI uses Node.js 20. Start each set of
steps below from the repository root.

### Web app

```bash
python -m pip install ".[core]"
cd web
npm ci
npm run build:data
npm test
npm run dev
```

Open `http://localhost:3000`.

### Data pipeline and API

```bash
python -m pip install -r requirements.txt
python run.py --demo
python -m uvicorn cvs_radar.api:app --reload
```

The demo source is offline and uses synthetic sample posts. Crawling requires network access
and should respect the source site's rate limits and terms. The API is an optional local
service; the static site does not need it running.

### FamilyMart food-safety data (standalone batch tool)

`scripts/crawl_family_food.py` reads public pages from FamilyMart's food-safety catalogue
separately from the PTT-only `PttCrawler`. Check the site's current `robots.txt` and terms
before use, respect its load (the default request delay is 1 second), and do not bypass
CAPTCHA, login or other access controls. Images remain official URLs unless
`--download-images` is explicitly supplied; the output directory is ignored by git.

```bash
python scripts/crawl_family_food.py --start-page 1 --max-pages 3 \
  --request-delay 1.5 --output data/family_food/products.jsonl
python scripts/crawl_family_food.py --max-pages 1 --download-images \
  --image-dir data/family_food/images
```

These commands create the ignored output directories. Each JSONL row contains a product's
`product_id`, `name`, `detail_url`, `image_urls`, `serving_size`, `servings_per_container`,
eight nutrient fields (`calories`, `protein`, `fat`, `saturated_fat`, `trans_fat`,
`carbohydrates`, `sugar`, `sodium`), `ingredients`, `allergens` and a UTC `crawled_at`.
Measurements contain `{"value", "unit", "raw_text"}`. Missing fields are `null`;
unparseable measurements retain `raw_text` with a `null` value instead of becoming zero.

Live rendering mode, API responses and current robots/terms remain unverified. Before
running, use the browser Network panel to check pagination at `/Web_FFD_2022/results/{page}`,
product IDs, detail URLs and JSON envelopes. If the HTML or API changes, save a response
without personal data as a local fixture, then update the `parse_list_html`,
`parse_api_response` or `parse_product_html` selectors and tests. Tests must not contact
the official site.

## Verification

Run from the repository root, following the CI checks:

```bash
python -m pip install ".[core,api,dev]"
python -m pytest -q
ruff check .

cd web
npm ci
npm run build:data
git diff --exit-code -- public/data.json
npm test
npx tsc --noEmit
npm run build
```

Three hundred-plus automated tests cover parsing edge cases, product normalization,
sentiment attribution, one-user caps, consensus distribution, author excerpt extraction,
score calibration, search, category and brand filtering, date boundaries, four sort modes
and the static production export.

## Deployment

The primary deployment is <https://cvs-radar.vercel.app/>. Vercel is connected to this
repository with `web/` as its Root Directory, and every push to `main` creates a new
production deployment. The app is a Next.js static export (`output: 'export'`).

<https://yuhsunwang.github.io/cvs-radar/> is a static mirror of the same site, rebuilt by
`.github/workflows/pages.yml` on every push to `main`: rebuild the payload, build the static
export with the `/cvs-radar` base path, upload and deploy.

Both serve the same `web/public/data.json`. That file is recomputed and committed to `main`
by an externally scheduled host running this project's cron wrapper; the repository neither
contains nor proves that host's crontab. If the schedule stalls, the repository does not
update itself; `scripts/check_data_freshness.py` is the observable guard. CI runs backend and frontend checks independently through `.github/workflows/ci.yml`.

The local publisher starts at `scripts/ops/rebackfill-cron.sh` and
`scripts/ops/rebackfill.sh`, which crawls, labels, recomputes and builds the public data.
Before the build, `scripts/fetch_official_kcal.py` and `scripts/fetch_official_nutrition.py`
refresh official nutrition caches, retaining cached values on failure. See
[the ops pipeline](docs/ops-pipeline.md) for the TypeSafe Jev and local Codex CLI setup
required by the five label layers. `.github/workflows/refresh-data.yml` is a manual
recovery fallback that runs none of those five labelers, so it is not a complete
semantic refresh.

## Limitations and next steps

- Semantic classification can still misread sarcasm, memes and comparisons with an elided
  subject, which is why manual overrides and source links are kept.
- Product grouping relies on normalized names and may split or merge unusual naming variants.
- The public site is a precomputed snapshot, not a real-time feed.
- Next: a larger manually labelled gold set, calibrated model comparison, more public sources.

## Disclaimer

This is an independent portfolio project and is not affiliated with PTT or any
convenience-store brand. Product opinions are derived from public user-generated content and
should be treated as decision support, not objective product quality claims.
