from __future__ import annotations

from __future__ import annotations
import re
import unicodedata
from collections import defaultdict
from difflib import SequenceMatcher
from ..config import (
    BRANDS,
    PRODUCT_ALIASES,
    PRODUCT_CATEGORIES,
    PRODUCT_NORMALIZATION,
)
from ..models import Comment, Post
from ..parser import _title_product_name

from ._common import (_BRACKET_RE, _BUNDLE_PRICE_RE, _BUNDLE_PRICE_SUFFIX_RE, _CATEGORY_STRONG_KEYWORDS, _DISTINCTIVE_TERMS, _FRAGMENT_PRODUCT_NAMES, _GARBAGE_NAME_RE, _GENERIC_CATEGORY_KEYWORDS, _MAX_PRICE, _MIN_PRICE, _MULTI_PRODUCT_RE, _NOISE_RE, _OPTIONAL_RE, _PARALLEL_PRODUCT_SUFFIXES, _PAYMENT_ASIDE_PATTERN, _PRICE_BEFORE_PROMO_RE, _PRICE_CONTEXT_RE, _PRICE_TOKEN_RE, _PRODUCT_FORM_TERMS, _PRODUCT_REVIEW_START_RE, _PROMO_RE, _PROMO_SUFFIX_RE, _PROMO_TAIL_RE, _PTT_PRODUCT_TEMPLATE, _QUANTITY_SUFFIX_RE, _SHARED_FLAVOR_RE, _SHARED_SAME_PRICE_RE, _SYNONYM_MAP, _TITLE_PREFIX_RE, _TRAILING_FILLER_RE, _TRAILING_NOISE_CLEAN_RE, _TRAILING_PRICE_CLEAN_RE, _TRAILING_PRICE_RE, _URL_RE)


def _extract_space_separated_parallel_products(
    text: str, brand: str = ""
) -> list[tuple[str, int | None]] | None:
    """Split a space-separated parallel product listing into one item per name.

    Only fires when every space-separated segment cleanly reduces to a product
    name AND at least two of them end with a distinctive product-type suffix,
    so ordinary single names that merely contain a space are left intact.
    """
    t = unicodedata.normalize("NFKC", text or "").strip()
    t = re.sub(r"^[：:]+\s*", "", t)
    segments = [seg for seg in re.split(r"\s+", t) if seg]
    if len(segments) < 2:
        return None
    named: list[tuple[str, int | None]] = []
    for seg in segments:
        parsed = _extract_products_and_prices_from_text(seg, brand)
        if not parsed or not parsed[0][0]:
            return None
        named.append((parsed[0][0], parsed[0][1]))
    suffixed = [
        name
        for name, _ in named
        if any(name.endswith(sfx) for sfx in _PARALLEL_PRODUCT_SUFFIXES)
    ]
    if len(suffixed) >= 2 and len(suffixed) == len(named):
        return named
    return None


def extract_products_and_prices(raw_name: str, brand: str = "") -> list[tuple[str, int | None]]:
    """Split a raw product name into (name, price) pairs.

    Handles single products with trailing prices ("BF薄荷岩鹽檸檬糖35")
    and multi-product titles ("抹茶霜淇淋兩支55抹茶千層59").
    """
    raw = unicodedata.normalize("NFKC", raw_name or "").strip()
    raw = re.sub(r"^[：:]+\s*", "", raw)
    lines = _candidate_product_lines(raw)
    if lines:
        parallel = _extract_space_separated_parallel_products(lines[0], brand)
        if parallel:
            return parallel
    if len(lines) > 1:
        results = _extract_multiline_products(lines, brand)
        if results:
            return results
        return _extract_first_line_with_price_anywhere(lines, brand)
    if lines:
        return _extract_products_and_prices_from_text(lines[0], brand)
    return _extract_products_and_prices_from_text("", brand)


def _candidate_product_lines(raw_name: str) -> list[str]:
    lines = []
    for line in raw_name.splitlines():
        line = line.strip()
        if not line:
            continue
        if _PRODUCT_REVIEW_START_RE.match(line):
            break
        if line == _PTT_PRODUCT_TEMPLATE:
            continue
        if _URL_RE.search(line):
            continue
        lines.append(line)
    return lines


