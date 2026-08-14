<task>
Review every product row in `comment_pick_work/chunks/__CHUNK__.csv` (__N__ rows).
Write the completed answers to the same directory as
`comment_pick_work/chunks/__CHUNK__.labeled.csv`.

The model, not a keyword or sentiment rule, decides whether a comment is a
product review and whether it is positive or negative. The CSV contains one
polarity-neutral pool of comments and one pool of author-review sentences.
</task>

<how_to_fill_each_row>
Keep the header, every source column, and the exact row order. Keep these columns
byte-for-byte unchanged: `fingerprint`, `brand`, `product_name`,
`other_products`, `comments`, `body_candidates`, and `prompt_version`.

Fill each of these four columns with a JSON array:
`positive_rewrites`, `negative_rewrites`, `positive_body_rewrites`, and
`negative_body_rewrites`.

Each array item must be exactly an object with this shape:
`{"source_index": 0, "text": "短短的繁體中文改寫"}`.
`source_index` is the number before the period in the matching candidate pool.
Use at most 3 items per array, keep the order that is most useful to shoppers,
and use `[]` when there is no defensible item. Set `model` to `codex`.
Assign a source item to at most one polarity within its pool; do not repeat the
same source index in both a positive and a negative array.
Do not alter a candidate pool to make an answer fit. Do not use Markdown fences.
Before writing each item, check that its index is present in the matching pool and
that every concrete fact in its rewrite is supported by that cited source. If a
rewrite condenses multiple source items, cite every supporting index; never cite a
nearby but unrelated index.
</how_to_fill_each_row>

<judgement>
Read `product_name` and `other_products` before judging. `other_products` names
products reviewed in the same thread; do not attribute their comments or body
sentences to this product. The product name and context determine the category.

Select an item only when it is genuinely about this product and communicates a
useful product experience. Rewrite it into concise Traditional Chinese, no more
than 30 characters per item:

- remove filler, scene-setting, URLs, and empty enthusiasm;
- keep concrete attributes and caveats, including a negative point;
- never add a fact, number, comparison, or usage claim not present in the source;
- never merge two different products into one item;
- prefer 「內餡奶酥好吃」 over 「超好吃推推」.

Select for aspect coverage, not just for the three individually strongest comments:

- Within each polarity, treat an aspect as one shopper-relevant dimension. For
  food this can be flavour, texture, portion, price/value, aftertaste, serving or
  preparation, ingredients/additives, batch consistency, or repurchase intent.
  For non-food it can be appearance, build quality, size/fit, usefulness,
  durability, ease of use, or value. Use other category-specific dimensions when
  the source makes them concrete.
- Choose up to 3 items whose useful points cover different aspects, so the set
  tells a shopper different things. Do not count a rewording, a stronger/weaker
  version, or another example of the same aspect as new coverage. A genuine
  disagreement about one aspect can be more useful than a third restatement of
  the majority view, so a clear contrary observation may earn a slot when it adds
  actionable information. Keep disputed observations source-specific (for
  example, 「有留言覺得像杏仁茶」) and never present one comment as consensus.
- If candidates tie on aspect coverage, prefer the more concrete and checkable
  wording: a named flavour, texture, size, ingredient, price, visible feature,
  or reproducible behaviour beats vague praise or criticism.
- Stop with fewer than 3 when the remaining defensible items repeat an aspect or
  are too weak/vague. Do not pad a set merely to reach the cap.

Do not use a fixed food-only rejection list. For food, taste, texture, portion,
price, spice, repurchase, and preparation details can be concrete. For 吊飾、周
邊、生活用品、飲料、雜貨, words such as 「可愛」「質感好」「做工細」「實用」
and 「CP 值高」 are concrete category attributes and may be valid even when
there is no taste or texture detail. Reject only praise that is empty relative
to this product's category.

The same model judgement assigns polarity. A comment does not need a positive or
negative lexicon hit to reach the pool. A body rewrite is a fallback for that
polarity when the comment rewrites cannot fill it; it must still be clearly about
this product.
</judgement>

<rewrite_examples>
Source: 「這一款,其實蠻好吃的,只是菠蘿皮是軟菠蘿,內餡的奶酥,很好吃我一星期會買一次來吃」
Rewrite: 「菠蘿皮偏軟，內餡奶酥好吃」

Source: 「舒跑款可愛」 for a 吊飾
Rewrite: 「舒跑款可愛」

Source: 「超好吃推推」 for a food item with no reason
Rewrite: reject (`[]`)
</rewrite_examples>

<acceptance_criteria>
- `__CHUNK__.labeled.csv` exists as UTF-8 BOM with exactly __N__ rows.
- Same header, fingerprints, source columns, and row order as the input.
- Every cited index exists in that row's matching pool.
- A rewrite and its source index are both present or both absent; no URLs,
  controls, width-garbage, or over-30-character rewrite.
</acceptance_criteria>

<scope_constraints>
Only create the labeled CSV. Do not modify cvs_radar/, scripts/, tests/, data/,
web/, or .github/. Do not git add or commit.
</scope_constraints>

<default_follow_through_policy>
Label all __N__ rows. Do not sample or leave a row structurally incomplete.
</default_follow_through_policy>
