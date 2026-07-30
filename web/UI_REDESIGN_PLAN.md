# CVS Radar UI Redesign Plan — DEV-113

## Scope and success condition

This is a design-and-delivery plan, not an implementation. The redesign must
continue to serve a shopper standing at a convenience-store shelf, operating a
phone one-handed. The static data contract remains unchanged: `build_data.py`
projects `data/results.json` into `web/public/data.json` and deliberately
publishes only the validated product fields (`web/build_data.py:234-270`,
`web/build_data.py:273-297`, `web/build_data.py:321-354`). The frontend is a
static Next export (`web/next.config.js:4-9`), and no phase introduces a
runtime backend.

All implementation work begins only after the owner resolves the decisions in
the final section. A visual preference is not silently selected by this plan.

## 1. Current-state audit

### What actually ships

- The declared stack is Next 15.4, React 19.1, TypeScript 5.5, Tailwind 3.4,
  and Vitest; neither Playwright nor another browser-test package is declared
  (`web/package.json:12-27`). `output: 'export'` and `trailingSlash: true` are
  configured (`web/next.config.js:4-9`).
- Every route reads the already-generated `public/data.json` with `readFile` at
  static rendering time (`web/app/page.tsx:1-13`, `web/app/shelf/page.tsx:14-20`,
  `web/app/classic/page.tsx:13-19`). The browser-side explorers then keep the
  products and filters in React state (`web/components/ShelfExplorer.tsx:77-98`,
  `web/components/ProductExplorer.tsx:38-57`).
- The only Tailwind extensions are `teal.radar`, three `consensus` values, and
  `shadow.card` (`web/tailwind.config.ts:7-20`). In current source,
  `shadow-card` is used by the classic card (`web/components/ProductCard.tsx:52`),
  but a source search finds no use of `teal-radar` or `consensus-*` utilities;
  the visible teal and status colours are mostly arbitrary-value utilities or
  CSS literals (for example `web/components/ProductCard.tsx:52-61`,
  `web/lib/data.ts:256-272`, `web/app/shelf/shelf.css:4-23`).
- Global styling is intentionally small—103 lines—and supplies the page
  background, system font stack, and custom date-slider thumb styling
  (`web/app/globals.css:5-25`, `web/app/globals.css:38-103`). The shelf route
  has 604 lines of separate scoped CSS (`web/app/shelf/shelf.css:1-604`).

### Implemented visual language and token inventory

| Layer | Implemented values / use | Source |
| --- | --- | --- |
| Tailwind custom palette | `teal.radar #0F7C7C`; `consensus.green #2E9E5B`; `consensus.amber #E0A417`; `consensus.red #B91C1C`; `shadow.card 0 3px 12px rgba(15,36,52,.10)` | `web/tailwind.config.ts:7-20` |
| Global surface and control colour | page `#F7F5EF`; date thumb `#0F7C7C`; focus halo `rgb(15 124 124 / 25%)` | `web/app/globals.css:13-15`, `web/app/globals.css:60-103` |
| Classic card palette actually rendered | arbitrary teal `#0F7C7C`; brand badges `#00824E`, `#0876CE`, `#E51F26`, `#EF7D00`, `#6C3DBF`; consensus text `#2E7D32` / `#B45309`; sentiment segments `#5A9F28` / `#9B9A92` / `#E84D4D` | `web/components/ProductCard.tsx:15-28`, `web/components/ProductCard.tsx:52-110`; `web/lib/data.ts:256-272` |
| Classic filters | brand-chip colours `#007A53`, `#0B75D1`, `#E51F26`, `#EF7D00`, `#6C3DBF`; selected category and date controls use arbitrary teal | `web/components/BrandChips.tsx:3-9`, `web/components/CategoryChips.tsx:19-32`, `web/components/DateRangeSlider.tsx:75-124` |
| Shelf local variables | aisle/tag/ink/soft/hair `#E7E4DB` / `#FFF` / `#17130E` / `#6E685D` / `#D9D5CA`; highlight/hot/status `#FFE500` / `#E5301F` / `#1F8A4C` / `#B4700C` / `#B0261A` / `#8A857B` | `web/app/shelf/shelf.css:4-23` |
| Shelf brand rails | `#F26522`, `#009B4C`, `#E51F26`, `#F5A623`, `#6C3DBF`, `#6B7280` | `web/components/ShelfCard.tsx:13-21`; `web/components/ShelfExplorer.tsx:33-43` |
| Typography/layout language | classic uses system sans and Tailwind cards; shelf adds CJK system fallbacks plus a mono face, label/aisle metaphors, 4–5px corners, patterned surfaces, and 720/900/640px breakpoints | `web/app/globals.css:17-25`; `web/app/shelf/shelf.css:16-30`, `web/app/shelf/shelf.css:227-252`, `web/app/shelf/shelf.css:462-594` |

