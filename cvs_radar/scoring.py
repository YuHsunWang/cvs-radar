"""Fair score aggregation and consensus classification for PRD F5/F6/§8."""

from __future__ import annotations

import csv
import math
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from statistics import mean

from .config import (
    BRAND_COMPARISON,
    BRANDS,
    CONFIDENCE_BANDS,
    CONSENSUS,
    PRODUCT_ALIASES,
    PRODUCT_CATEGORIES,
    PRODUCT_NORMALIZATION,
    SCORING,
    SHILL_DETECTION,
)
from .models import Comment, Contributor, Post, ProductReport
from .parser import _title_product_name
from .preference import AccountProfile
from .sentiment import NEGATIVE_WORDS, POSITIVE_WORDS


_BRACKET_RE = re.compile(r"[\[\(（【].*?[\]\)）】]")
_TITLE_PREFIX_RE = re.compile(r"^\s*(商品|心得|情報|問題|請益|討論|問卦)\s*")
_NOISE_RE = re.compile(
    r"(無限回購|期間限定|季節限定|超好吃|好不好吃|好吃嗎|小心得|新口味|"
    r"心得|開箱|踩雷|地雷|評價|回購|分享|請益|請問|詢問|推薦|推不推|"
    r"反推|實測|試吃|食記|簡評|必買|不推|超商|好吃|難吃|最新|聯名|"
    r"大推|激推|微雷|不雷|二訪|回味)"
    # NOTE: keep compound 踩雷/地雷/微雷/不雷 but never a bare 雷 — a lone 雷 in
    # the alternation matched inside real names (蜂蜜雷夢軟歐 -> 蜂蜜夢軟歐). DEV-110.
)
_OPTIONAL_RE = re.compile(
    r"((?:\d+(?:\.\d+)?|[一二三四五六七八九十]+)\s*(入|包|個|顆|片|枚|杯|瓶|罐|盒|組|ml|毫升|g|公克|克|支)|"
    r"(口味|數量|容量|規格|加量|限定|新品|新上市))"
)
_PROMO_RE = re.compile(
    r"(\d+元|\$\d+|"
    r"買[一二三四五六七八九十\d]+[送得]|"
    r"第[二三四五六七八九十\d]+件\d*折|"
    r"任選\d+件?\d*元?|"
    r"[買滿]\d+[送打折抽]|"
    r"\d+買[一二三四五六七八九十\d]+[支個入包瓶罐杯盒組件]?|"
    r"可以抽抽樂|抽抽樂|集點|加購|"
    r"限時特價|目前特價|原價|特價|價格|售價|價錢|台幣|特惠|促銷|優惠|折扣|"
    r"買就送|滿額|加價購)"
)
_BUNDLE_PRICE_SUFFIX_RE = re.compile(
    r"(?P<count>[2-6])\s*(?P<unit>支|入|個|包|瓶|罐|杯|盒|組|件|份)\s*$"
)
_BUNDLE_PRICE_RE = re.compile(
    r"(?P<count>[2-6])\s*(?P<unit>支|入|個|包|瓶|罐|杯|盒|組|件|份)\s*\$?\s*(?P<total>\d{2,3})\s*(?:元)?"
)
_TRAILING_PRICE_RE = re.compile(
    r"^(.+?)\s*(?:各)?\s*(\d{2,3})\s*元?$"
)
_PRICE_BEFORE_PROMO_RE = re.compile(
    r"^(.+?)"
    r"(\d{2,3})"
    r"(?:元)?"
    r"(?:搭|取件|隨買|跨店|"
    r"買[一二三四五六七八九十\d]+[送得支個入包瓶罐杯盒組件份]|"
    r"第[二三四五六七八九十\d]+件|任選|滿額|加購|優惠|半價|"
    r"[買滿]\d+[送打折抽]|好康|活動|限時|特惠|促銷|折扣).*$"
)
_PROMO_TAIL_RE = re.compile(
    r"(隨買|跨店|取件|搭配|好康|活動|優惠|加購|半價|滿額).*$"
)
_PROMO_SUFFIX_RE = re.compile(
    r"(?:點數兌換|免費兌換的?|兌換|預購加點數|會員特價.*|會員優惠.*|任選.*|打折.*)$"
)
_PAYMENT_ASIDE_PATTERN = (
    r"付款|支付|刷卡|信用卡|金融卡|聯邦卡|國泰卡|中信卡|玉山卡|台新卡|"
    r"悠遊卡|一卡通|icash|ipass|i\s*pass|line\s*pay|linepay|街口|全支付|全盈|"
    r"apple\s*pay|google\s*pay|samsung\s*pay"
)
_MULTI_PRODUCT_RE = re.compile(
    r"([一-鿿A-Za-z][一-鿿A-Za-z\w]*?)"
    r"(?:[兩三四五六七八九十\d]*[支個入包瓶罐杯盒組件份])*"
    r"(\d{2,3})"
)
_QUANTITY_SUFFIX_RE = re.compile(
    r"[兩三四五六七八九十\d]+[支個入包瓶罐杯盒組件份]$"
)
_COMMENT_NOISE_RE = re.compile(r"(這款|這個|這品|這次|個人覺得|我覺得|覺得|補充[:：]?|推薦|推推|再推一次)")
_OFF_TOPIC_COMMENT_RE = re.compile(
    r"(沒看到|買不到|找不到|缺貨|改名|停產|哪裡有|沒有賣|沒在賣|漲價|降價|調漲|"
    r"區域限定|限定區|庫存|截圖|圖片|照片|拍照|陰影|謝謝.*分享|感謝.*分享|加碼分享)"
)
_REACTION_ECHO_RE = re.compile(
    r"^\s*(原來|果然|難怪|所以)\S{0,8}(雷|難吃|踩雷|很差|好硬|份量.*少|縮水|貴)"
)
_FIRST_HAND_COMMENT_RE = re.compile(
    r"(我|自己|吃過|喝過|買過|試過|昨天|今天|剛剛|剛|上次|之前|回購|不會再買)"
)
_PTT_PRODUCT_TEMPLATE = "(區域型商品請註明 試吃試用品請標示價格0元)"
_URL_RE = re.compile(r"https?://", re.IGNORECASE)
_PRODUCT_REVIEW_START_RE = re.compile(r"^\s*[：:]?\s*[【\[]?\s*心得\s*[】\]]?\s*[:：]")
_PRICE_TOKEN_RE = re.compile(r"(?<!\d)(\d{1,3})(?!\d)\s*(?:元|台幣)?")
_PRICE_CONTEXT_RE = re.compile(
    r"^\s*(?:價格|售價|價錢|原價|特價|目前|活動價|NT\$?|\$|\d+\s*(?:ML|毫升|G|公克|克))",
    re.IGNORECASE,
)
_FRAGMENT_PRODUCT_NAMES = {
    "今日",
    "會員",
    "軟歐",
    "搭配",
    "奶茶",
    "單瓶",
    "前者",
    "後者",
    "打折",
    "元",
    "任選",
    "購入",
    "友善",
    "雞排",
    "油雞",
    "全家",
    "全品項",
    "買兩個",
    "元新品",
}
_MIN_PRICE = 15
_MAX_PRICE = 400
_SYNONYM_MAP = {
    "蕃薯": "地瓜",
    "番薯": "地瓜",
    "起士": "起司",
    "芝士": "起司",
    "優格": "優酪",
    "吐司": "土司",
    "哈蜜瓜": "哈密瓜",
    "贅澤": "贅沢",
}
_DISTINCTIVE_TERMS = {
    "原味",
    "辣",
    "麻辣",
    "起司",
    "地瓜",
    "乳酪",
    "巧克力",
    "可可",
    "哈密瓜",
    "芒果",
    "荔枝",
    "水蜜桃",
    "桃",
    "蘋果",
    "青蘋果",
    "木瓜",
    "香蕉",
    "奇異果",
    "火龍果",
    "鳳梨",
    "葡萄柚",
    "葡萄",
    "柳橙",
    "橘",
    "橙",
    "芭樂",
    "莓",
    "草莓",
    "野莓",
    "蔓越莓",
    "抹茶",
    "焙茶",
    "紅茶",
    "綠茶",
    "烏龍",
    "咖啡",
    "奶茶",
    "牛奶",
    "鮮奶",
    "優酪",
    "香草",
    "焦糖",
    "蜂蜜",
    "海鹽",
    "檸檬",
    "柚",
    "藍莓",
    "芋頭",
    "花生",
    "開心果",
    "栗子",
    "榛果",
    "堅果",
    "芝麻",
    "紅豆",
    "綠豆",
    "玉米",
    "牛肉",
    "豬肉",
    "雞肉",
    "鮪魚",
    "鮭魚",
    "椒麻",
    "麻油",
    "咖哩",
    "蒜",
    "蔥",
    "辣椒",
}
_GENERIC_CATEGORY_KEYWORDS = {
    "牛奶",
    "鮮奶",
    "巧克力",
    "可可",
    "草莓",
    "抹茶",
    "咖啡",
    "奶茶",
    "紅茶",
    "綠茶",
    "烏龍",
    "梅子",
    "芭樂",
    "葡萄",
    "鳳梨",
    "檸檬",
    "蘋果",
    "木瓜",
    "芒果",
    "起司",
    "乳酪",
    "糖",
    "捲",
}
_CATEGORY_STRONG_KEYWORDS = {
    "周邊": {"捏捏球", "吊飾", "積木", "置物箱", "盲盒", "杯組", "公仔", "玩具", "文具", "襪套"},
    "冰品": {"酷聖霜", "霜淇淋", "雪糕", "冰棒", "冰淇淋", "冰沙", "聖代", "甜筒", "酷繽沙", "繽球"},
    "飲料": {"拿鐵", "咖啡", "奶茶", "紅茶", "綠茶", "烏龍", "豆漿", "果汁", "汽水", "可樂", "啤酒", "氣泡", "檸檬水", "蜜茶", "冬瓜茶", "貝納頌", "光泉", "林鳳營", "瑞穗", "御茶園", "茶裏王", "原萃", "麥茶", "果昔", "冰茶", "水果茶", "龜記", "微醉", "純喫茶", "青茶"},
    "甜點": {"蛋糕", "泡芙", "布丁", "慕斯", "銅鑼燒", "麻糬", "大福", "鯛魚燒", "甜甜圈", "奶酪", "果凍", "蕨餅", "糰子"},
    "麵包": {"麵包", "吐司", "土司", "貝果", "餐包", "菠蘿", "可頌", "三明治"},
    "便當": {"便當", "飯糰", "御飯糰", "炒飯", "燴飯", "丼", "餐盒", "壽司", "捲餅", "燉飯", "涼麵", "雞飯", "鰻魚飯", "豬腳飯"},
    "零食": {"洋芋片", "餅乾", "軟糖", "脆條", "乖乖", "蝦味先", "科學麵", "米果", "仙貝", "堅果", "果乾", "肉乾", "魷魚絲", "玉米片", "多力多滋", "多利多茲", "樂事", "爆脆捲"},
    "泡麵": {"泡麵", "速食麵", "杯麵", "碗麵", "拉麵", "一度贊", "來一客", "統一麵", "滿漢"},
}
_PRODUCT_FORM_TERMS = {
    "霜淇淋",
    "冰淇淋",
    "雪糕",
    "冰棒",
    "冰沙",
    "甜筒",
    "麵包",
    "餅乾",
    "脆條",
    "飯糰",
    "便當",
    "飲料",
}


