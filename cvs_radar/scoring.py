"""Fair score aggregation and consensus classification for PRD F5/F6/§8."""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from statistics import mean

from .config import (
    BRAND_COMPARISON,
    BRANDS,
    CONFIDENCE_BANDS,
    CONSENSUS,
    PRODUCT_ALIASES,
    PRODUCT_NORMALIZATION,
    SCORING,
)
from .models import Comment, Contributor, Post, ProductReport
from .preference import AccountProfile
from .sentiment import POSITIVE_WORDS


_BRACKET_RE = re.compile(r"[\[\(（【].*?[\]\)）】]")
_TITLE_PREFIX_RE = re.compile(r"^\s*(商品|心得|情報|問題|請益|討論|問卦)\s*")
_NOISE_RE = re.compile(
    r"(心得|開箱|踩雷|地雷|評價|回購|好吃嗎|好不好吃|分享|請益|請問|詢問|"
    r"推薦|推不推|反推|實測|試吃|食記|簡評|小心得)"
)
_OPTIONAL_RE = re.compile(
    r"(\d+(\.\d+)?\s*(入|包|個|顆|片|枚|杯|瓶|罐|盒|組|ml|毫升|g|公克|克)|"
    r"(口味|數量|容量|規格|加量|限定|新品|新上市))"
)
_COMMENT_NOISE_RE = re.compile(r"(這款|這個|這品|這次|個人覺得|我覺得|覺得|補充[:：]?|推薦|推推|再推一次)")
_DISTINCTIVE_TERMS = {
    "原味",
    "辣",
    "麻辣",
    "起司",
    "乳酪",
    "巧克力",
    "可可",
    "草莓",
    "抹茶",
    "咖啡",
    "奶茶",
    "香草",
    "焦糖",
    "蜂蜜",
    "海鹽",
    "檸檬",
    "藍莓",
    "芋頭",
    "花生",
    "芝麻",
    "紅豆",
    "綠豆",
    "牛肉",
    "豬肉",
    "雞肉",
    "鮪魚",
    "鮭魚",
}


@dataclass(frozen=True, slots=True)
class _CommentAttribution:
    include_score: bool
    effective_sentiment: float | None
    competitor_brands: tuple[str, ...] = ()
    competitor_preference: bool = False


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
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"[^\w\u4e00-\u9fff]+", "", s)
    return s or "unknown"


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
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"[^\w\u4e00-\u9fff]+", "", s)
    return s or "unknown"


def _compact_key(name: str) -> str:
    s = unicodedata.normalize("NFKC", name or "").casefold()
    s = re.sub(r"[\s　]+", "", s)
    s = re.sub(r"[^\w\u4e00-\u9fff]+", "", s)
    return s or "unknown"


def group_products(posts: list[Post]) -> dict[tuple[str, str], list[Post]]:
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
        positive_floor = float(BRAND_COMPARISON.get("own_brand_positive_floor", 0.4))
        effective = max(sentiment if sentiment is not None else 0.0, positive_floor)
        return _CommentAttribution(True, effective, other_brands, competitor_preference=False)

    return _CommentAttribution(False, sentiment, other_brands, competitor_preference=True)


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

def _competitor_stats(posts: list[Post]) -> tuple[int, int, list[str]]:
    mentioned_count = 0
    preferred_count = 0
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
    brands = [brand for brand, _ in sorted(brand_counter.items(), key=lambda item: (-item[1], item[0]))]
    return mentioned_count, preferred_count, brands


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


def score_product(posts: list[Post], profiles: dict[str, AccountProfile]) -> ProductReport:
    if not posts:
        raise ValueError("score_product requires at least one post")

    mu0 = float(SCORING["prior_mean"])
    prior_strength = float(SCORING["prior_strength"])
    author_pairs, author_contributors = _author_pairs(posts)
    commenter_pairs, commenter_contributors = _commenter_pairs(posts, profiles)
    opinion_pairs = author_pairs + commenter_pairs

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
    competitor_mention_count, competitor_preference_count, competitor_brands = _competitor_stats(posts)

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
        competitor_mention_count=competitor_mention_count,
        competitor_preference_count=competitor_preference_count,
        competitor_brands=competitor_brands,
    )


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
    if not posts:
        return "unknown"
    names = [canonical_product_name(posts[0].brand, post.product_name) for post in posts]
    counts = Counter(names)
    return min(counts, key=lambda name: (-counts[name], -len(name), name))


def _clean_representative_comment(brand: str, text: str) -> str:
    s = unicodedata.normalize("NFKC", text or "").strip()
    for kw in sorted(set([*BRANDS.get(brand, []), brand]), key=len, reverse=True):
        if kw:
            s = re.sub(re.escape(kw), " ", s, flags=re.IGNORECASE)
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
    reports = [score_product(group, profiles) for group in group_products(posts).values()]
    reports.sort(
        key=lambda report: (
            report.fair_score is None,
            report.confidence == "低" or report.consensus == "資料不足",
            -(report.fair_score or 0.0),
        )
    )
    return reports
