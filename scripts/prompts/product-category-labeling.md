<task>
Assign a category to each convenience-store product in ONE CSV:
`product_category_work/chunks/__CHUNK__.csv` (__N__ data rows). Write your
answers to `product_category_work/chunks/__CHUNK__.labeled.csv`.

Each row is one product the pipeline scored. Your job: pick the single category
a Taiwanese shopper would look under to find it.

Judge each row YOURSELF by reading it. Do NOT write a regex/heuristic script —
a keyword whitelist is exactly what this cache exists to replace, and it is what
dumped 125 products into 其他 in the first place.
</task>

<how_to_fill_each_row>
Keep every column and the same header, rows in the SAME order, and keep
`fingerprint`, `brand`, `product_name`, `rule_guess`, `prompt_version`
UNCHANGED. `rule_guess` is what the old keyword engine produced — informational
only, frequently 其他, and never a reason to answer 其他 yourself.

Fill in:
- `category`: exactly one of 便當 鹹食 泡麵 麵包 甜點 冰品 飲料 乳品 零食 周邊 其他
- `model`: set to `codex`.
</how_to_fill_each_row>

<categories>
便當 — a meal. Rice dishes (便當, 飯糰, 丼, 炒飯, 燴飯, 粽, 米糕, 咖哩飯),
  noodle and 粉 mains that are not instant noodles (義大利麵, 拌麵, 涼麵,
  牛肉麵, 河粉, 炊粉), hot pots and stews (部隊鍋, 壽喜燒, 薑母鴨), soups and
  congee (雞湯, 味噌湯, 廣東粥), salad and protein meal boxes (沙拉, 蛋白餐,
  匠食盒).
鹹食 — a savoury single item, not a meal. Counter hot food (關東煮, 雞塊,
  雞排, 大亨堡, 熱狗), dumplings and buns (水餃, 煎餃, 湯包, 肉包, 燒賣),
  eggs and small plates (茶葉蛋, 溏心蛋, 甜不辣, 毛豆, 玉米杯, 滷味, 雞翅,
  雞丁, 豬肝). The test against 便當 is whether it is sold as a whole meal.
泡麵 — instant noodles you add water to (杯麵, 碗麵, 泡麵包裝, 來一客, 滿漢).
  A ready-to-eat noodle bowl from the chiller is 便當, not 泡麵.
麵包 — bread and sandwiches (麵包, 吐司, 貝果, 可頌, 丹麥, 三明治, 餐包).
甜點 — sweet food that is not frozen and not bread (蛋糕, 布丁, 泡芙, 麻糬,
  大福, 布朗尼, 銅鑼燒, 鬆餅, 果凍, 愛玉, 豆花, 燒仙草, 芝麻糊).
冰品 — frozen (霜淇淋, 冰淇淋, 雪糕, 冰棒, 冰沙, 聖代, 剉冰, 雪淋霜).
飲料 — anything drunk that is not primarily milk (茶, 咖啡, 拿鐵, 奶茶,
  果汁, 汽水, 機能飲, 豆漿, 椰子水, 米漿) INCLUDING alcohol (啤酒, 拉格,
  調酒, highball, 梅酒).
乳品 — dairy as the product itself (鮮乳, 保久乳, 優格, 優酪乳, 起司, 乳酪).
  A milk tea or a latte is 飲料; plain 鮮奶 is 乳品.
零食 — packaged snacks (洋芋片, 餅乾, 糖果, 巧克力, 米果, 肉乾, 堅果,
  果乾, 魷魚絲, 脆片).
周邊 — not food. Collectables and goods (福袋, 公仔, 一番賞, 吊飾, 鑰匙圈,
  杯墊, 托特包, 造型包, 毯, 玩具, 文具, 鍋具, 安全帽, 寵物用品).
其他 — LAST RESORT, for things none of the above fits: raw ingredients and
  groceries (生鮮雞蛋, 水果, 地瓜), condiments (辣椒醬, 鵝油), household items.
  If you are hesitating between two real categories, pick the better one; 其他
  is not the safe answer, it is the answer that made this layer necessary.
</categories>

<judgement_notes>
- A product name that names a shop or a licence (茶湯會翡翠檸檬, 屋馬枸杞雞湯,
  台鋼雄鷹TAKAO孔雀香酥脆香魚) still describes a product — categorise the
  product, not the brand.
- 造型/聯名 goods borrow food words (夯地瓜造型包, 咖波福袋). If it is an object
  you keep rather than eat, it is 周邊.
- CITYCAFE 中熱美 is a coffee (飲料); 每日C is juice (飲料); 純萃喝 is coffee
  (飲料). Chain shorthand counts as a name.
- Judge the product, not the eating occasion: 炸雞桶 is 鹹食 even if somebody
  eats it as dinner.
</judgement_notes>

<verification>
Before you finish, re-open your `.labeled.csv` and check:
1. Row count and row order match the input exactly.
2. Every `fingerprint` from the input is present, none added.
3. Every `category` is one of the eleven listed above, spelled exactly.
4. `其他` appears only where you can say what it is that fits nothing.
Report the row count and the 其他 count in your final message.
</verification>