def _reply_product_extraction_text(raw_name: str) -> str:
    lines: list[str] = []
    for line in (raw_name or "").splitlines():
        marker = re.sub(r"^[：:]\s*", "", line.strip()).strip()
        if marker == "--":
            return "\n".join(lines).strip()
        lines.append(line)
    return raw_name


def _extract_multiline_products(lines: list[str], brand: str) -> list[tuple[str, int | None]]:
    same_price = _extract_slash_same_price_products(
        _normalize_product_pattern_text(" ".join(lines), brand)
    )
    if same_price:
        return same_price

    results: list[tuple[str, int | None]] = []
    pending_name: str | None = None

    for line in lines:
        if _is_price_context_line(line):
            price = _best_price_from_text(line)
            if pending_name and price is not None:
                results.append((pending_name, price))
                pending_name = None
            continue

        split_results = _extract_multiple_price_segments(line, brand)
        if len(split_results) >= 2:
            results.extend(split_results)
            pending_name = None
            continue

        parsed = _extract_products_and_prices_from_text(line, brand)
        priced = [(name, price) for name, price in parsed if name and price is not None]
        if priced:
            results.extend(priced)
            pending_name = None
            continue
        if parsed and parsed[0][0]:
            pending_name = parsed[0][0]

    return results


def _extract_first_line_with_price_anywhere(lines: list[str], brand: str) -> list[tuple[str, int | None]]:
    """Fallback when line-by-line splitting finds no product: treat the first
    line as the product name and only scan the remaining lines for a price,
    instead of joining every line into one string and re-parsing it (which
    can leak stray characters from unrelated promo/quantity lines into the
    name, e.g. '橘貓款冰棒襪套' + '3支冰+19元加購...' -> '橘貓款冰棒襪套冰').
    """
    first_index = 0
    first: list[tuple[str, int | None]] = []
    for index, line in enumerate(lines):
        first = _extract_products_and_prices_from_text(line, brand)
        if first and first[0][0]:
            first_index = index
            break
    if not first or not first[0][0]:
        return _extract_products_and_prices_from_text(" ".join(lines), brand)
    name, price = first[0]
    if price is None:
        for line in lines[first_index + 1:]:
            found = _best_price_from_text(line)
            if found is not None:
                price = found
                break
            continuation = _name_continuation(line, brand)
            if continuation and continuation not in name:
                name = f"{name}{continuation}"
    return [(name, price)]


def _name_continuation(line: str, brand: str) -> str:
    text = unicodedata.normalize("NFKC", line or "").strip()
    text = re.sub(r"^[：:]+\s*", "", text)
    if not text or len(text) > 16:
        return ""
    if any(pattern.search(text) for pattern in (_URL_RE, _PRICE_TOKEN_RE, _PROMO_RE, _OPTIONAL_RE)):
        return ""
    if text == _PTT_PRODUCT_TEMPLATE:
        return ""
    parsed = _extract_products_and_prices_from_text(text, brand)
    if not parsed or parsed[0][1] is not None:
        return ""
    name = parsed[0][0]
    if len(name) < 2 or _is_price_label_name(name):
        return ""
    return name