@dataclass(frozen=True, slots=True)
class _CommentAttribution:
    include_score: bool
    effective_sentiment: float | None
    competitor_brands: tuple[str, ...] = ()
    competitor_preference: bool = False
    own_preference: bool = False


# Distinctive product-type suffixes for detecting space-separated parallel
# product listings ("地瓜起司雞排三明治 厚里肌蛋沙拉三明治"). Kept to multi-char,
# unambiguous nouns so an ordinary single name with an internal space is not
# over-split. DEV-110.
_PARALLEL_PRODUCT_SUFFIXES = (
    "三明治", "御飯糰", "飯糰", "便當", "軟歐", "貝果", "可頌", "餐包",
    "蛋餅", "義大利麵", "霜淇淋", "冰淇淋", "布丁", "泡芙", "蛋糕",
    "拉麵", "麵包", "吐司", "土司",
)


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


_SHARED_SAME_PRICE_RE = re.compile(
    r"^\s*(?P<names>.+?)\s*(?:[/／]\s*)?(?:都|各)\s*(?P<price>\d{2,3})\s*(?:元)?\s*\$?\s*$"
)


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


_SHARED_FLAVOR_RE = re.compile(
    r"(?P<prefix>[^-－/／]{2,}?)[-－]"
    r"(?P<flavors>[^-－/／]*?、[^-－/／]*?)"
    r"(?P<marker>雙風味|雙口味|雙口感|兩種口味|兩款口味)"
)


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


