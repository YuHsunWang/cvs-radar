<task>
Read the speech-to-text transcript of ONE Taiwanese YouTube video in which the
creator tries convenience-store products: `__ID__.transcript.txt` (one line per
segment, `m:ss text`). Video details are in `__ID__.meta.json`.

Write `__ID__.extract.json`: a JSON array with one object per product the
creator actually tasted AND gave a verdict on. Read the whole transcript
yourself; do not write a script to do it.
</task>

<fields>
- `brand`: one of "7-11", "全家", "萊爾富", "OK". 小七/711 → "7-11". Skip
  products from any other shop (supermarkets, Japanese stores, chain
  restaurants) and skip a product whose shop you cannot tell.
- `product_name`: the name printed on the package as best you can tell. The
  transcript is machine speech recognition and mishears names
  (賣味噌→麥味噌, 卵歐→軟歐, 東洋貢→冬蔭功, 勢力價→士力架, 夏慕妮→夏慕尼). Fix
  obvious mishearings using the title, the description and the candidate list.
  No price, no brand prefix, at most 30 characters.
- `product_id`: if the same product is in `candidates.txt` (one `brand::name`
  per line, the products the site already lists), copy that line exactly.
  Only when you are sure it is the same item, not just a similar one.
  Otherwise "".
- `category`: one of 便當 鹹食 泡麵 麵包 甜點 冰品 飲料 乳品 零食 周邊 其他.
- `price`: only when the creator clearly states this one item's price in NT$
  (「一個是49元」「75塊」), as a string of digits. Leave "" when it is unclear,
  garbled, a total for several items, or you would have to guess a digit.
- `creator_score`: only when the creator states a score out of something,
  written like "9/10", "6.5/10", "4/5". A creator who scores every product
  with a bare 「N分」 (never above 10) and never names the scale is using a
  10-point scale: write "N/10". Else "". Never invent one.
- `start_seconds`: the second (integer) where the creator starts talking about
  this product, taken from the line timestamps.
- `summary`: the creator's verdict in YOUR words, Traditional Chinese, at most
  40 characters, e.g. 「巧克力味滿滿，脆絲加分、不會太甜」. Say what they
  liked or disliked; keep their direction (good / so-so / bad) exactly.
</fields>

<skip>
- Sponsored segments (supplements, apps, anything not a store product).
- Jokes, sarcasm or banter where the real verdict is unclear — leave the
  product out rather than guess.
- Products only mentioned, not tasted.
</skip>

Write `[]` if nothing qualifies. Write only that file.