def _extract_products_and_prices_from_text(raw_name: str, brand: str = "") -> list[tuple[str, int | None]]:
    """Extract product names and prices from one logical product-name text."""
    s = _normalize_product_pattern_text(raw_name, brand)

    same_price = _extract_slash_same_price_products(s)
    if same_price:
        return same_price

    shared_flavors = _extract_shared_prefix_flavors(s)
    if shared_flavors:
        return shared_flavors

    s = re.sub(r"(?<=[\u4e00-\u9fff])[xX×](?=[\u4e00-\u9fff])", " ", s)
    s = re.sub(r"[#:/／｜|,，.。!！?？~～\-_=+]+", " ", s)
    s = _TITLE_PREFIX_RE.sub(" ", s)
    s = _NOISE_RE.sub(" ", s)
    s = re.sub(r"\s+", "", s).strip()

    segmented = _extract_multiple_price_segments(s, brand)
    if len(segmented) >= 2 or (len(segmented) == 1 and _BUNDLE_PRICE_RE.search(s)):
        return segmented

    matches = list(_MULTI_PRODUCT_RE.finditer(s))
    valid = [(m.group(1), int(m.group(2))) for m in matches
             if _MIN_PRICE <= int(m.group(2)) <= _MAX_PRICE and len(m.group(1)) >= 2]

    if len(valid) >= 2:
        results = []
        for name, price in valid:
            name = _QUANTITY_SUFFIX_RE.sub("", name).strip()
            name = _PROMO_RE.sub("", name).strip()
            name = re.sub(r"半價$", "", name).strip()
            if len(name) >= 2:
                results.append((name, price))
        if len(results) >= 2:
            return results

    m = _TRAILING_PRICE_RE.match(s)
    if m:
        name = m.group(1).strip()
        price = int(m.group(2))
        if _MIN_PRICE <= price <= _MAX_PRICE and len(name) >= 2:
            name = _QUANTITY_SUFFIX_RE.sub("", name).strip()
            name = _OPTIONAL_RE.sub("", name).strip()
            name = _PROMO_RE.sub("", name).strip()
            name = _PROMO_TAIL_RE.sub("", name).strip()
            if len(name) >= 2:
                return [(name, price)]

    mp = _PRICE_BEFORE_PROMO_RE.match(s)
    if mp:
        name = mp.group(1).strip()
        price = int(mp.group(2))
        if _MIN_PRICE <= price <= _MAX_PRICE and len(name) >= 2:
            name = _QUANTITY_SUFFIX_RE.sub("", name).strip()
            name = _OPTIONAL_RE.sub("", name).strip()
            if len(name) >= 2:
                return [(name, price)]

    s_clean = _PROMO_RE.sub(" ", s)
    s_clean = re.sub(r"\s+", "", s_clean).strip()
    m2 = _TRAILING_PRICE_RE.match(s_clean)
    if m2:
        name = m2.group(1).strip()
        price = int(m2.group(2))
        if _MIN_PRICE <= price <= _MAX_PRICE and len(name) >= 2:
            name = _QUANTITY_SUFFIX_RE.sub("", name).strip()
            name = _OPTIONAL_RE.sub("", name).strip()
            if len(name) >= 2:
                return [(name, price)]

    cleaned = _PROMO_RE.sub(" ", s)
    cleaned = re.sub(r"\d{2,3}元?$", "", cleaned).strip()
    cleaned = re.sub(r"\s+", "", cleaned).strip()
    if not cleaned:
        cleaned = re.sub(r"\s+", "", s).strip()
    return [(cleaned, None)]


def _extract_slash_same_price_products(s: str) -> list[tuple[str, int | None]] | None:
    """Handle 'A/B都N元' or 'A、B/各N元' style shared trailing prices."""
    match = _SHARED_SAME_PRICE_RE.match(s.strip())
    if not match:
        return None
    price = int(match.group("price"))
    if not (_MIN_PRICE <= price <= _MAX_PRICE):
        return None
    names = match.group("names")
    if not re.search(r"[/／、]", names):
        return None
    segments = re.split(r"[/／、]", names)
    results: list[tuple[str, int | None]] = []
    for segment in segments:
        name = _NOISE_RE.sub(" ", segment.strip())
        name = re.sub(r"[，,、]+$", "", name).strip()
        name = re.sub(r"\s+", "", name).strip()
        if len(name) >= 2:
            results.append((name, price))
    return results if len(results) >= 2 else None


def _normalize_product_pattern_text(raw_name: str, brand: str = "") -> str:
    s = unicodedata.normalize("NFKC", raw_name or "").strip()
    s = re.sub(r"^[：:]+\s*", "", s)
    s = _normalize_marketing_text(s)
    s = re.sub(r"\$(\d)", r"\1", s)
    s = re.sub(r"(\d)\$", r"\1", s)
    s = _BRACKET_RE.sub(" ", s)
    s = re.sub(r"[\[\(（【][^\]\)）】]*$", " ", s)
    s = _strip_brand_keywords(s, brand)
    return _strip_payment_asides(s)


def _strip_payment_asides(text: str) -> str:
    """Drop payment-method notes separated from the product by slash-like punctuation."""
    s = text
    s = re.sub(
        rf"[/／｜|]\s*[^/／｜|\d]*(?:{_PAYMENT_ASIDE_PATTERN})[^/／｜|\d]*(?=\d{{2,3}}\s*(?:元)?)",
        " ",
        s,
        flags=re.IGNORECASE,
    )
    s = re.sub(
        rf"(\d{{2,3}}元)\s*[/／｜|]\s*[^/／｜|]*(?:{_PAYMENT_ASIDE_PATTERN}).*$",
        r"\1",
        s,
        flags=re.IGNORECASE,
    )
    return s


