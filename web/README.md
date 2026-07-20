# CVS Radar Web

Static, mobile-first Next.js frontend for CVS Radar. Runtime data comes from
`public/data.json`, generated from the de-identified `../data/results.json`.
Search, intent-based category and brand chips, two-way date/volume/score
sorting, score/date filtering and whole-card detail expansion all run locally
in the browser.

The collapsed card exposes a stable, fixed-anchor recommendation score. The
original Bayesian fair score remains available in the detail view for
transparency. Low-confidence products show neither a recommendation score nor
a sentiment percentage distribution.

## Local setup

```bash
npm install
npm run build:data
npm test
npm run dev
```

Open the dev server URL printed by Next.js.

## Static build

```bash
npm run build
```

`next.config.js` uses `output: 'export'`, so production output is written to
`out/`.

The initial result list renders 30 products. Additional products are appended
in 30-item batches with the load-more control.

## Analytics (GA4)

Analytics is gated on `NEXT_PUBLIC_GA_ID` (a GA4 Measurement ID, `G-XXXXXXX`).
When the variable is unset — local dev, forks — no GA script is loaded and all
tracking calls are silent no-ops. Set it in the Vercel project environment to
enable tracking in production. All calls go through `lib/analytics.ts`;
components never use `gtag` directly.

Custom events (no PII; no free text beyond the search term itself):

| Event | Params | Fired when |
| --- | --- | --- |
| `search` | `search_term` | query settles (800 ms debounce), non-empty |
| `product_expand` | `product_id`, `brand`, `category`, `fair_score_bucket` (`70+`/`50-69`/`<50`/`none`) | a product card is expanded (not collapsed) |
| `filter_apply` | `filter_type` (`brand`/`category`/`date_range`/`hide_no_score`), `value` | a filter is applied (clearing does not fire) |
| `sort_change` | `sort_key` | sort dropdown changes |
| `outbound_ptt_click` | `product_id` | an original-post PTT link is clicked |

## Vercel

- Root Directory: `web/`
- Framework Preset: Next.js
- Build Command: `npm run build`

Regenerate `public/data.json` with `npm run build:data` whenever the
de-identified `../data/results.json` snapshot changes.
