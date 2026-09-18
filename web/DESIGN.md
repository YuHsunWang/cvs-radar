# CVS Radar Web — Frontend Design

> Component inventory last verified: 2026-08-03 against `components/ShelfExplorer.tsx`.
> The "Visual design" section below still describes the retired classic card
> layout and has **not** been re-verified against the shelf-edge UI.

A mobile-first static web frontend for CVS Radar. It presents the ranked
convenience-store product reviews as a shopper-facing app you can read standing
in front of the shelf. Built with Next.js and deployed as a static site on
Vercel — no backend at runtime.

## Overview

The Python pipeline (in the repo root) turns PTT reviews into product-level
scores and writes `data/results.json`. This frontend reads a **de-identified,
display-ready** projection of that file and renders it. All interaction
(search, brand filter, sort, expand) happens client-side over the loaded JSON.

## Data pipeline

`web/build_data.py` reads the de-identified `data/results.json` and emits
`web/public/data.json`. It reuses the project's own Python
(`cvs_radar.store.load_results`, `cvs_radar.app_helpers.consensus_distribution`
and `volume_label`) so the web numbers match the analysis exactly.

Only display fields are emitted — per-account data (`contributors`, `profiles`)
is dropped entirely, and the positive / neutral / negative percentages are
pre-computed in Python so the frontend stays simple.

Per-product shape:

```jsonc
{
  "id": "7-11::伯爵紅茶拿鐵",
  "brand": "7-11",
  "productName": "伯爵紅茶拿鐵",
  "price": "65",            // may be null
  "category": "飲料",       // "" renders as 其他
  "fairScore": 89,
  "recommendationScore": 94, // null when confidence is low
  "consensus": "一致好評",  // 一致好評 / 評價兩極 / 資料不足
  "confidence": "高",       // 高 / 中 / 低
  "nPosts": 18,
  "nComments": 64,
  "volumeLevel": "充足",    // 充足 / 中等 / 不足
  "positivePct": 72,        // null when insufficient data
  "neutralPct": 18,
  "negativePct": 10,
  "likes": ["茶香明顯", "甜度剛好"],
  "cautions": ["部分門市缺貨"],
  "excerpt": "……",
  "postUrls": ["https://www.ptt.cc/..."],
  "latestDate": "2026-06-30"
}
```

## Component architecture

```
app/layout.tsx          root layout, metadata, global styles
app/page.tsx            the only shopper route — mounts ShelfExplorer with the built payload
app/shelf.css           the sl-* styles for the shelf-edge label layout
components/ShelfExplorer owns search / brand / category / sort state, the desktop
                         filter rail, and the mobile filter sheet
components/ShelfCard     shelf-edge label row with an expand/collapse detail button
components/ProductDetail 單品判斷 detail: score, consensus bar, volume, author review, comment summary, source links
components/SearchBar     persistent live search
components/CountUp       animated score counter used by ShelfCard
lib/data.ts             types + loader + pure filter / sort / search helpers
```

`lib/data.ts` holds all non-UI logic so the components stay presentational and
independently testable.

## Visual design

Follows `../docs/redesign/app_mockup_mobile_v3.png`: a single mobile column with

- a header with product count and data-update notice,
- an always-visible latest-review-date range slider plus a hide-unscored toggle and sort menu,
- intent category chips (正餐 / 甜點 / 冰品 / 飲料 / 麵包 / 零食 / 其他),
- brand chips (7-11 / 全家 / 萊爾富 / OK / 美聯社 / 其他, each in its brand colour),
- a result count and section title, and
- ranked product cards.

Each collapsed card shows rank, brand, name, recommendation score, consensus,
volume and price·category. Low-confidence scores carry a 樣本少 label.
Tapping anywhere on the card expands an inline 單品判斷 block with the large
recommendation score, original fair score, a green/amber/red consensus
distribution bar, and a volume indicator.

The expanded panel (`ProductDetail`, styled with the `sl-k-*` block in
`shelf.css`) reads as the back of the same shelf label rather than as a separate
surface. It spans the full card width and joins the row above it with a dashed
hairline — a perforation on one ticket, not the edge of a second object. (It
previously cut with a near-black rule while also being inset 12px and tinted:
three devices all saying "separate block", which is what made an open card look
like two stacked things.) Order is 作者評價 → 評價重點 → 原文: the summary is one short sentence that frames the bullets, so reading it first makes them land as detail rather than as a cold list. Both polarities share one heading
and one list, each row carried by a 讚/警告 icon in the polarity colour so the
distinction survives greyscale; likes come first, then cautions. An empty list
says what was found rather than rendering 無 as though it were a review point,
and a `reviewProvisional` row is marked 暫定 even when it has no summary at all.
Multi-reviewer summaries arrive joined with 「；」 and are split back into numbered
takes.

It is built for vertical economy: evidence items are ≤19 characters and the
median summary is 17, so per-item containers, not text, are what make this panel
tall — and an inline expander that pushes the next product off a 360×800 screen
defeats its own purpose. Typical panels run 150–300px.

Palette: primary teal `#0F7C7C`; consensus bar green `#2E9E5B` / amber `#E0A417`
/ red `#D64545`; brand colours per the chips above. The expanded panel uses the
`sl-*` tokens instead (`--sl-ink`, `--sl-good`, `--sl-hot`, `--sl-mono`).

## Interaction

- Default: all brands, sorted by 近期推薦.
- Search matches product name + brand (NFKC, case-insensitive), live.
- Brand chips single-select; tap again to clear.
- Category chips single-select; tap again to clear.
- The card summary button toggles its detail; detail actions remain independent keyboard targets.
- The sort menu supports 近期推薦、討論熱度、綜合評分高到低及綜合評分低到高。
- The inclusive latest-review-date range uses one always-visible dual-thumb slider and filters live.
- 暫無綜合評分的商品可隱藏；有效日期篩選會在結果數下方摘要並可清除。
- Results render in 30-item batches to keep the mobile DOM responsive.
- The bell opens a data-update notice with product count and latest review date.

## Tech & deployment

Next.js (App Router) + TypeScript + Tailwind CSS, static export
(`output: 'export'`). Deploy on Vercel with **Root Directory = `web/`**;
the framework is auto-detected. The static data is committed as
`public/data.json`; regenerate it with `npm run build:data` after re-running
the Python pipeline.

## Why these choices

- **Static, no backend** — the demo data is a precomputed snapshot, so a static
  site is faster, free to host, and has no server to keep alive.
- **Precompute display fields in Python** — one source of truth for the numbers,
  and the browser never sees account-level data.
- **Whole-card click** — the shelf-side use case is one-thumb; a large tap
  target beats a small chevron.
