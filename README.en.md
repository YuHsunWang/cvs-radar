# CVS Radar

> Standing in front of the shelf, decide what to buy in 30 seconds.

[![CI](https://github.com/YuHsunWang/cvs-radar/actions/workflows/ci.yml/badge.svg)](https://github.com/YuHsunWang/cvs-radar/actions/workflows/ci.yml)
[![GitHub Pages](https://github.com/YuHsunWang/cvs-radar/actions/workflows/pages.yml/badge.svg)](https://github.com/YuHsunWang/cvs-radar/actions/workflows/pages.yml)
![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![Next.js](https://img.shields.io/badge/Next.js-15-000000?logo=nextdotjs&logoColor=white)
![TypeScript](https://img.shields.io/badge/TypeScript-5-3178C6?logo=typescript&logoColor=white)

**[Live demo](https://cvs-radar.vercel.app/)** ·
**[GitHub Pages mirror](https://yuhsunwang.github.io/cvs-radar/)** ·
**[繁體中文](README.md)**

Whether a new convenience-store product is any good is an answer buried in a thousand-odd
reviews and replies on Taiwan's PTT CVS board. CVS Radar turns that into something you can
use while standing in the aisle: search it, compare it, see *why* people recommend it or
don't, and jump back to the original thread in one tap.

The site covers roughly 800 products, drawn from close to a thousand posts and over ten
thousand comments across the past year. Crawling, semantic reading, statistical scoring and
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
  <img src="docs/screenshots/product-detail.png" width="520" alt="Expanded product card: author verdict, pros and cons distilled from comments, links to the source thread" />
</p>

<p align="center">
  A mobile-first ranked card list. Expand any card to read the author's verdict, the pros
  and cons distilled from comments, and links back to the original thread.
</p>

## The problem

Discussion of a new convenience-store product is scattered across separate posts and
replies. Reading a single review means inheriting one person's palate; reading the replies
means judging sarcasm, off-topic tangents and sample size yourself. CVS Radar consolidates
those signals into comparable, product-level information:

- **What should I eat today?** Narrow down by bento, dessert, ice cream, drinks, bread or
  snacks.
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
3. **Preserve the actual experience** — author verdicts keep their original sentences;
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

Only a single static JSON file runs in the user's browser; all semantic reading and
statistics happen in the batch pipeline before publication. Once loaded, search and
filtering run locally with no backend.

| Layer | Technology |
|---|---|
| Data collection | Python, Requests, Beautiful Soup |
| Semantic labelling | Four LLM layers (sentiment, product name, excerpt, representative comments), each cached by content fingerprint in `data/labels/*.csv` |
| Scoring | Rule-based sentiment, SnowNLP adapter, Bayesian shrinkage, time decay |
| Service layer | Framework-independent query API with a FastAPI adapter |
| Web | Next.js 15, React 19, TypeScript, Tailwind CSS, Lucide |
| Quality | Pytest, Vitest, Ruff, TypeScript / Next.js production build |
| Deployment | Vercel (primary) plus a GitHub Actions / GitHub Pages static mirror |

## What this project is meant to show

- **Use an LLM without making the results irreproducible.** All four semantic layers are
  LLM-judged, but every result is cached into version control under a content fingerprint
  that includes the prompt version. The same input recomputes without calling the model
  again and yields identical scores — which is what makes CI viable and the cost bounded.
- **Don't overreach statistically.** Bayesian shrinkage, per-user caps, time decay, and no
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
scripts/                   audit, labelling and excerpt rebuild utilities
tests/                     backend and data-build regression tests
web/
  app/                     Next.js App Router entry
  components/              filters, product cards and detail views
  lib/                     typed search, filter and sort logic
  public/data.json         product-level payload the browser reads
data/results.json          precomputed product-level snapshot
data/labels/               fingerprint-keyed LLM label caches
docs/screenshots/          screenshots generated from the production build
.github/workflows/         CI and the GitHub Pages mirror deployment
```

## Run locally

### Web app

```bash
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
and should respect the source site's rate limits and terms.

## Verification

```bash
python -m pytest -q
ruff check .

cd web
npm test
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
