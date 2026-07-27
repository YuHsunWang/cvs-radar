<task>
Choose the review excerpt shown to shoppers for each (post, product) pair in ONE
CSV: `excerpt_work/chunks/__CHUNK__.csv` (__N__ data rows). Write your answers to
`excerpt_work/chunks/__CHUNK__.labeled.csv`.

Each row is one product plus the body of the PTT post reviewing it. Pick the
sentences from `review_text` that would actually help someone decide whether to
buy `product_name`.

Judge each row YOURSELF by reading it. Do NOT write a keyword-scoring script —
keyword scoring is exactly what this cache replaces.
</task>

<how_to_fill_each_row>
Keep every column and the same header, rows in the SAME order, and keep
`fingerprint`, `post_id`, `brand`, `product_name`, `other_products`,
`review_text` UNCHANGED. Fill in `excerpt`, and set `model` to `codex`.

`excerpt` rules:
- Quote the author VERBATIM. You may drop words inside a sentence and join
  sentences with 「，」 or 「。」, but do not paraphrase, translate, or invent.
- At most 3 sentences and at most 90 characters total. Shorter is fine.
- Prefer concrete, checkable description: taste, texture, filling/ingredients,
  portion, heat/spice level, sweetness, price-worth, how it compares with a
  similar item, and any caveat worth knowing (熱量高, 份量少, 偏鹹, 要加熱).
- REJECT contentless praise as the whole excerpt: 「超級好吃」「我很愛」「看起來很好吃」
  「推推」 say nothing. A verdict IS allowed when it carries a reason or a
  condition (「喜歡吃辣的這個很推」「有優惠再買」「不會回購」).
- REJECT scene-setting and logistics: 「今天路過全家」「圖多多版本」「先上圖」, store
  availability, coupon mechanics, shipping, and anything with a URL.
- **`other_products` lists the OTHER products reviewed in this same post. Sentences
  about those belong to them, not here — never let them into this excerpt.** If a
  sentence compares this product with one of them, keep it only if it tells you
  something about THIS product.
- If the post genuinely says nothing usable about this product (it only mentions
  buying it, or all the description belongs to another product), leave `excerpt`
  EMPTY. An empty answer is a real verdict and is recorded as such — do not pad.
</how_to_fill_each_row>

<acceptance_criteria>
- `excerpt_work/chunks/__CHUNK__.labeled.csv` exists, UTF-8 BOM, same header.
- Exactly __N__ rows, same order, SAME fingerprints; none dropped or added.
- Every non-empty `excerpt` appears in `review_text` as the author's own wording
  (allowing dropped words and joined sentences), is <= 90 characters, and contains
  no URL.
- No excerpt describes a product named in that row's `other_products`.
</acceptance_criteria>

<scope_constraints>
Only create the labeled CSV. Do not modify anything under cvs_radar/, scripts/,
tests/, data/, web/, or .github/. Do not git add or commit.
</scope_constraints>

<default_follow_through_policy>
Label all __N__ rows. Do not sample.
</default_follow_through_policy>

<compact_output_contract>
Under 300 words: rows in/out, how many you left empty, how many times you excluded
a sentence because it belonged to another product, and 3-5 examples where the
choice was difficult. No CSV dump.
</compact_output_contract>