_GARBAGE_NAME_RE = re.compile(
    r"^\d{1,3}$|^unknown$|^任\d|^折後$|^消費滿|^期間|"
    r"^友善時光$|^牧場直送$|.*(?:FMC|系列商品|即期品)|"
    r".*(?:兩件|兩瓶|合購|加購|app|折價券|好康|扣|跨店|指定商品|點數換)|"
    r"任[0-9二三四五六七八九十]|^\d+元$|^\d+金|"
    r"^ps|^配\S{0,3}$|^記得|^最近\S{0,2}$|^大卡$|^OP$|"
    r"^i珍食|^APP券|^惜福|^555|^36\d{3}|"
    r".*(?:ibon|票券).*(?:ibon|票券)|"
    r".{60,}",
    re.IGNORECASE,
)


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


_TRAILING_NOISE_CLEAN_RE = re.compile(
    r"\d{2,3}(?:ibon|\u7968\u5238|[xX\u00d7]|\u6298|\u4ef6|\u9ede|\u74f6|\u676f|\u91d1).*$"
)
_TRAILING_PRICE_CLEAN_RE = re.compile(r"\d{1,3}$")
_TRAILING_FILLER_RE = re.compile(
    r"(?:\u5617\u9bae\u50f9|\u5690\u9bae\u50f9|\u534a\u50f9|\u55ae\u4ef6|\u50f9|\u90fd|\u4e00|\u7684|\u819b)$"
)


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


# Backends whose sentiment is an authoritative per-comment judgment (LLM
# fingerprint labels, reviewed text overrides); heuristic rewrites like the
# own-brand positive floor must not override them.
_AUTHORITATIVE_BACKENDS = frozenset({"llm-backfill", "codex"})


def _comment_attribution(post_brand: str, comment: Comment) -> _CommentAttribution:
    """Decide whether a comment's sentiment belongs to the post product."""

    sentiment = comment.sentiment
    other_brands = tuple(_mentioned_other_brands(post_brand, comment.text))
    if not other_brands:
        return _CommentAttribution(True, sentiment)

    if not _has_comparison_tone(comment.text):
        return _CommentAttribution(False, sentiment, other_brands, competitor_preference=False)

    favored = _favored_brand(post_brand, comment.text, other_brands)
    canonical_post_brand = _canonical_brand(post_brand)
    if favored == canonical_post_brand:
        if comment.backend in _AUTHORITATIVE_BACKENDS and sentiment is not None:
            effective = sentiment
        else:
            positive_floor = float(BRAND_COMPARISON.get("own_brand_positive_floor", 0.4))
            effective = max(sentiment if sentiment is not None else 0.0, positive_floor)
        return _CommentAttribution(
            True, effective, other_brands, competitor_preference=False, own_preference=True
        )

    return _CommentAttribution(False, sentiment, other_brands, competitor_preference=True)


def _is_reaction_echo_comment(text: str) -> bool:
    s = unicodedata.normalize("NFKC", text or "").strip()
    return bool(_REACTION_ECHO_RE.search(s)) and not _FIRST_HAND_COMMENT_RE.search(s)


def _mentioned_other_brands(post_brand: str, text: str) -> list[str]:
    canonical_post_brand = _canonical_brand(post_brand)
    found = []
    for brand in BRANDS:
        canonical = _canonical_brand(brand)
        if canonical == canonical_post_brand:
            continue
        if _brand_positions(text, canonical):
            found.append(canonical)
    return sorted(set(found))


def _has_comparison_tone(text: str) -> bool:
    token = _text_token(text)
    return any(_text_token(term) in token for term in BRAND_COMPARISON["comparison_terms"])


def _favored_brand(post_brand: str, text: str, other_brands: tuple[str, ...]) -> str | None:
    token = _text_token(text)
    canonical_post_brand = _canonical_brand(post_brand)
    brands = (canonical_post_brand, *other_brands)
    spans = _all_brand_spans(text, brands)
    positive_terms = _positive_terms()

    favored = _favored_by_bi_comparison(token, spans, positive_terms, canonical_post_brand)
    if favored:
        return favored

    favored = _favored_by_still_pattern(token, spans, positive_terms)
    if favored:
        return favored

    favored = _favored_by_win_loss(token, spans, canonical_post_brand)
    if favored:
        return favored

    favored = _favored_by_nearby_positive(token, spans, positive_terms)
    if favored:
        return favored

    return None