def _extract_shared_prefix_flavors(s: str) -> list[tuple[str, int | None]] | None:
    """Handle '<共同前綴>-<口味A>、<口味B>雙風味' style: shared prefix over flavors.

    e.g. '乖乖玉米脆條-蘋果牛奶、木瓜牛奶雙風味 / 35元'
      -> ('乖乖玉米脆條蘋果牛奶風味', 35), ('乖乖玉米脆條木瓜牛奶風味', 35)
    """
    match = _SHARED_FLAVOR_RE.search(s)
    if not match:
        return None
    prefix = match.group("prefix").strip()
    if len(prefix) < 2:
        return None
    suffix = "口味" if "口味" in match.group("marker") else "風味"
    flavors = [f.strip() for f in match.group("flavors").split("、") if f.strip()]
    if len(flavors) < 2:
        return None
    price = _best_price_from_text(s)
    results: list[tuple[str, int | None]] = []
    for flavor in flavors:
        name = re.sub(r"\s+", "", f"{prefix}{flavor}{suffix}")
        if len(name) >= 2:
            results.append((name, price))
    return results if len(results) >= 2 else None


def _extract_multiple_price_segments(text: str, brand: str) -> list[tuple[str, int | None]]:
    results: list[tuple[str, int | None]] = []
    start = 0
    for match in _PRICE_TOKEN_RE.finditer(text):
        price = int(match.group(1))
        if not (_MIN_PRICE <= price <= _MAX_PRICE):
            continue
        raw_name = text[start:match.start()].strip()
        start = match.end()
        if not raw_name:
            continue
        price, raw_name = _bundle_adjusted_price(raw_name, price)
        if price is None:
            continue
        name = _clean_extracted_product_name(raw_name, brand)
        if len(name) >= 2 and not _is_price_label_name(name):
            results.append((name, price))
    return results


def _bundle_adjusted_price(raw_name: str, price: int) -> tuple[int | None, str]:
    match = _BUNDLE_PRICE_SUFFIX_RE.search(raw_name)
    if not match:
        return price, raw_name
    count = int(match.group("count"))
    unit_price = int((price / count) + 0.5)
    cleaned_name = raw_name[: match.start()].strip()
    if not (_MIN_PRICE <= unit_price <= _MAX_PRICE):
        return None, cleaned_name
    return unit_price, cleaned_name


def _clean_extracted_product_name(raw_name: str, brand: str) -> str:
    s = unicodedata.normalize("NFKC", raw_name or "").strip()
    s = _normalize_marketing_text(s)
    s = _BRACKET_RE.sub(" ", s)
    s = _strip_brand_keywords(s, brand)
    s = re.sub(r"(?<=[\u4e00-\u9fff])[xX×](?=[\u4e00-\u9fff])", " ", s)
    s = re.sub(r"[#:/／｜|,，.。!！?？~～\-_=+]+", " ", s)
    s = _TITLE_PREFIX_RE.sub(" ", s)
    s = _NOISE_RE.sub(" ", s)
    s = _OPTIONAL_RE.sub(" ", s)
    s = _PROMO_RE.sub(" ", s)
    s = _PROMO_SUFFIX_RE.sub(" ", s)
    s = _PROMO_TAIL_RE.sub(" ", s)
    s = _QUANTITY_SUFFIX_RE.sub("", s).strip()
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"[^\w\u4e00-\u9fff]+", "", s)
    return s


def _best_price_from_text(text: str) -> int | None:
    return _price_from_text(text, prefer_first=False, max_price=_MAX_PRICE)


def _primary_price_from_text(text: str) -> int | None:
    return _price_from_text(text, prefer_first=True, max_price=999)


def _price_from_text(text: str, *, prefer_first: bool, max_price: int) -> int | None:
    bundle_spans: list[tuple[int, int]] = []
    bundle_prices: list[int] = []
    for match in _BUNDLE_PRICE_RE.finditer(text):
        count = int(match.group("count"))
        total = int(match.group("total"))
        unit_price = int((total / count) + 0.5)
        if _MIN_PRICE <= unit_price <= max_price:
            bundle_prices.append(unit_price)
            bundle_spans.append(match.span("total"))

    prices: list[int] = []
    for match in _PRICE_TOKEN_RE.finditer(text):
        span = match.span(1)
        if any(start <= span[0] and span[1] <= end for start, end in bundle_spans):
            continue
        price = int(match.group(1))
        if _MIN_PRICE <= price <= max_price:
            prices.append(price)
    if prices:
        return prices[0] if prefer_first else prices[-1]
    if not bundle_prices:
        return None
    return bundle_prices[0] if prefer_first else bundle_prices[-1]


