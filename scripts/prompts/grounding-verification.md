<task>
Judge whether each rewrite is faithful to the source text it cites, in ONE CSV:
`grounding_work/chunks/__CHUNK__.csv` (__N__ data rows). Write your answers to
`grounding_work/chunks/__CHUNK__.labeled.csv`.

These rows all failed a mechanical character-overlap screen. That screen cannot
tell a good Chinese paraphrase from an invention, because a faithful rewrite often
shares no characters with its source (「太貴了」 → 「價格偏高」). You are the
adjudicator it cannot be. Read each pair and decide.
</task>

<how_to_fill_each_row>
Keep every column and the same header, rows in the SAME order, and keep
`fingerprint`, `product_name`, `field`, `rewrite`, `source_text` UNCHANGED.
Fill in `verdict` and set `model` to `codex`.

`verdict` is exactly one of:

- `grounded` — every claim in `rewrite` is stated or directly implied by
  `source_text`. Synonym substitution is fine and expected: 「太貴了」→「價格偏高」,
  「有夠柴」→「雞胸肉很柴」, 「超小顆」→「份量太小」, 「我無法」→「不太能接受」.
  Naming the product or its obvious part is fine when the source is clearly about
  it (「太醜了吧」→「企鵝造型很醜」 for a penguin charm). Tightening rambling
  wording into a clean phrase is the whole point — do not punish it.
- `ungrounded` — `rewrite` asserts something the source does not support. This
  includes: a fact absent from the source (source says 「吃起來不會膩」, rewrite says
  「每層都有奶油」); a different topic entirely (source says 「這熱門程度可以等特價」,
  rewrite says 「茶包式咖啡方便冷泡」); a claim built from the product name rather
  than the review; or a rewrite that is mostly faithful but bolts on one extra
  unsupported detail (source says 「都擠很小」, rewrite says 「偏小，還會滴水」 —
  「滴水」 is not there, so the whole rewrite is `ungrounded`).

The test is simple: could a reader who saw only `source_text` have written
`rewrite` without adding knowledge of their own? If yes, `grounded`.

When genuinely torn, answer `ungrounded`. A dropped rewrite costs one line of
detail; a kept invention is a false claim about a real product.
</how_to_fill_each_row>

<acceptance_criteria>
- `grounding_work/chunks/__CHUNK__.labeled.csv` exists, UTF-8 BOM, same header.
- Exactly __N__ rows, same order, SAME fingerprints; none dropped or added.
- Every `verdict` is exactly `grounded` or `ungrounded` — never blank, never
  anything else.
- `rewrite` and `source_text` are byte-identical to the input.
</acceptance_criteria>

<scope_constraints>
Only create the labeled CSV. Do not modify anything under cvs_radar/, scripts/,
tests/, data/, or web/. Do not git add or commit.
</scope_constraints>

<default_follow_through_policy>
Judge all __N__ rows yourself by reading them. Do not write a scoring script —
a mechanical rule is exactly what this step replaces.
</default_follow_through_policy>

<compact_output_contract>
Under 300 words: how many grounded / ungrounded, and 3-5 examples where the call
was difficult, with one line of reasoning each. No CSV dump.
</compact_output_contract>