def _favored_by_bi_comparison(
    token: str,
    spans: list[tuple[str, int, int]],
    positive_terms: tuple[str, ...],
    post_brand: str,
) -> str | None:
    for index in _term_indexes(token, "比"):
        before = _nearest_before(spans, index, window=12)
        after = _nearest_after(spans, index + 1, window=12)
        has_positive_after = _has_positive_after(token, index, positive_terms)
        if before and after and has_positive_after:
            return before[0]
        if after and has_positive_after:
            return post_brand if after[0] != post_brand else None

    for term in ("比較", "較"):
        for index in _term_indexes(token, term):
            before = _nearest_before(spans, index, window=10)
            after = _nearest_after(spans, index + len(term), window=10)
            if before and _has_positive_after(token, index, positive_terms):
                return before[0]
            if after and _has_positive_before(token, index, positive_terms):
                return after[0]
    return None


def _favored_by_still_pattern(
    token: str,
    spans: list[tuple[str, int, int]],
    positive_terms: tuple[str, ...],
) -> str | None:
    for term in ("還是", "還4"):
        for index in _term_indexes(token, term):
            after = _nearest_after(spans, index + len(term), window=12)
            if after and _has_positive_after(token, after[2], positive_terms):
                return after[0]
    for term in ("沒有", "沒"):
        for index in _term_indexes(token, term):
            after = _nearest_after(spans, index + len(term), window=12)
            if after and _has_positive_after(token, after[2], positive_terms):
                return after[0]
    return None


def _favored_by_win_loss(
    token: str,
    spans: list[tuple[str, int, int]],
    post_brand: str,
) -> str | None:
    for term in ("輸", "不如"):
        for index in _term_indexes(token, term):
            after = _nearest_after(spans, index + len(term), window=12)
            if after:
                return after[0]
    for term in ("贏", "勝過", "屌打", "勝"):
        for index in _term_indexes(token, term):
            before = _nearest_before(spans, index, window=12)
            if before:
                return before[0]
            after = _nearest_after(spans, index + len(term), window=12)
            if after:
                return post_brand
    return None


def _favored_by_nearby_positive(
    token: str,
    spans: list[tuple[str, int, int]],
    positive_terms: tuple[str, ...],
) -> str | None:
    candidates: list[tuple[int, str]] = []
    for term in positive_terms:
        for index in _term_indexes(token, term):
            for brand, start, end in spans:
                distance = min(abs(index - end), abs(start - (index + len(term))))
                if distance <= 8:
                    candidates.append((distance, brand))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    closest_distance = candidates[0][0]
    closest_brands = {brand for distance, brand in candidates if distance == closest_distance}
    if len(closest_brands) == 1:
        return next(iter(closest_brands))
    return None

def _competitor_stats(posts: list[Post]) -> tuple[int, int, int, list[str]]:
    mentioned_count = 0
    preferred_count = 0
    own_preferred_count = 0
    brand_counter: Counter[str] = Counter()
    for post in posts:
        for comment in post.comments:
            attribution = _comment_attribution(post.brand, comment)
            if not attribution.competitor_brands:
                continue
            mentioned_count += 1
            brand_counter.update(attribution.competitor_brands)
            if attribution.competitor_preference:
                preferred_count += 1
            elif attribution.own_preference:
                own_preferred_count += 1
    brands = [brand for brand, _ in sorted(brand_counter.items(), key=lambda item: (-item[1], item[0]))]
    return mentioned_count, preferred_count, own_preferred_count, brands


def _all_brand_spans(text: str, brands: tuple[str, ...]) -> list[tuple[str, int, int]]:
    spans: list[tuple[str, int, int]] = []
    for brand in brands:
        spans.extend((brand, start, end) for start, end in _brand_positions(text, brand))
    spans.sort(key=lambda item: (item[1], -(item[2] - item[1]), item[0]))
    return spans


def _brand_positions(text: str, brand: str) -> list[tuple[int, int]]:
    token = _text_token(text)
    positions: list[tuple[int, int]] = []
    for alias in _brand_aliases(brand):
        alias_token = _text_token(alias)
        if not alias_token:
            continue
        start = 0
        while True:
            index = token.find(alias_token, start)
            if index < 0:
                break
            positions.append((index, index + len(alias_token)))
            start = index + max(1, len(alias_token))
    return sorted(set(positions))


def _brand_aliases(brand: str) -> list[str]:
    canonical = _canonical_brand(brand)
    aliases = [canonical, *BRANDS.get(canonical, [])]
    return sorted({alias for alias in aliases if alias}, key=len, reverse=True)


def _canonical_brand(value: str) -> str:
    token = _text_token(value)
    for brand, aliases in BRANDS.items():
        if token in {_text_token(alias) for alias in [brand, *aliases] if alias}:
            return brand
    return str(value).strip()


def _text_token(value: str) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).casefold()


def _positive_terms() -> tuple[str, ...]:
    terms = [*BRAND_COMPARISON["positive_nearby_terms"], *POSITIVE_WORDS.keys()]
    return tuple(sorted({_text_token(term) for term in terms if term}, key=len, reverse=True))


def _term_indexes(text: str, term: str) -> list[int]:
    token = _text_token(term)
    indexes: list[int] = []
    start = 0
    while token:
        index = text.find(token, start)
        if index < 0:
            return indexes
        indexes.append(index)
        start = index + len(token)
    return indexes