### Documentation and implementation drift to repair

The following are verified differences, not proposed changes.

1. **Consensus red value:** `DESIGN.md` documents `#D64545`; Tailwind defines
   `#B91C1C` (`web/DESIGN.md:65-66`, `web/tailwind.config.ts:11-15`). The
   configured `#B91C1C` token is not currently consumed; the classic sentiment
   bar uses `#E84D4D`, classic caution text uses Tailwind `red-700`, and shelf
   score/status colours use `#B0261A` / `#E5301F`
   (`web/lib/data.ts:256-272`, `web/components/ProductDetail.tsx:41-45`,
   `web/app/shelf/shelf.css:10-15`). Therefore no single red is actually
   rendering across the app. Recommendation pending Decision 4: standardize
   semantic negative on the current configured `#B91C1C`, subject to contrast
   checks, rather than restore the undocumented/unused `#D64545`.
2. **Documented primary architecture is no longer `/`:** the document says
   `app/page.tsx` owns interaction state and lists `ProductExplorer`,
   `TopBar`, `CategoryChips`, `BrandChips`, `DateRangeSlider`, and
   `ProductCard` as the shopper composition (`web/DESIGN.md:43-57`). Root now
   imports `ShelfExplorer` and shelf CSS (`web/app/page.tsx:1-13`); the listed
   component tree is used by `ProductExplorer`, which is mounted only by
   `/classic` (`web/components/ProductExplorer.tsx:1-10`,
   `web/app/classic/page.tsx:1-19`).
3. **`/` is not the documented classic filter model:** the document promises
   an always-visible dual-thumb date slider plus hide-unscored toggle and sort
   menu (`web/DESIGN.md:61-73`). The root shelf UI uses relative-date preset
   buttons and button-style sort choices (`web/components/ShelfExplorer.tsx:55-68`,
   `web/components/ShelfExplorer.tsx:312-365`), hides all filter controls on
   phones, and exposes them in a FAB/bottom sheet (`web/app/shelf/shelf.css:462-594`).
   The dual slider exists only in the classic component
   (`web/components/ProductExplorer.tsx:159-209`,
   `web/components/DateRangeSlider.tsx:74-140`).
4. **Header/update-notice behaviour differs:** the document says a bell opens
   a data-update notice (`web/DESIGN.md:74-84`). The current root shelf header
   renders a live 24-hour clock and an update strip (`web/components/ShelfExplorer.tsx:369-396`),
   while the `TopBar` component is only imported by `ProductExplorer`
   (`web/components/ProductExplorer.tsx:5-10`, `web/components/ProductExplorer.tsx:119-128`).
5. **Expanded-card contents differ:** `DESIGN.md` says the expanded block
   contains a large recommendation score, original fair score, consensus
   distribution, and volume (`web/DESIGN.md:68-70`). The shared expanded
   `ProductDetail` instead contains author excerpt, likes/cautions, and source
   links (`web/components/ProductDetail.tsx:9-79`). The classic card places its
   score and compact sentiment bar before expansion
   (`web/components/ProductCard.tsx:92-147`); shelf does not render that
   distribution (`web/components/ShelfCard.tsx:94-121`).
6. **“Brand colours per chips” is no longer a coherent rule:** the document
   describes brand chips (`web/DESIGN.md:64-66`), but root uses shelf rails
   (`web/components/ShelfCard.tsx:61-64`) and has three incompatible brand
   palettes (classic chips, classic badges, shelf rails; see the inventory
   above). In addition, `lib/data.ts` lists `美聯社`
   (`web/lib/data.ts:44-55`), whereas shelf hides it as a stated typo and
   maps a different `美廉社` spelling (`web/components/ShelfExplorer.tsx:33-43`).
7. **The shelf stylesheet comment is stale:** it says it is imported only by
   `app/shelf/page.tsx` (`web/app/shelf/shelf.css:1-2`), but root imports the
   same file (`web/app/page.tsx:3-5`).
