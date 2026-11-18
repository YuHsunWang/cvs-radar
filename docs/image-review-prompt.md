<task>
Goal: review queued photo candidates and add the good ones to
`data/labels/product_images.csv`. Owner decision 2026-11-17: Codex does the
review; picks still go out as a PR the owner merges.

Inputs (written daily by the local cron, outside the repo):
- `~/.cache/cvs-radar/image-candidates.csv`: every non-PTT link in the
  product's PTT articles (product_id, post_url, image_url, nearby_text).
  `image_url` may be a photo page (postimg.cc) or short link (myppt.cc):
  open it, and store the direct image file URL it leads to, not the page.
- `~/.cache/cvs-radar/familymart-image-candidates.csv`: FamilyMart official
  photos already saved locally (product_id, official_id, source_page_url,
  image_url, local_file). Open `local_file`; never fetch FamilyMart yourself
  (it answers 403 to scripts).

Rules: `docs/product-images.md` is binding. Prefer an official photo over PTT
for the same product. On top of it, reject a photo when:
- the product is not the main subject (small, in the background, cut off);
- only the back, nutrition panel or barcode side shows;
- the flavour or variant on the package does not match the product name;
- the article covers several products and the photo cannot tell which one;
- it shows something other than this product.
A label is not required (owner decision 2026-11-18). Soft-serve, cup drinks
and fresh food often have none. Accept an unlabelled item when the article is
about this one product and the photo shows the item itself.
When unsure, leave it out.
</task>

<scope_constraints>
- May change: `data/labels/product_images.csv`, and `web/public/data.json`
  only via `cd web && npm run build:data`.
- Working files go in `.codex-work/` (untracked; never commit it).
- No code, test, docs or other CSV changes. Do not commit or push.
</scope_constraints>

<acceptance_criteria>
- Each new row: identity_status and rights_status `verified`, enabled `1`,
  checked_at = today, correct `rotate`, HTTPS URLs. Official rows use
  source_kind `official_retailer` and keep official_id as text (leading zeros).
- `.codex-work/decisions.csv` lists every enabled row with the reason it matches;
  `.codex-work/uncertain.csv` lists skipped candidates with the reason.
- After writing, re-open every enabled photo once more and drop any that break
  a rule above.
- Pass from repo root: `python3 -m pytest -q tests/test_product_images.py`,
  `cd web && npm run build:data && npm test && npx tsc --noEmit`.
</acceptance_criteria>

<default_follow_through_policy>
Keep going until the acceptance criteria are met; only stop when a missing
detail would change correctness.
</default_follow_through_policy>

<compact_output_contract>
Under 200 words: image-less count before/after, new rows by source kind,
candidates skipped, checks run with pass/fail.
</compact_output_contract>