def _nearest_before(
    spans: list[tuple[str, int, int]],
    index: int,
    *,
    window: int,
) -> tuple[str, int, int] | None:
    candidates = [span for span in spans if span[2] <= index and index - span[2] <= window]
    return max(candidates, key=lambda span: span[2], default=None)


def _nearest_after(
    spans: list[tuple[str, int, int]],
    index: int,
    *,
    window: int,
) -> tuple[str, int, int] | None:
    candidates = [span for span in spans if span[1] >= index and span[1] - index <= window]
    return min(candidates, key=lambda span: span[1], default=None)


def _has_positive_after(text: str, index: int, positive_terms: tuple[str, ...], *, window: int = 12) -> bool:
    fragment = text[index : index + window]
    return any(term in fragment for term in positive_terms)


def _has_positive_before(text: str, index: int, positive_terms: tuple[str, ...], *, window: int = 12) -> bool:
    fragment = text[max(0, index - window) : index]
    return any(term in fragment for term in positive_terms)


def _weighted_mean(pairs: list[tuple[float, float]]) -> float:
    total_weight = sum(weight for _, weight in pairs)
    return sum(value * weight for value, weight in pairs) / total_weight if total_weight else 0.0


def _weighted_std(pairs: list[tuple[float, float]], mu: float) -> float:
    total_weight = sum(weight for _, weight in pairs)
    if total_weight <= 0:
        return 0.0
    variance = sum(weight * (value - mu) ** 2 for value, weight in pairs) / total_weight
    return math.sqrt(max(0.0, variance))


def _n_eff(weights: list[float]) -> float:
    s1 = sum(weights)
    s2 = sum(weight * weight for weight in weights)
    return (s1 * s1 / s2) if s2 > 0 else 0.0


def _confidence(n_eff: float) -> str:
    for threshold, label in CONFIDENCE_BANDS:
        if n_eff < threshold:
            return label
    return "高"


def _classify(mu: float, std: float, n_eff: float) -> str:
    if n_eff < float(CONSENSUS["n_eff_min"]):
        return "資料不足"
    if std >= float(CONSENSUS["high_std"]):
        return "評價兩極"
    if mu >= float(CONSENSUS["high_mean"]) and std <= float(CONSENSUS["low_std"]):
        return "一致好評"
    if mu <= float(CONSENSUS["low_mean"]) and std <= float(CONSENSUS["low_std"]):
        return "一致負評"
    return "褒貶不一"


def _decay(posted_at: datetime | None, now: datetime | None = None) -> float:
    lam = float(SCORING["time_decay_lambda"])
    if lam <= 0 or posted_at is None:
        return 1.0
    now = now or datetime.now(timezone.utc)
    if posted_at.tzinfo is None:
        posted_at = posted_at.replace(tzinfo=timezone.utc)
    days = max(0.0, (now - posted_at).total_seconds() / 86400.0)
    return math.exp(-lam * days)


def _commenter_pairs(
    posts: list[Post],
    profiles: dict[str, AccountProfile],
) -> tuple[list[tuple[float, float]], list[Contributor]]:
    role_weight = float(SCORING["role_weight"]["commenter"])
    per_user: dict[str, list[tuple[float, float]]] = defaultdict(list)

    for post in posts:
        for comment in post.comments:
            if comment.sentiment is None:
                continue
            if SCORING["exclude_self_push"] and comment.user == post.author:
                continue
            if _OFF_TOPIC_COMMENT_RE.search(comment.text):
                continue
            if _is_reaction_echo_comment(comment.text):
                continue
            attribution = _comment_attribution(post.brand, comment)
            if not attribution.include_score or attribution.effective_sentiment is None:
                continue
            score01 = (attribution.effective_sentiment + 1.0) / 2.0
            credibility = profiles.get(comment.user).credibility if comment.user in profiles else 1.0
            weight = max(0.0, credibility * role_weight * _decay(comment.posted_at or post.posted_at))
            per_user[comment.user].append((score01, weight))

    pairs: list[tuple[float, float]] = []
    contributors: list[Contributor] = []
    for user, values in per_user.items():
        if SCORING["per_user_cap"]:
            stance = mean(score for score, _ in values)
            weight = mean(weight for _, weight in values)
            pairs.append((stance, weight))
            contributors.append(Contributor(user, "commenter", round(stance, 4), round(weight, 4)))
        else:
            for score, weight in values:
                pairs.append((score, weight))
                contributors.append(Contributor(user, "commenter", round(score, 4), round(weight, 4)))
    return pairs, contributors


def _author_pairs(posts: list[Post]) -> tuple[list[tuple[float, float]], list[Contributor]]:
    role_weight = float(SCORING["role_weight"]["author"])
    pairs: list[tuple[float, float]] = []
    contributors: list[Contributor] = []
    for post in posts:
        if post.author_score is None:
            continue
        score01 = max(0.0, min(1.0, post.author_score / 100.0))
        weight = role_weight * _decay(post.posted_at)
        pairs.append((score01, weight))
        contributors.append(Contributor(post.author, "author", round(score01, 4), round(weight, 4)))
    return pairs, contributors


def _is_shill_comment(text: str) -> bool:
    """判斷留言是否在喊「業配」。排除茶葉蛋等誤判。"""
    for fp in SHILL_DETECTION["false_positive_contexts"]:
        if fp in text:
            return False
    for kw in SHILL_DETECTION["keywords"]:
        if kw in text:
            return True
    return False