8. **Testing documentation omission:** the only test file is the pure-data
   Vitest suite (`web/lib/data.test.ts:1-204`), and no browser/visual test tool
   is declared (`web/package.json:5-27`). `DESIGN.md` contains no screenshot
   baseline or visual-regression policy (`web/DESIGN.md:1-122`).

## 2. Route architecture and consolidation recommendation

| Route | What it renders now | Likely audience / job | Evidence |
| --- | --- | --- | --- |
| `/` | `ShelfExplorer` plus shelf CSS; it has a shelf-label visual system, live store clock, search, 30-item batching, and mobile filter FAB/sheet. | **Actual public default** and the closest match to a standing-at-shelf task. The intended audience is inferred from the literal shelf UI; the product-owner intent is otherwise UNVERIFIED. | `web/app/page.tsx:3-13`; `web/components/ShelfExplorer.tsx:368-522`; `web/app/shelf/shelf.css:462-594` |
| `/shelf` | The same `ShelfExplorer`, same source data loading, and same shelf CSS as `/`; only title/description/canonical metadata differ. | A duplicate shelf-label URL, not an independent user journey. | `web/app/page.tsx:3-13`; `web/app/shelf/page.tsx:4-20` |
| `/classic` | `ProductExplorer`: TopBar, always-visible category/brand chips, dual-date slider, select sort control, two-column desktop card grid, and `ProductCard`. | A desktop-friendly, information-dense comparison variant and the only route matching most of the existing `DESIGN.md` component description. | `web/app/classic/page.tsx:4-19`; `web/components/ProductExplorer.tsx:119-306` |

**Recommendation:** choose one canonical shopper route, `/`, built from the
validated shelf-side interaction model; remove `/shelf` as a duplicate route
after preserving any needed incoming-link handling. Keep `/classic` only as a
short-lived comparison/prototype during migration, then retire it if the
canonical route reaches functional parity.

`/classic` is retireable, but retirement loses its immediately visible dual
date-range slider, chip-based filters, select menu, TopBar notice affordance,
two-column desktop comparison layout, and the compact pre-expand sentiment
bar (`web/components/ProductExplorer.tsx:121-209`,
`web/components/ProductExplorer.tsx:251-275`, `web/components/ProductCard.tsx:92-110`).
Those are capabilities to deliberately preserve, defer, or reject in Decision
1—not accidental losses caused by deletion.

## 3. The `/shelf` CSS problem: incremental migration

The current 604-line stylesheet has useful component scoping (`sl-`), but its
local variables and literals bypass the Tailwind theme and conflict with
classic colours (`web/app/shelf/shelf.css:1-23`,
`web/tailwind.config.ts:7-20`). Do not big-bang rewrite it.

1. **Inventory and token foundation (no layout change):** introduce primitive
   colour, surface, border, typography, radius, shadow, focus, and motion
   tokens; map them to semantic aliases such as `--surface-canvas`,
   `--surface-card`, `--text-primary`, `--text-muted`, `--action-primary`,
   `--status-positive`, `--status-caution`, `--status-negative`, and
   `--focus-ring`. Expose the same approved values through Tailwind names.
   Keep the `sl-*` selectors intact, but replace only the variable block first.
2. **Migrate by component boundary:** move sign/aisle, controls, shelf card,
   detail, and mobile sheet one independently reviewed group at a time. Each
   group may use semantic CSS variables initially; convert stable repeated
   patterns to Tailwind utilities or `@layer components` only after its
   before/after screenshots match. Do not convert decoration (medal gradients,
   aisle texture) into false semantic tokens.
3. **Unify shared controls before deleting CSS:** make search, chips, buttons,
   cards, status badges, and focus rings consume the same semantic tokens in
   both the canonical route and any temporary classic route. Preserve route
   DOM/class contracts until the route decision and screenshot comparison pass.
4. **Remove only proven-dead declarations:** after each visual test pass,
   delete superseded literals and record the mapping; do not delete
   `shelf.css` until all four responsive regions (base, 720, 900, and mobile
   640) are covered (`web/app/shelf/shelf.css:29-31`,
   `web/app/shelf/shelf.css:227-229`, `web/app/shelf/shelf.css:462-594`).

## 4. Mobile-first verification

