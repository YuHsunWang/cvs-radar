# CVS Radar Shopper UI Redesign

## Mockup

- Generated with the built-in imagegen tool.
- Saved mockup: `docs/redesign/app_mockup.png`

## Design Direction

The redesign uses a clean shopper dashboard layout: a compact warm-white header, a bordered filter band, a context summary strip, and a two-column main area with the candidate product shelf on the left and the selected product decision card on the right.

The color system is warm neutral with trustworthy teal as the primary action color, green for positive consensus, amber for mixed or volume signals, and coral red for negative risk. Typography is dense but readable, with dark navy text and muted slate helper copy.

Brand-logo chips stay small, rounded, and color-coded for 7-11, 全家, 萊爾富, OK, 美聯社, and 其他. Consensus and volume signals are styled as badges with mini segmented bars so shoppers can scan score, agreement, and discussion volume without reading every detail.

## Mobile v2

- Generated with the built-in imagegen tool.
- Saved mockup: `docs/redesign/app_mockup_mobile_v2.png`

Mobile v2 reframes the shopper app as a phone-first, single-column screen. The desktop sidebar becomes a large thumb-reachable `調整篩選` control with brand chips for `7-11`, `全家`, `萊爾富`, `OK`, `美聯社`, and `其他` visible as a compact filter preview. A sticky compact header keeps `CVS Radar` and the current search context available, while ranked product cards surface `綜合分數`, `共識`, and `聲量` immediately.

Product imagery is intentionally optional. Because the data does not include a reliable per-product photo or thumbnail field, each item uses a branded placeholder tile: brand/category color, a category glyph such as `飯`, `麵`, `飲`, or `甜`, and a product-name initial. A future implementation could opportunistically try the first user-posted image URL from a matched post in `data/posts.jsonl`, but it should treat that image as best-effort only and keep the placeholder as the default fallback so the layout never depends on hotlinked or unreliable photos.

The usability emphasis is scan-first decision making on a phone. Product cards use large tap targets, a bold score block, consensus and volume badges, price/category/date chips, and an `展開詳情` affordance for progressive disclosure. The selected `單品判斷` card keeps the buy/no-buy recommendation, `大家喜歡的點`, and `需要留意的點` close together, with `查看心得` as the obvious primary action in the thumb zone.

## Mobile v3

- Generated with the built-in imagegen tool.
- Saved mockup: `docs/redesign/app_mockup_mobile_v3.png`

Mobile v3 keeps the same phone-first list, compact sticky header, `調整篩選` drawer entry, brand chips, branded placeholder tiles, and scan-first score badges from v2, but changes the product detail interaction to an inline accordion. Tapping a product row expands that row's own `單品判斷` panel directly beneath it, pushing the next ranked products down instead of sending the detail to a separate section.

The mockup shows product #1 expanded between row #1 and row #2. Its row header remains visible with the open/收合 affordance, and the inline detail card contains the large `綜合分數`, `共識` distribution, `聲量` indicator, `大家喜歡的點`, `需要留意的點`, and `查看心得` action. Rows #2 and below remain collapsed with their `展開` affordance, making the accordion behavior explicit.