def _shill_stats(posts: list[Post]) -> tuple[float, bool]:
    """計算貼文群組的業配喊聲比例與是否標記。"""
    total = 0
    shill_count = 0
    for post in posts:
        for comment in post.comments:
            if not comment.text.strip():
                continue
            total += 1
            if _is_shill_comment(comment.text):
                shill_count += 1
    if total < int(SHILL_DETECTION["min_comments"]):
        return 0.0, False
    ratio = shill_count / total
    flag = ratio >= float(SHILL_DETECTION["ratio_threshold"])
    return round(ratio, 4), flag


def score_product(posts: list[Post], profiles: dict[str, AccountProfile]) -> ProductReport:
    """計算單一商品彙整分數。"""
    if not posts:
        raise ValueError("score_product requires at least one post")

    mu0 = float(SCORING["prior_mean"])
    prior_strength = float(SCORING["prior_strength"])
    shill_ratio, shill_flag = _shill_stats(posts)
    shill_penalty = float(SHILL_DETECTION["post_weight_penalty"]) if shill_flag else 1.0

    author_pairs, author_contributors = _author_pairs(posts)
    commenter_pairs, commenter_contributors = _commenter_pairs(posts, profiles)
    opinion_pairs = author_pairs + commenter_pairs

    if shill_flag and opinion_pairs:
        opinion_pairs = [(score, weight * shill_penalty) for score, weight in opinion_pairs]

    if opinion_pairs:
        weighted_sum = sum(score * weight for score, weight in opinion_pairs)
        weight_sum = sum(weight for _, weight in opinion_pairs)
        fair01 = (prior_strength * mu0 + weighted_sum) / (prior_strength + weight_sum)
        mean01 = _weighted_mean(opinion_pairs)
        std = _weighted_std(opinion_pairs, mean01)
        n_eff = _n_eff([weight for _, weight in opinion_pairs])
    else:
        fair01 = None
        mean01 = 0.0
        std = 0.0
        n_eff = 0.0

    contributors = sorted(author_contributors + commenter_contributors, key=lambda c: -c.weight)
    rep_pos, rep_neg = _rep_comments(posts)
    product_name = representative_product_name(posts)
    product_key = f"{posts[0].brand}:{normalize_product(posts[0].brand, product_name)}"
    (
        competitor_mention_count,
        competitor_preference_count,
        competitor_own_preference_count,
        competitor_brands,
    ) = _competitor_stats(posts)
    review_excerpt = _load_review_excerpt_overrides().get(product_key) or _review_excerpt(posts)

    post_dates = [p.posted_at for p in posts if p.posted_at]
    latest_post_date = max(post_dates) if post_dates else None
    priced_posts = [p for p in posts if p.price and p.price.isdigit()]
    latest_priced_post = max(priced_posts, key=lambda p: p.posted_at or datetime.min, default=None)
    price = int(latest_priced_post.price) if latest_priced_post is not None and latest_priced_post.price else None
    post_urls = sorted({p.url for p in posts if p.url})

    return ProductReport(
        brand=posts[0].brand,
        product_name=product_name,
        fair_score=round(fair01 * 100.0, 1) if fair01 is not None else None,
        consensus=_classify(mean01, std, n_eff),
        confidence=_confidence(n_eff),
        n_eff=round(n_eff, 2),
        score_std=round(std, 3),
        n_posts=len(posts),
        n_comments=sum(len(post.comments) for post in posts),
        contributors=contributors,
        rep_positive=rep_pos,
        rep_negative=rep_neg,
        product_key=product_key,
        score_mean=round(mean01, 4),
        price=price,
        category=categorize_product(product_name),
        competitor_mention_count=competitor_mention_count,
        competitor_preference_count=competitor_preference_count,
        competitor_own_preference_count=competitor_own_preference_count,
        competitor_brands=competitor_brands,
        shill_ratio=shill_ratio,
        shill_flag=shill_flag,
        latest_post_date=latest_post_date,
        review_excerpt=review_excerpt,
        post_urls=post_urls,
    )


_EXCERPT_DROP_RE = re.compile(
    r"^\s*(?:https?://|[（(]?區域型商品|試吃試用品|[-—─＝=]{2,}|※|◎|●|▲|Sent from|發信站|文章網址|批踢踢|˙|·)"
)
_EXCERPT_LABEL_RE = re.compile(r"^\s*[【\[]?\s*(?:心得|商品名稱|商品|便利商店|廠商名稱|價格|評分|分數|口味)\s*[】\]]?\s*[:：]")
_EXCERPT_SENTENCE_RE = re.compile(r"[^。！？!?；;\n]+[。！？!?；;]?")
_EXCERPT_SIGNATURE_RE = re.compile(r"^\s*(?:--+|Sent from|※\s*發信站|發信站|文章網址)", re.IGNORECASE)
_EXCERPT_INTRO_RE = re.compile(r"(今天|昨天|之前|記得|原本|剛剛|下班|路過|逛到|看到|買來|入手|開箱|分享|先上圖)")
_EXCERPT_FIRST_HAND_RE = re.compile(r"(我|自己|吃起來|喝起來|入口|咬下|回購|再買|不會再買)")
_EXCERPT_SENTENCE_START_RE = re.compile(
    r"^(?:味道|口感|整體|價格|價位|份量|吃起來|喝起來|我自己|我覺得|建議|另外|而且|重要的是)"
)
_EXCERPT_DECISION_TERMS = (
    "回購",
    "再買",
    "不會再買",
    "推薦",
    "不推",
    "值得",
    "可以試",
    "不值得",
    "耐吃",
)
_EXCERPT_ASPECT_TERMS: dict[str, tuple[str, ...]] = {
    "taste": ("味道", "口味", "甜", "鹹", "酸", "苦", "辣", "香", "濃", "淡", "膩", "奶味", "茶味", "咖啡味"),
    "texture": ("口感", "軟", "硬", "脆", "酥", "滑順", "綿密", "濕潤", "乾", "柴", "嫩", "Q彈", "嚼勁"),
    "portion": ("份量", "內容量", "大小", "飽足", "吃不飽", "給得多", "給的多", "太少"),
    "value": ("價格", "價位", "划算", "便宜", "偏貴", "太貴", "CP值", "cp值"),
    "preparation": ("加熱", "微波", "冷藏", "退冰", "融化", "冰過", "熱熱吃", "冷冷吃"),
    "comparison": ("比較像", "比起", "不如", "勝過", "還原度", "類似", "更好吃", "比較好"),
}

