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

## Vercel

- Root Directory: `web/`
- Framework Preset: Next.js
- Build Command: `npm run build`

Regenerate `public/data.json` with `npm run build:data` whenever the
de-identified `../data/results.json` snapshot changes.