def _is_price_context_line(line: str) -> bool:
    return bool(_PRICE_CONTEXT_RE.search(line))


def _is_price_label_name(name: str) -> bool:
    return bool(re.fullmatch(r"(價格|售價|價錢|原價|特價|目前特價|活動價|台幣)+", name))


def _is_junk_extracted_product_name(name: str) -> bool:
    text = unicodedata.normalize("NFKC", name or "").strip()
    if not text:
        return True
    compact = re.sub(r"\s+", "", text)
    if _is_price_label_name(compact):
        return True
    # 萊爾富「即時救援」是即期品折扣活動名稱，不是商品名。貼文者常把它連同折扣價
    # 填進商品名稱欄（如「售價：99元/ 即時救援7折69元」），真正商品名留在標題。
    if re.search(r"即時救援|即期救援|救援價", compact):
        return True
    if compact in _FRAGMENT_PRODUCT_NAMES:
        return True
    if re.fullmatch(r"(?:今日|會員|搭配|友善|購入)(?:價|\d+折|一)?", compact):
        return True
    if re.fullmatch(r"(?:\d{1,3}|元|價格|售價|原價|會員|目前|特價|優惠|預購|加點數|點數)+", compact):
        return True
    if re.fullmatch(r"(?:\d+|元|塊|套餐|打折|點數|換|的話|會員|特價|優惠|任選)+", compact):
        return True
    digits = sum(ch.isdigit() for ch in compact)
    if digits >= 2 and digits / max(len(compact), 1) >= 0.35 and re.search(r"(塊|套餐|打折|點數|換)", compact):
        return True
    promo_chars = sum(len(token) for token in re.findall(r"預購|加點數|點數|會員|特價|優惠|原價|售價|目前|元", compact))
    return promo_chars >= 2 and promo_chars / max(len(compact), 1) >= 0.5


def _title_fallback_product_name(post: Post) -> str:
    title_name = _title_product_name(post.title)
    cleaned = _clean_extracted_product_name(title_name, post.brand)
    if len(cleaned) >= 2 and not _is_junk_extracted_product_name(cleaned):
        return cleaned
    return title_name.strip()


def _normalize_marketing_text(text: str) -> str:
    return re.sub(r"Fami!ce", "Famice", text, flags=re.IGNORECASE)


def _strip_brand_keywords(text: str, brand: str) -> str:
    if not brand:
        return text
    s = text
    keywords = [*BRANDS.get(brand, []), brand]
    for kw in sorted(set(keywords), key=len, reverse=True):
        if not kw:
            continue
        if re.search(r"[A-Za-z0-9]", kw):
            pattern = rf"(?<![A-Za-z0-9]){re.escape(kw)}(?![A-Za-z0-9])"
            s = re.sub(pattern, " ", s, flags=re.IGNORECASE)
        else:
            s = re.sub(re.escape(kw), " ", s, flags=re.IGNORECASE)
    return s


def categorize_product(name: str) -> str:
    """Assign a category to a product name based on keyword matching."""
    text = unicodedata.normalize("NFKC", name or "").lower()
    matches: list[tuple[tuple[int, int, int, int], str]] = []
    for index, (category, keywords) in enumerate(PRODUCT_CATEGORIES.items()):
        matched = [kw for kw in keywords if kw.lower() in text]
        if not matched:
            continue
        strong = [kw for kw in matched if kw in _CATEGORY_STRONG_KEYWORDS.get(category, set())]
        specific = [kw for kw in matched if kw not in _GENERIC_CATEGORY_KEYWORDS]
        score = (
            len(strong),
            max((len(kw) for kw in strong), default=0),
            len(specific),
            max((len(kw) for kw in specific), default=0),
            len(matched),
            -index,
        )
        matches.append((score, category))
    if matches:
        matches.sort(reverse=True)
        return matches[0][1]
    return "其他"


