"""Shared imports and module-level constants for the scoring package."""
from __future__ import annotations

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
from ..config import (
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
from ..filters import normalize_datetime
from ..models import Comment, Contributor, Post, ProductReport
from ..parser import _title_product_name, brand_alias_positions
from ..preference import AccountProfile
from ..sentiment import NEGATIVE_WORDS, POSITIVE_WORDS


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

_PARALLEL_PRODUCT_SUFFIXES = (
    "三明治", "御飯糰", "飯糰", "便當", "軟歐", "貝果", "可頌", "餐包",
    "蛋餅", "義大利麵", "霜淇淋", "冰淇淋", "布丁", "泡芙", "蛋糕",
    "拉麵", "麵包", "吐司", "土司",
)

_SHARED_SAME_PRICE_RE = re.compile(
    r"^\s*(?P<names>.+?)\s*(?:[/／]\s*)?(?:都|各)\s*(?P<price>\d{2,3})\s*(?:元)?\s*\$?\s*$"
)

_SHARED_FLAVOR_RE = re.compile(
    r"(?P<prefix>[^-－/／]{2,}?)[-－]"
    r"(?P<flavors>[^-－/／]*?、[^-－/／]*?)"
    r"(?P<marker>雙風味|雙口味|雙口感|兩種口味|兩款口味)"
)

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

_TRAILING_NOISE_CLEAN_RE = re.compile(
    r"\d{2,3}(?:ibon|\u7968\u5238|[xX\u00d7]|\u6298|\u4ef6|\u9ede|\u74f6|\u676f|\u91d1).*$"
)

_TRAILING_PRICE_CLEAN_RE = re.compile(r"\d{1,3}$")

_TRAILING_FILLER_RE = re.compile(
    r"(?:\u5617\u9bae\u50f9|\u5690\u9bae\u50f9|\u534a\u50f9|\u55ae\u4ef6|\u50f9|\u90fd|\u4e00|\u7684|\u819b)$"
)

_AUTHORITATIVE_BACKENDS = frozenset({"llm-backfill", "codex"})

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


__all__ = ['AccountProfile', 'BRANDS', 'BRAND_COMPARISON', 'CONFIDENCE_BANDS', 'CONSENSUS', 'Comment', 'Contributor', 'Counter', 'DEFAULT_REVIEW_EXCERPT_OVERRIDES_PATH', 'NEGATIVE_WORDS', 'POSITIVE_WORDS', 'PRODUCT_ALIASES', 'PRODUCT_CATEGORIES', 'PRODUCT_NORMALIZATION', 'Path', 'Post', 'ProductReport', 'SCORING', 'SHILL_DETECTION', 'SequenceMatcher', '_AUTHORITATIVE_BACKENDS', '_BRACKET_RE', '_BUNDLE_PRICE_RE', '_BUNDLE_PRICE_SUFFIX_RE', '_CATEGORY_STRONG_KEYWORDS', '_COMMENT_NOISE_RE', '_DISTINCTIVE_TERMS', '_EXCERPT_ASPECT_TERMS', '_EXCERPT_DECISION_TERMS', '_EXCERPT_DROP_RE', '_EXCERPT_FIRST_HAND_RE', '_EXCERPT_INTRO_RE', '_EXCERPT_LABEL_RE', '_EXCERPT_SENTENCE_RE', '_EXCERPT_SENTENCE_START_RE', '_EXCERPT_SIGNATURE_RE', '_FIRST_HAND_COMMENT_RE', '_FRAGMENT_PRODUCT_NAMES', '_GARBAGE_NAME_RE', '_GENERIC_CATEGORY_KEYWORDS', '_MAX_PRICE', '_MIN_PRICE', '_MULTI_PRODUCT_RE', '_NOISE_RE', '_OFF_TOPIC_COMMENT_RE', '_OPTIONAL_RE', '_PARALLEL_PRODUCT_SUFFIXES', '_PAYMENT_ASIDE_PATTERN', '_PRICE_BEFORE_PROMO_RE', '_PRICE_CONTEXT_RE', '_PRICE_TOKEN_RE', '_PRODUCT_FORM_TERMS', '_PRODUCT_REVIEW_START_RE', '_PROMO_RE', '_PROMO_SUFFIX_RE', '_PROMO_TAIL_RE', '_PTT_PRODUCT_TEMPLATE', '_QUANTITY_SUFFIX_RE', '_REACTION_ECHO_RE', '_SHARED_FLAVOR_RE', '_SHARED_SAME_PRICE_RE', '_SYNONYM_MAP', '_TITLE_PREFIX_RE', '_TRAILING_FILLER_RE', '_TRAILING_NOISE_CLEAN_RE', '_TRAILING_PRICE_CLEAN_RE', '_TRAILING_PRICE_RE', '_URL_RE', '_title_product_name', 'annotations', 'brand_alias_positions', 'csv', 'dataclass', 'datetime', 'defaultdict', 'lru_cache', 'math', 'mean', 'normalize_datetime', 're', 'timezone', 'unicodedata']
