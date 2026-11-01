# Product images

The static frontend shows reviewed images. The manifest has 79 7-11 images, 141
FamilyMart images and 1524 PTT images, checked by eye against the product name on
review sheets in 2026-11. The repo owner approved official 7-11 and FamilyMart
images, and approved PTT images without asking each author first: every PTT image
links to its source article and is removed on objection (see removal below).
PTT photos show what a poster bought, so the package may differ from today's.
Matching names and official IDs alone do not establish the exact flavour, size,
package, or image identity. FamilyMart answers scripted requests with HTTP 403,
so its images must be re-checked in a real browser run by an operator.

Edit `data/labels/product_images.csv` with UTF-8 BOM and CRLF. Keep `official_id`
as text, including the leading zero in `0904302`. Use one retained row per exact
public `product_id` (`brand::productName`, including case). Duplicate product IDs
abort the build, including an official/PTT pair or an enabled/removal pair.

Review retailer/brand sources first (`official_retailer`, `official_brand`). Use
`ptt` only as a manually reviewed supplement when no suitable official image has
been established. A PTT source must link to its CVS article, never an account
page. There is no name matching, first-post-image selection, or automatic PTT
fallback. Select one reviewed source in the existing row; keep disabled and
removal rows instead of appending alternatives.

Before enabling a row, verify the exact product and image, and separately verify
permission for the intended external image display. Record review evidence in
your restricted review record, outside the public payload. Set both
`identity_status` and `rights_status` to `verified` only with that evidence. Set
`checked_at` to the actual review date, clear any resolved `takedown_reason`, and
set `enabled` to `1`. Unknown/unreviewed rows stay `unknown` and `0`; `enabled`
accepts exactly `0` or `1`, with malformed values aborting the build. Both URLs
must use HTTPS without credentials, control characters, or nonstandard ports.
Unsupported sources or unsafe URLs fail closed. Reachability is not checked by
the build. This workflow grants no image download or rehosting authorization.

To remove an image, set `enabled=0`, record `takedown_reason`, retain the row, and
rebuild from the repo root:

```bash
cd web
npm run build:data
npm test
npx tsc --noEmit
npm run build
```

Use a Python environment with the repository dependencies installed. Rebuilding
updates `web/public/data.json` and the static output; a live removal takes effect
only after the normal publishing process publishes that output.

Only `image: null` or `{imageUrl, sourcePageUrl, sourceKind}` enters public product
data. Review dates, candidate IDs, permission records and removal reasons do not.
Images load only when a card is opened; collapsed cards keep the category icon
and request nothing. A missing image shows nothing in detail and a failed one
shows readable fallback text; failures retry when the item or image metadata changes.
Tests use synthetic `.example` URLs, never approved real images.