def _name_bigrams(text: str) -> set[str]:
    chars = re.sub(r"[^\w\u4e00-\u9fff]", "", text)
    if len(chars) < 2:
        return {chars} if chars else set()
    return {chars[i : i + 2] for i in range(len(chars) - 1)}


def _route_comments_by_product(comments: list[Comment], names: list[str]) -> list[list[Comment]]:
    """Route each comment to the split product whose name it distinctly matches.

    Falls back to sharing a comment across all split products when its text
    does not uniquely single out one product's distinctive name fragments,
    so ambiguous comments still count (previous behavior) instead of being
    silently dropped.
    """
    bigrams = [_name_bigrams(name) for name in names]
    distinctive: list[set[str]] = []
    for i, grams in enumerate(bigrams):
        others: set[str] = set()
        for j, other_grams in enumerate(bigrams):
            if j != i:
                others |= other_grams
        distinctive.append(grams - others)

    routed: list[list[Comment]] = [[] for _ in names]
    for comment in comments:
        comment_grams = _name_bigrams(comment.text)
        hits = [i for i, dset in enumerate(distinctive) if dset and (comment_grams & dset)]
        if len(hits) == 1:
            routed[hits[0]].append(comment)
        else:
            for bucket in routed:
                bucket.append(comment)
    return routed


def preprocess_posts(posts: list[Post]) -> list[Post]:
    """Split multi-product posts and extract prices."""
    result: list[Post] = []
    for post in posts:
        extraction_name = (
            _reply_product_extraction_text(post.product_name)
            if post.is_reply
            else post.product_name
        )
        items = extract_products_and_prices(extraction_name, post.brand)
        cleaned_items = [_strip_product_item_promo_suffix(name, price) for name, price in items]
        if len(items) == 1 and items[0][0] == extraction_name and items[0][1] is None:
            cleaned_name = _strip_product_name_promo_suffix(extraction_name)
            if len(cleaned_name) >= 2 and not _is_junk_extracted_product_name(cleaned_name):
                if cleaned_name == post.product_name:
                    result.append(post)
                else:
                    result.append(_replace_post_product(post, cleaned_name, None))
                continue
            if _is_junk_extracted_product_name(extraction_name):
                fallback_name = _title_fallback_product_name(post)
                if fallback_name and len(fallback_name) >= 2:
                    result.append(_replace_post_product(post, fallback_name, _primary_price_from_text(extraction_name)))
                    continue
            result.append(post)
            continue
        valid_items = [
            (name, price) for name, price in cleaned_items
            if not _GARBAGE_NAME_RE.match(name)
            and not _is_junk_extracted_product_name(name)
            and len(name) >= 2
        ]
        junk_items = [
            (name, price) for name, price in cleaned_items
            if len(name) >= 2 and _is_junk_extracted_product_name(name)
        ]
        if not valid_items and junk_items:
            fallback_name = _title_fallback_product_name(post)
            fallback_price = _primary_price_from_text(extraction_name)
            if fallback_name and len(fallback_name) >= 2:
                valid_items = [(fallback_name, fallback_price)]
        # Drop items that still canonicalize to "unknown" (promo/fragment tokens such
        # as 加價購169元 / 嚐鮮價 that slip past junk detection); if that empties the
        # list, fall back to the post title so unrelated posts don't merge under "unknown".
        resolved_items = [
            (name, price)
            for name, price in valid_items
            if canonical_product_name(post.brand, name) != "unknown"
        ]
        if not resolved_items:
            fallback_name = _title_fallback_product_name(post)
            if (
                fallback_name
                and len(fallback_name) >= 2
                and canonical_product_name(post.brand, fallback_name) != "unknown"
            ):
                resolved_items = [(fallback_name, _primary_price_from_text(extraction_name))]
        valid_items = resolved_items
        # Expand a bare product-form name (e.g. "霜淇淋" from a shorthand price line) to
        # the title's more specific flavored name when the title ends with that form word
        # (e.g. title 全家草莓優格x比利時巧克力霜淇淋 -> keep the flavor, not just "霜淇淋").
        title_specific = _title_fallback_product_name(post)
        if title_specific and not _is_junk_extracted_product_name(title_specific):
            expanded_items = []
            for name, price in valid_items:
                if (
                    _is_bare_form_name(name)
                    and len(title_specific) > len(name)
                    and title_specific != name
                    and any(title_specific.endswith(form) for form in _matched_product_forms(name))
                ):
                    expanded_items.append((title_specific, price))
                else:
                    expanded_items.append((name, price))
            valid_items = expanded_items
        if len(valid_items) > 1:
            routed_comments = _route_comments_by_product(
                post.comments, [name for name, _ in valid_items]
            )
        else:
            routed_comments = [post.comments for _ in valid_items]
        for (name, price), comments in zip(valid_items, routed_comments):
            new_post = Post(
                id=f"{post.id}_{_compact_key(name)}" if len(items) > 1 else post.id,
                source=post.source,
                board=post.board,
                url=post.url,
                title=post.title,
                brand=post.brand,
                product_name=name,
                price=str(price) if price is not None else post.price,
                author=post.author,
                author_score=post.author_score,
                review_text=post.review_text,
                posted_at=post.posted_at,
                is_reply=post.is_reply,
                push_count=post.push_count,
                comments=comments,
                raw=post.raw,
            )
            result.append(new_post)
    return result


