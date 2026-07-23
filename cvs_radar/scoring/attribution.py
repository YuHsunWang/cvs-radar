from __future__ import annotations

from __future__ import annotations
import unicodedata
from collections import Counter
from dataclasses import dataclass
from ..config import (
    BRAND_COMPARISON,
    BRANDS,
)
from ..models import Comment, Post
from ..parser import brand_alias_positions
from ..sentiment import POSITIVE_WORDS

from ._common import (_AUTHORITATIVE_BACKENDS, _FIRST_HAND_COMMENT_RE, _REACTION_ECHO_RE)


@dataclass(frozen=True, slots=True)
class _CommentAttribution:
    include_score: bool
    effective_sentiment: float | None
    competitor_brands: tuple[str, ...] = ()
    competitor_preference: bool = False
    own_preference: bool = False


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
    positions: list[tuple[int, int]] = []
    for alias in _brand_aliases(brand):
        positions.extend(brand_alias_positions(text, alias))
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
