<task>
Choose the representative comments shown to shoppers for each product in ONE CSV:
`comment_pick_work/chunks/__CHUNK__.csv` (__N__ data rows). Write your answers to
`comment_pick_work/chunks/__CHUNK__.labeled.csv`.

Each row is one product with ranked positive and negative comment candidates. Pick
the comments that would actually help someone decide whether to buy `product_name`.
</task>

<how_to_fill_each_row>
Keep every column and the same header, rows in the SAME order, and keep
`fingerprint`, `brand`, `product_name`, `positive_candidates`, and
`negative_candidates`, and `body_candidates` UNCHANGED. Fill `positive_picks`,
`negative_picks`, `positive_body_picks`, and `negative_body_picks` with pipe-joined
candidate indices (for example `0|3`), and set `model` to `codex`.

- Pick at most 3 indices per polarity. Fewer than 3 — including none — is correct
  whenever the pool has nothing better. Do not pad with contentless praise.
- Prefer comments that say something concrete about the product: taste, texture,
  portion, price, or repurchase intent.
- Reject contentless verdicts such as 「好吃」「我很愛」「推」.
- Reject speculation by someone who has not eaten it, such as 「看起來很好吃」,
  「有機會來買」, or 「想吃吃看」.
- Reject comments about a different product.
- A blank pick cell is a real verdict: it means no candidate in that polarity is
  worth showing. If both polarities are blank, still set `model` to `codex`.
</how_to_fill_each_row>

<body_candidates>
`body_candidates` are author-review sentences used only when the comments could
not fill a polarity.

READ `other_products` FIRST. It lists the other products reviewed in the same
threads, and the body candidates are drawn from those whole posts — so sentences
about those products ARE in the list. Pick a body sentence only when it is
unambiguously about the row's `product_name`. Reject a sentence about a listed
thread-mate, or a comparison whose subject is another product, even if it is well
written. When `other_products` is non-empty, assume contamination is present and
check each sentence against that list before picking it.

Picking nothing is correct when no sentence clearly belongs to this product.
Never put the same body index in both body-pick columns.
</body_candidates>

<acceptance_criteria>
- `comment_pick_work/chunks/__CHUNK__.labeled.csv` exists, UTF-8 BOM, same header.
- Exactly __N__ rows, same order, SAME fingerprints; none dropped or added.
- Each pick is an existing index from that row's matching candidate cell; there are
  no duplicate indices and no more than 3 picks in either polarity.
- Every chosen comment is concrete, first-hand where relevant, and about the row's
  `product_name`; no contentless praise was used as padding.
</acceptance_criteria>

<scope_constraints>
Only create the labeled CSV. Do not modify anything under cvs_radar/, scripts/,
tests/, data/, web/, or .github/. Do not git add or commit.
</scope_constraints>

<default_follow_through_policy>
Label all __N__ rows. Do not sample.
</default_follow_through_policy>