def _strip_product_item_promo_suffix(name: str, price: int | None) -> tuple[str, int | None]:
    return _strip_product_name_promo_suffix(name), price


def _strip_product_name_promo_suffix(name: str) -> str:
    text = unicodedata.normalize("NFKC", name or "").strip()
    stripped = _PROMO_SUFFIX_RE.sub("", text).strip()
    stripped = re.sub(r"\s+", "", stripped)
    return stripped or text


def _replace_post_product(post: Post, name: str, price: int | None) -> Post:
    return Post(
        id=post.id,
        source=post.source,
        board=post.board,
        url=post.url,
        title=post.title,
        brand=post.brand,
        product_name=name,
        price=str(price) if price is not None else post.price,
        author=post.author,
        author_score=post.author_score,
        review_text=post.review_text,
        posted_at=post.posted_at,
        is_reply=post.is_reply,
        push_count=post.push_count,
        comments=post.comments,
        raw=post.raw,
    )


def normalize_product(brand: str, name: str) -> str:
    """Return a stable, reproducible product key for one brand/name pair."""
    return _compact_key(canonical_product_name(brand, name))


def canonical_product_name(brand: str, name: str) -> str:
    """Clean noisy post titles and apply data-driven brand/product aliases."""
    cleaned = _clean_product_name(brand, name)
    return _apply_product_alias(brand, cleaned) or "unknown"


def _clean_product_name(brand: str, name: str) -> str:
    s = unicodedata.normalize("NFKC", name or "").strip()
    s = _BRACKET_RE.sub(" ", s)
    keywords = [*BRANDS.get(brand, []), brand]
    for kw in sorted(set(keywords), key=len, reverse=True):
        if kw:
            s = re.sub(re.escape(kw), " ", s, flags=re.IGNORECASE)
    s = re.sub(r"[#:/／｜|,，.。!！?？~～\-_=+]+", " ", s)
    s = _TITLE_PREFIX_RE.sub(" ", s)
    s = _NOISE_RE.sub(" ", s)
    s = _OPTIONAL_RE.sub(" ", s)
    s = _PROMO_RE.sub(" ", s)
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"[^\w\u4e00-\u9fff]+", "", s)
    s = _strip_trailing_noise(s)
    for old, new in _SYNONYM_MAP.items():
        s = s.replace(old, new)
    return s or "unknown"


def _strip_trailing_noise(s: str) -> str:
    s = _TRAILING_NOISE_CLEAN_RE.sub("", s)
    s = _TRAILING_PRICE_CLEAN_RE.sub("", s)
    s = _TRAILING_FILLER_RE.sub("", s)
    if len(s) >= 6:
        half = len(s) // 2
        if s[:half] == s[half : half * 2]:
            s = s[:half]
    return s


def _apply_product_alias(brand: str, cleaned_name: str) -> str:
    aliases = PRODUCT_ALIASES.get(brand, {})
    if not aliases:
        return cleaned_name
    alias_map = {
        _compact_key(_clean_product_name_without_alias(brand, alias)): _clean_product_name_without_alias(brand, canonical)
        for alias, canonical in aliases.items()
    }
    return alias_map.get(_compact_key(cleaned_name), cleaned_name)