The verification target is an in-store portrait phone, one hand, transient
attention, and glare—not merely a responsive desktop layout. Current evidence
worth preserving includes full-width card buttons (`web/components/ShelfCard.tsx:53-116`),
a 54px fixed filter FAB (`web/app/shelf/shelf.css:466-480`), safe-area padding
on the sheet action row (`web/app/shelf/shelf.css:567-593`), and reduced-motion
support (`web/app/shelf/shelf.css:599-604`). Current exceptions to correct
include 36px close buttons (`web/app/shelf/shelf.css:546-556`) and small
chip padding/text (`web/app/shelf/shelf.css:156-196`), which must be evaluated
against the final target-size rule.

For every visual phase, verify at 320×568, 360×800, 390×844, and 430×932 CSS
pixels, portrait, at 100% zoom. Test the first-result path with either thumb:
search, inspect the first score, expand/collapse it, open filters, select one
brand and one date option, apply, clear, and load more. Place frequent actions
inside the lower reachable zone or make them full-row targets; keep the filter
entry fixed without covering result actions or browser safe areas. Require a
minimum 44×44 CSS-pixel hit target for standalone controls and a full-card
target for product inspection; use explicit focus states and keyboard checks
as a separate accessibility path.

Treat outdoor readability as an acceptance criterion: no meaning may depend
on colour alone; score/consensus must include text/icon/position; body and
control text must meet WCAG 2.2 AA contrast (4.5:1 normal text, 3:1 large text
and non-text UI), with a 7:1 target for key score/action text on its actual
surface. Verify the selected tokens with an automated contrast check plus a
sunlight simulation/manual device review; record failures as defects rather
than “acceptable on desktop.”

## 5. Phase 0 — screenshot baseline (must precede visual changes)

Do **not** run this capture in the DEV-113 planning change. In a separate,
tooling-only future commit, install the tool and browser exactly as follows:

```bash
cd web
npm install --save-dev @playwright/test
npx playwright install chromium
```

Add `web/playwright.config.ts` and `web/e2e/visual-baseline.spec.ts` with the
following exact baseline script. The fixed clock prevents the shelf header
clock from creating false diffs (`web/components/ShelfExplorer.tsx:139-155`);
reduced motion prevents the radar sweep and other animations from doing so
(`web/app/shelf/shelf.css:63-73`, `web/app/shelf/shelf.css:599-604`).

```ts
// web/playwright.config.ts
import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  use: { baseURL: 'http://127.0.0.1:3000' },
  webServer: {
    command: 'npm run dev',
    url: 'http://127.0.0.1:3000',
    reuseExistingServer: false,
  },
})
```

```ts
// web/e2e/visual-baseline.spec.ts
import { test } from '@playwright/test'

const routes = [
  { name: 'root', path: '/' },
  { name: 'shelf', path: '/shelf/' },
  { name: 'classic', path: '/classic/' },
] as const

const viewports = [
  { name: 'desktop-1440x1000', width: 1440, height: 1000 },
  { name: 'mobile-390x844', width: 390, height: 844 },
] as const

for (const route of routes) {
  for (const viewport of viewports) {
    test(`${route.name} ${viewport.name} before`, async ({ page }) => {
      await page.clock.install({ time: new Date('2026-07-30T04:00:00.000Z') })
      await page.setViewportSize({ width: viewport.width, height: viewport.height })
      await page.emulateMedia({ reducedMotion: 'reduce' })
      await page.goto(route.path, { waitUntil: 'networkidle' })
      await page.getByRole('heading', { level: 1 }).waitFor()
      await page.screenshot({
        path: `docs/screenshots/ui-baseline/before/${route.name}-${viewport.name}.png`,
        fullPage: true,
        animations: 'disabled',
        caret: 'hide',
      })
    })
  }
}
```

Run it from `web/`:

```bash
npx playwright test e2e/visual-baseline.spec.ts --project=chromium
```

The required matrix is exactly six before-images: `/`, `/shelf/`, and
`/classic/` × desktop 1440×1000 and mobile 390×844. They go under
`web/docs/screenshots/ui-baseline/before/` with the six filenames emitted by
the script. Capture the corresponding `after/` set with the same route and
viewport names before every visual pull request; `/shelf/` remains in the
baseline until its retirement is explicitly approved. The current repository
has no such setup (`web/package.json:5-27`).

## 6. Phased work plan