DEFAULT_REVIEW_EXCERPT_OVERRIDES_PATH = "data/labels/review_excerpt_batch_scored.csv"


@lru_cache(maxsize=4)
def _load_review_excerpt_overrides(path: str = DEFAULT_REVIEW_EXCERPT_OVERRIDES_PATH) -> dict[str, str]:
    """載入 Codex 節錄覆寫表（product_key -> 節錄）。檔案不存在時回傳空字典。"""
    file_path = Path(path)
    if not file_path.exists():
        return {}
    overrides: dict[str, str] = {}
    with open(file_path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            key = (row.get("product_key") or "").strip()
            excerpt = (row.get("節錄") or "").strip()
            if key and excerpt:
                overrides[key] = excerpt
    return overrides


@dataclass(frozen=True, slots=True)
class _ReviewCandidate:
    text: str
    score: float
    aspects: frozenset[str]
    post_index: int
    sentence_index: int


def _review_excerpt(posts: list[Post], max_len: int = 180, max_sentences: int = 3) -> str:
    """Select diverse, purchase-relevant sentences from every author review."""

    candidates = _review_candidates(posts)
    selected: list[_ReviewCandidate] = []
    covered_aspects: set[str] = set()

    while candidates and len(selected) < max_sentences:
        ranked = sorted(
            candidates,
            key=lambda item: (
                -(item.score + 2.0 * len(item.aspects - covered_aspects)),
                item.post_index,
                item.sentence_index,
                item.text,
            ),
        )
        chosen = None
        for candidate in ranked:
            if any(_review_sentences_similar(candidate.text, item.text) for item in selected):
                continue
            rendered = _render_review_sentences([*selected, candidate])
            if len(rendered) <= max_len:
                chosen = candidate
                break
        if chosen is None:
            break
        selected.append(chosen)
        covered_aspects.update(chosen.aspects)
        candidates.remove(chosen)

    return _render_review_sentences(selected)


def _review_candidates(posts: list[Post]) -> list[_ReviewCandidate]:
    candidates: list[_ReviewCandidate] = []
    ordered_posts = sorted(
        posts,
        key=lambda post: (post.posted_at.isoformat() if post.posted_at else "", post.id),
        reverse=True,
    )

    for post_index, post in enumerate(ordered_posts):
        for sentence_index, sentence in enumerate(_review_sentences(post.review_text)):
            compact = re.sub(r"\s+", "", sentence).casefold()
            aspects = frozenset(
                aspect
                for aspect, terms in _EXCERPT_ASPECT_TERMS.items()
                if any(term.casefold() in compact for term in terms)
            )
            decision_hits = sum(term.casefold() in compact for term in _EXCERPT_DECISION_TERMS)
            sentiment_hits = sum(
                term.casefold() in compact
                for term in {*POSITIVE_WORDS, *NEGATIVE_WORDS}
                if len(term) >= 2
            )
            if not aspects and not decision_hits and not sentiment_hits:
                continue

            score = 3.0 * len(aspects) + 2.5 * min(decision_hits, 2) + 1.25 * min(sentiment_hits, 3)
            if 12 <= len(sentence) <= 80:
                score += 1.0
            if _EXCERPT_FIRST_HAND_RE.search(sentence):
                score += 0.75
            if _EXCERPT_INTRO_RE.search(sentence):
                score -= 2.5
            if post.author_score is not None:
                score += min(abs(post.author_score - 50) / 50, 1.0)
            score += min(sentence_index, 10) * 0.05
            candidates.append(
                _ReviewCandidate(
                    text=sentence,
                    score=score,
                    aspects=aspects,
                    post_index=post_index,
                    sentence_index=sentence_index,
                )
            )
    return candidates


def _review_sentences(review_text: str) -> list[str]:
    sentences: list[str] = []
    text = unicodedata.normalize("NFKC", review_text or "")
    blocks: list[list[str]] = []
    block: list[str] = []

    def flush_block() -> None:
        if block:
            blocks.append(block.copy())
            block.clear()

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if _EXCERPT_SIGNATURE_RE.search(line):
            flush_block()
            break
        if not line:
            continue
        if _URL_RE.search(line) or _EXCERPT_DROP_RE.search(line):
            flush_block()
            continue
        line = _EXCERPT_LABEL_RE.sub("", line).strip()
        line = re.sub(r"\(\s*[?!？]?\s*\)", "", line)
        if len(line) >= 4:
            block.append(line)
    flush_block()

    for lines in blocks:
        sources = ["".join(lines)] if _looks_hard_wrapped(lines) else _merge_wrapped_review_lines(lines)
        for source in sources:
            for match in _EXCERPT_SENTENCE_RE.finditer(source):
                fragment = re.sub(r"\s+", " ", match.group(0)).strip(" ：:、-—─")
                for sentence in _chunk_review_fragment(fragment):
                    if 6 <= len(sentence) <= 140:
                        sentences.append(sentence)
    return sentences


def _looks_hard_wrapped(lines: list[str]) -> bool:
    if len(lines) < 4:
        return False
    common_length, count = Counter(len(line) for line in lines).most_common(1)[0]
    return common_length >= 10 and count >= 3 and count / len(lines) >= 0.5


def _merge_wrapped_review_lines(lines: list[str]) -> list[str]:
    if not lines:
        return []
    merged: list[str] = []
    current = lines[0]
    previous = lines[0]
    for line in lines[1:]:
        continues = previous.endswith((",", "，", "、", ":", "：")) or (
            len(previous) >= 28 and not re.search(r"[。！？!?；;)）]$", previous)
        )
        if continues:
            separator = "。" if _EXCERPT_SENTENCE_START_RE.search(line) else ""
            current += separator + line
        else:
            merged.append(current)
            current = line
        previous = line
    merged.append(current)
    return merged


def _chunk_review_fragment(fragment: str, target_len: int = 70) -> list[str]:
    if len(fragment) <= target_len:
        return [fragment]

    clauses = [clause.strip() for clause in re.split(r"[,，]", fragment) if clause.strip()]
    if len(clauses) <= 1:
        return [fragment]
    if len(clauses) >= 3 and _EXCERPT_INTRO_RE.search(clauses[0]):
        clauses = clauses[1:]

    chunks: list[str] = []
    current = ""
    for clause in clauses:
        candidate = f"{current},{clause}" if current else clause
        if current and len(candidate) > target_len and len(current) >= 18:
            chunks.append(current)
            current = clause
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def _review_sentences_similar(left: str, right: str) -> bool:
    left_key = re.sub(r"[^\w\u4e00-\u9fff]+", "", left).casefold()
    right_key = re.sub(r"[^\w\u4e00-\u9fff]+", "", right).casefold()
    if not left_key or not right_key:
        return False
    if left_key in right_key or right_key in left_key:
        return True
    return SequenceMatcher(None, left_key, right_key).ratio() >= 0.78


def _remove_unmatched_parentheses(text: str) -> str:
    """Drop stray parentheses while preserving the review text around them."""

    open_indexes: list[int] = []
    remove_indexes: set[int] = set()
    for index, char in enumerate(text):
        if char == "(":
            open_indexes.append(index)
        elif char == ")":
            if open_indexes:
                open_indexes.pop()
            else:
                remove_indexes.add(index)
    remove_indexes.update(open_indexes)
    return "".join(char for index, char in enumerate(text) if index not in remove_indexes)


def _render_review_sentences(candidates: list[_ReviewCandidate]) -> str:
    rendered = []
    for candidate in sorted(candidates, key=lambda item: (item.post_index, item.sentence_index)):
        sentence = _remove_unmatched_parentheses(candidate.text)
        sentence = sentence.replace(",", "，").strip("。！？!?；; ，")
        if sentence:
            rendered.append(f"{sentence}。")
    return " ".join(rendered)


def _rep_comments(posts: list[Post], k: int = 3) -> tuple[list[str], list[str]]:
    positive: list[tuple[float, str]] = []
    negative: list[tuple[float, str]] = []
    for post in posts:
        for comment in post.comments:
            if comment.sentiment is None or not comment.text.strip():
                continue
            attribution = _comment_attribution(post.brand, comment)
            if not attribution.include_score or attribution.effective_sentiment is None:
                continue
            if _OFF_TOPIC_COMMENT_RE.search(comment.text):
                continue
            if _is_reaction_echo_comment(comment.text):
                continue
            text = _clean_representative_comment(post.brand, comment.text)
            if not text:
                continue
            item = (attribution.effective_sentiment, text)
            if attribution.effective_sentiment > 0.2:
                positive.append(item)
            elif attribution.effective_sentiment < -0.2:
                negative.append(item)
    positive.sort(key=lambda item: -item[0])
    negative.sort(key=lambda item: item[0])
    return _dedupe_ranked_comments(positive, k), _dedupe_ranked_comments(negative, k)


def representative_product_name(posts: list[Post]) -> str:
    """選出代表性商品名稱。"""
    if not posts:
        return "unknown"
    names = [canonical_product_name(posts[0].brand, post.product_name) for post in posts]
    counts = Counter(names)
    return min(counts, key=lambda name: (-counts[name], -len(name), name))


def _clean_representative_comment(brand: str, text: str) -> str:
    s = unicodedata.normalize("NFKC", text or "").strip()
    for kw in sorted(set([*BRANDS.get(brand, []), brand]), key=len, reverse=True):
        if kw:
            # Only remove a store name when it is a label-like prefix. Brand names
            # inside a sentence carry meaning (e.g. "全家的甜品" / "我買全家的時候").
            pattern = rf"^{re.escape(kw)}(?=[\s:：])[\s:：]*"
            s = re.sub(pattern, "", s, count=1, flags=re.IGNORECASE)
    s = _BRACKET_RE.sub(" ", s)
    s = _COMMENT_NOISE_RE.sub(" ", s)
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"^[\s:：,，.。!！?？~～\-]+|[\s:：,，.。!！?？~～\-]+$", "", s)
    return s.strip()


def _dedupe_ranked_comments(items: list[tuple[float, str]], k: int) -> list[str]:
    selected: list[str] = []
    seen: set[str] = set()
    for _, text in items:
        key = re.sub(r"\s+", "", unicodedata.normalize("NFKC", text).casefold())
        if key in seen:
            continue
        seen.add(key)
        selected.append(text)
        if len(selected) >= k:
            break
    return selected


def score_all(posts: list[Post], profiles: dict[str, AccountProfile]) -> list[ProductReport]:
    """計算所有商品報告並排序。"""
    reports = [score_product(group, profiles) for group in group_products(posts).values()]
    reports.sort(
        key=lambda report: (
            report.fair_score is None,
            report.confidence == "低" or report.consensus == "資料不足",
            -(report.fair_score or 0.0),
        )
    )
    return reports