def _clean_product_name_without_alias(brand: str, name: str) -> str:
    s = unicodedata.normalize("NFKC", name or "").strip()
    s = _BRACKET_RE.sub(" ", s)
    keywords = [*BRANDS.get(brand, []), brand]
    for kw in sorted(set(keywords), key=len, reverse=True):
        if kw:
            s = re.sub(re.escape(kw), " ", s, flags=re.IGNORECASE)
    s = re.sub(r"[#:/／｜|,，.。!！?？~～\-_=+]+", " ", s)
    s = _TITLE_PREFIX_RE.sub(" ", s)
    s = _NOISE_RE.sub(" ", s)
    s = _OPTIONAL_RE.sub(" ", s)
    s = _PROMO_RE.sub(" ", s)
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"[^\w\u4e00-\u9fff]+", "", s)
    for old, new in _SYNONYM_MAP.items():
        s = s.replace(old, new)
    return s or "unknown"


def _compact_key(name: str) -> str:
    s = unicodedata.normalize("NFKC", name or "").casefold()
    s = re.sub(r"[\s　]+", "", s)
    s = re.sub(r"[^\w\u4e00-\u9fff]+", "", s)
    return s or "unknown"


def group_products(posts: list[Post]) -> dict[tuple[str, str], list[Post]]:
    """依品牌與商品鍵分組貼文。"""
    groups: dict[tuple[str, str], list[Post]] = {}
    representatives: dict[str, list[str]] = defaultdict(list)
    for post in posts:
        brand = post.brand
        name = canonical_product_name(brand, post.product_name)
        matched_key = None
        for key, names in representatives.items():
            key_brand, representative = key.split(":", 1)
            if key_brand == brand and any(_same_product(brand, name, existing) for existing in names + [representative]):
                matched_key = key
                break
        if matched_key is None:
            matched_key = f"{brand}:{normalize_product(brand, name)}"
            groups[(brand, normalize_product(brand, name))] = []
        groups[(brand, matched_key.split(":", 1)[1])].append(post)
        representatives[matched_key].append(name)
    return dict(groups)


def _same_product(brand: str, left: str, right: str) -> bool:
    left_key = normalize_product(brand, left)
    right_key = normalize_product(brand, right)
    if left_key == right_key:
        return True
    if left_key == "unknown" or right_key == "unknown":
        return False
    if _has_distinctive_difference(left_key, right_key):
        return False
    if _same_combo_flavor_product(left_key, right_key):
        return True
    ratio = SequenceMatcher(None, left_key, right_key).ratio()
    jaccard = _char_jaccard(left_key, right_key)
    return ratio >= float(PRODUCT_NORMALIZATION["similarity_threshold"]) or jaccard >= float(
        PRODUCT_NORMALIZATION["jaccard_threshold"]
    )


def _char_jaccard(left: str, right: str) -> float:
    left_set = set(left)
    right_set = set(right)
    union = left_set | right_set
    return len(left_set & right_set) / len(union) if union else 0.0


def _has_distinctive_difference(left: str, right: str) -> bool:
    for term in _DISTINCTIVE_TERMS:
        if (term in left) != (term in right):
            return True
    return False


def _same_combo_flavor_product(left: str, right: str) -> bool:
    left_flavors = _matched_flavor_terms(left)
    right_flavors = _matched_flavor_terms(right)
    if len(left_flavors) < 2 or left_flavors != right_flavors:
        return False
    left_forms = _matched_product_forms(left)
    right_forms = _matched_product_forms(right)
    return bool(left_forms & right_forms) or _both_ice_forms(left_forms, right_forms)


def _matched_flavor_terms(text: str) -> frozenset[str]:
    return frozenset(term for term in _DISTINCTIVE_TERMS if term in text)


def _matched_product_forms(text: str) -> frozenset[str]:
    return frozenset(term for term in _PRODUCT_FORM_TERMS if term in text)


def _is_bare_form_name(name: str) -> bool:
    """True when the name is only a product-form word (e.g. 霜淇淋) with no flavor."""
    forms = _matched_product_forms(name)
    if not forms:
        return False
    residual = name
    for form in forms:
        residual = residual.replace(form, "")
    return len(residual.strip()) == 0


def _both_ice_forms(left_forms: frozenset[str], right_forms: frozenset[str]) -> bool:
    ice_forms = {"霜淇淋", "冰淇淋", "雪糕", "冰棒", "冰沙", "甜筒"}
    return bool(left_forms & ice_forms) and bool(right_forms & ice_forms)