| Phase | Relative size | Shippable deliverable | Acceptance check |
| --- | --- | --- | --- |
| 0. Visual evidence | S | Separate tooling commit: Playwright config/script, browser dependency, and the six immutable `before/` images specified above. No UI redesign in this commit. | Six files exist at the exact paths; route × viewport matrix is complete; fixed-clock/reduced-motion capture command succeeds. |
| 1. Decision and route contract | S | Record the owner’s decisions below; publish a route map naming `/` canonical, each temporary route, its exit criterion, and incoming-link policy. No CSS migration yet. | Owner signs off on Decisions 1–4; no route is redesigned or removed before its documented replacement/retention decision. |
| 2. Token foundation | M | Create the approved primitive → semantic → component token map, wire it into Tailwind/CSS, and add a contrast inventory. Preserve layout and `sl-*` markup. | Automated search shows every newly touched colour references an approved token; `before/` versus `after/` screenshots have no intentional visual change; all key foreground/background pairs meet the stated threshold. |
| 3. Shelf CSS migration | L | Migrate one bounded group per PR: (a) shell/sign, (b) filters, (c) card/status/detail, (d) FAB/sheet and responsive rules. Keep a mapping/deletion log. | Each PR has the six-route screenshot comparison while all routes exist; mobile interaction script/checklist passes; no group introduces raw duplicate status/action colours. |
| 4. Canonical shelf-side UX | L | Implement the owner-approved information hierarchy and consolidated route behavior; retain classic capabilities deliberately chosen in Phase 1, not by default. Add interaction/browser coverage for search, filters, expansion, clear, and load-more. | At four portrait sizes, every core shelf task completes one-handed with 44px standalone targets; desktop remains usable; before/after review and keyboard/focus/contrast checks pass. |
| 5. Route retirement and documentation | M | Remove or retain `/shelf` and `/classic` exactly per Decision 1; delete now-dead CSS/components only after route checks; update `web/DESIGN.md` as the final explicit deliverable. | Route map, screenshots, browser tests, and static build pass. `DESIGN.md` names every surviving route/component and the final interactions; it states the selected palette. If the recommendation is accepted, the corrected values are teal `#0F7C7C`, green `#2E9E5B`, amber `#E0A417`, red `#B91C1C`; if the owner selects another red, document that exact approved value and remove all competing status-red literals. |

The Phase 2 token design follows a primitive → semantic → component structure:
raw approved values feed purpose names, then component aliases. It avoids the
current situation where `#0F7C7C` is both a configured token and repeated raw
value (`web/tailwind.config.ts:7-15`, `web/components/SearchBar.tsx:10-26`).

## 7. Open decisions for the repository owner

1. **Route strategy — recommendation: consolidate to canonical `/`; retire
   duplicate `/shelf`, then retire `/classic` after deliberately preserving
   approved capabilities.**
   - One canonical route: lowest maintenance and one design system; loses
     classic-only controls unless migrated first.
   - Canonical `/` plus supported `/classic`: retains a comparison-oriented
     desktop variant; doubles visual/accessibility regression obligations.
   - Keep all three: preserves experiments, but `/` and `/shelf` are currently
     duplicate UI and all variants drift independently.
2. **Product positioning — recommendation: keep mobile-first, one-handed
   shelf-side use as the primary job.**
   - Keep it: optimizes the stated purchase moment and makes desktop an
     enhancement.
   - Hybrid: preserve shelf tasks but elevate at-home comparison equally; adds
     hierarchy and testing complexity.
   - Change it: optimize research/desktop browsing; knowingly abandons the
     current shelf-side product premise.
3. **Primary colour — recommendation: retain teal `#0F7C7C` as the approved
   primary action/identity colour.**
   - Keep teal: preserves current recognizability and existing high-visibility
     controls.
   - Use shelf ink `#17130E`: strengthens the label metaphor but makes the
     product feel less like the documented teal identity.
   - Choose a new primary: permits a full rebrand, but requires fresh contrast,
     status, screenshot, and documentation work.
4. **Negative/status red — recommendation: standardize on the currently
   configured `#B91C1C` after contrast validation.**
   - Use `#B91C1C`: aligns the final design with the existing Tailwind
     configuration and is the most defensible migration target.
   - Restore documented `#D64545`: preserves the old document but requires a
     new token change and contrast proof.
   - Select a new approved red: can better fit the chosen art direction, but
     must replace all current negative variants and be recorded in `DESIGN.md`.

No decision is needed from the owner for correctness-only work: preserving the
static data boundary, capturing the before-set first, replacing duplicate
tokens incrementally, and bringing `DESIGN.md` into sync are mandatory.
