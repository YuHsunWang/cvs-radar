<task>
Label the raw 商品名稱 fields of PTT convenience-store review posts in ONE CSV:
`product_name_work/chunks/__CHUNK__.csv` (__N__ data rows). Write your answers to
`product_name_work/chunks/__CHUNK__.labeled.csv`.

Each row is one post's raw product field. Your job: decide what product(s) the
poster actually reviewed, and at what unit price.

Judge each row YOURSELF by reading it. Do NOT write a regex/heuristic script —
rules are exactly what this cache exists to replace.
</task>

<how_to_fill_each_row>
Keep every column and the same header, rows in the SAME order, and keep
`fingerprint`, `brand`, `raw_name`, `post_title`, `rule_guess` UNCHANGED.
`rule_guess` is what the old rule engine produced, in `name#price` form — it is a
hint only and is often wrong; correct it.

Fill in:
- `product_name`: the product's name as a shopper would say it. Strip prices,
  coupon/discount wording (酷碰價, 友善時光, 嚐鮮價, 第二件, N折, 加購價), gift and
  threshold clauses (消費滿200免費送, 買一送一), payment notes (icash付款), store
  or availability notes (限店, i珍食), quantity/pack sizes, and the poster's own
  asides (「一起結帳不確定價格」,「價格忘記」). KEEP brand/sub-brand and flavour
  words that are genuinely part of the name (牧場直送4.0巧克力牛奶雪糕,
  光泉午后時光紅茶, Seasons法式香草烤雞翅). Do not invent words that are not
  supported by raw_name or post_title.
- `price`: the unit price the poster paid, as a plain integer, or blank if the
  field states none. For "原價79元、優惠價48元" use the price actually paid (48).
  For a bundle ("2支55") give the per-unit price (28) only if that is clearly the
  intent, otherwise leave blank. Ignore prices that belong to a gift or threshold.
- `model`: set to `codex`.

MULTI-PRODUCT ROWS: when the field really covers several distinct products
(「抹茶霜淇淋55/抹茶千層59」), emit ONE ROW PER PRODUCT: copy the row, keep the same
`fingerprint`, and set `item_index` to 0, 1, 2 … in the order they appear. A
combo where the second item is just a bundle partner or comparison
(「翻轉布丁3入+統一布丁3入/75元」) is ONE product — the first one.

NO USABLE NAME: when the field carries only a price or promo text (「55元 甜點兩件
六九折」, 「49」) and the real name is only in `post_title`, take the name from
`post_title` (drop its 「[商品] 品牌」 prefix). Only if neither gives a usable
product name, leave `product_name` blank — that blank is a real verdict and is
stored as such.
</how_to_fill_each_row>

<acceptance_criteria>
- `product_name_work/chunks/__CHUNK__.labeled.csv` exists, UTF-8 BOM, same header.
- Every input row is represented; fingerprints match the input and none is dropped.
- `item_index` starts at 0 per fingerprint and increments with no gaps.
- `price` is blank or a plain integer (no 元, no decimals, no ranges).
- `product_name` contains no price digits-with-元, no 折/券/贈/送 promo wording,
  and no full-width punctuation runs.
</acceptance_criteria>

<scope_constraints>
Only create the labeled CSV. Do not modify anything under cvs_radar/, scripts/,
tests/, data/, web/, or .github/. Do not git add or commit.
</scope_constraints>

<default_follow_through_policy>
Label all __N__ rows. Do not sample. Only stop if the instructions are genuinely
contradictory.
</default_follow_through_policy>

<compact_output_contract>
Under 300 words: row counts in/out, how many multi-product rows you split, how many
you left blank, 3-5 rows where you disagreed with rule_guess and why. No CSV dump.
</compact_output_contract>
