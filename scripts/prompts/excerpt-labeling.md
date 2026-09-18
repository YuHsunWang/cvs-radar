<task>
Review every (post, product) row in `excerpt_work/chunks/__CHUNK__.csv`
(__N__ rows). Write the completed answers to
`excerpt_work/chunks/__CHUNK__.labeled.csv`.

The model decides what counts as a product review. The source pool is supplied
as numbered, mechanically cleaned author sentences; it is not pre-filtered by
food keywords or sentiment.
</task>

<how_to_fill_each_row>
Keep the header, every source column, and exact row order. Keep these columns
byte-for-byte unchanged: `fingerprint`, `post_id`, `brand`, `product_name`,
`other_products`, `review_text`, `body_candidates`, and `prompt_version`.

Fill `source_indices` with at most 3 cited candidate numbers joined by `|` (for
example `0|3`) and fill `rewrite` with one concise Traditional-Chinese summary.
The rewrite is a model-written condensation, not a quote. Set `model` to
`codex`. If the post has no useful review of this product, leave both
`source_indices` and `rewrite` empty, but still set `model` to `codex`.
Before writing the summary, check that each cited index exists in the printed pool
and that every concrete fact in the summary is supported by one of those cited
sentences. Never cite a nearby but unrelated index.
</how_to_fill_each_row>

<rewrite_rules>
- Traditional Chinese, no more than 30 characters for this item.
- Drop filler, scene-setting, logistics, quoted headers, and URLs.
- Keep concrete attributes and any caveat worth knowing.
- Never add a fact, number, product, comparison, or usage claim not in the
  cited source.
- Never merge two different products into one item. Read `other_products` first;
  the shared post body can contain sentences belonging to those products.
- Category comes from `product_name` and context. Food may mention taste,
  texture, portion, spice, price, repurchase, or preparation. For 吊飾、周邊、
  生活用品、飲料、雜貨, 「可愛」「質感好」「做工細」「實用」「CP 值高」
  are concrete attributes and must not be rejected merely because they are not
  food descriptors. Reject emptiness relative to the category, not a fixed
  word list.
</rewrite_rules>

<example>
Source: 「這一款,其實蠻好吃的,只是菠蘿皮是軟菠蘿,內餡的奶酥,很好吃我一星期會買一次來吃」
Rewrite: 「菠蘿皮偏軟，內餡奶酥好吃」

Source: 「飲料小夥伴超萌逗趣的模樣」 for a 吊飾
Rewrite: 「造型超萌逗趣」
</example>

<acceptance_criteria>
- `__CHUNK__.labeled.csv` exists as UTF-8 BOM with exactly __N__ rows.
- Same header, fingerprints, source columns, and row order as the input.
- `source_indices` is empty exactly when `rewrite` is empty, otherwise every
  index exists in that row's `body_candidates` and there are no more than 3.
- No URL, controls, width-garbage, or rewrite over 30 characters.
</acceptance_criteria>

<scope_constraints>
Only create the labeled CSV. Do not modify cvs_radar/, scripts/, tests/, data/,
web/, or .github/. Do not git add or commit.
</scope_constraints>

<default_follow_through_policy>
Label all __N__ rows. Do not sample or leave a row structurally incomplete.
</default_follow_through_policy>
