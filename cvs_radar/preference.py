"""Account preference and weak suspicion signals for PRD F4."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from statistics import mean
import unicodedata

from .config import SUSPICION
from .models import Post


@dataclass(slots=True)
class BrandStat:
    count: int
    avg_sentiment: float


@dataclass(slots=True)
class AccountProfile:
    user: str
    source: str = "PTT"
    brand_stats: dict[str, BrandStat] = field(default_factory=dict)
    lean_brand: str | None = None
    suspicion_score: float = 0.0
    suspicion_features: dict[str, float] = field(default_factory=dict)
    credibility: float = 1.0
    total_comments: int = 0


def build_profiles(posts: list[Post]) -> dict[str, AccountProfile]:
    rows: dict[str, list[tuple[str, float, str]]] = defaultdict(list)
    timestamps: dict[str, dict[str, list[datetime]]] = defaultdict(lambda: defaultdict(list))
    for post in posts:
        for comment in post.comments:
            if comment.sentiment is None or not comment.user:
                continue
            rows[comment.user].append((post.brand, comment.sentiment, comment.text.strip()))
            if comment.posted_at is not None:
                timestamps[comment.user][post.brand].append(comment.posted_at)

    profiles: dict[str, AccountProfile] = {}
    for user, values in rows.items():
        by_brand: dict[str, list[float]] = defaultdict(list)
        texts: list[str] = []
        for brand, sentiment, text in values:
            by_brand[brand].append(sentiment)
            if text:
                texts.append(text)

        brand_stats = {
            brand: BrandStat(count=len(scores), avg_sentiment=round(mean(scores), 4))
            for brand, scores in by_brand.items()
        }
        lean_brand = max(brand_stats, key=lambda b: brand_stats[b].avg_sentiment, default=None)
        features = _suspicion_features(by_brand, texts, timestamps.get(user, {}))
        suspicion = _weighted_suspicion(features, len(values))
        credibility = max(float(SUSPICION["weight_floor"]), 1.0 - suspicion)
        profiles[user] = AccountProfile(
            user=user,
            brand_stats=brand_stats,
            lean_brand=lean_brand,
            suspicion_score=round(suspicion, 4),
            suspicion_features=features,
            credibility=round(credibility, 4),
            total_comments=len(values),
        )
    return profiles


def _suspicion_features(
    by_brand: dict[str, list[float]],
    texts: list[str],
    brand_timestamps: dict[str, list[datetime]] | None = None,
) -> dict[str, float]:
    total = sum(len(v) for v in by_brand.values())
    if total < int(SUSPICION["min_activity"]):
        return {}

    brand_means = {brand: mean(scores) for brand, scores in by_brand.items()}
    positive_brand = max(brand_means, key=brand_means.get)
    pos = max(0.0, brand_means[positive_brand])
    competitors = [v for b, v in brand_means.items() if b != positive_brand]
    competitor_neg = abs(min(0.0, mean(competitors))) if competitors else 0.0

    dominant_count = max((len(v) for v in by_brand.values()), default=0)
    all_scores = [s for scores in by_brand.values() for s in scores]
    extreme_ratio = sum(1 for s in all_scores if abs(s) >= 0.85) / total
    template_ratio = _template_like_ratio(texts)
    burst_ratio = _burst_ratio(brand_timestamps or {})

    return {
        "one_sided": round(min(1.0, (pos + competitor_neg) / 2.0), 4),
        "single_brand": round(dominant_count / total if total else 0.0, 4),
        "extreme": round(extreme_ratio, 4),
        "template_like": round(template_ratio, 4),
        "burst": round(burst_ratio, 4),
    }


def _weighted_suspicion(features: dict[str, float], total: int) -> float:
    if total < int(SUSPICION["min_activity"]) or not features:
        return 0.0
    weights = SUSPICION["feature_weights"]
    return max(0.0, min(1.0, sum(features.get(k, 0.0) * w for k, w in weights.items())))


def _template_like_ratio(texts: list[str]) -> float:
    eligible = _eligible_template_texts(texts)
    if len(eligible) < 3:
        return 0.0
    flagged = _template_like_indices(texts)
    eligible_indices = {index for index, _ in eligible}
    return len(flagged & eligible_indices) / len(eligible)


def _burst_ratio(brand_timestamps: dict[str, list[datetime]]) -> float:
    total = sum(len(timestamps) for timestamps in brand_timestamps.values())
    if total == 0:
        return 0.0
    burst_count = 0
    for timestamps in brand_timestamps.values():
        burst_count += len(_burst_indices(timestamps))
    return burst_count / total


def _template_like_indices(texts: list[str]) -> set[int]:
    eligible = _eligible_template_texts(texts)
    if len(eligible) < 3:
        return set()

    parent = list(range(len(eligible)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    normalized = [text for _, text in eligible]
    bigrams = [_char_bigrams(text) for text in normalized]
    for left in range(len(eligible)):
        for right in range(left + 1, len(eligible)):
            if normalized[left] == normalized[right] or _jaccard(bigrams[left], bigrams[right]) >= 0.8:
                union(left, right)

    groups: dict[int, list[int]] = defaultdict(list)
    for local_index, (original_index, _) in enumerate(eligible):
        groups[find(local_index)].append(original_index)

    flagged: set[int] = set()
    for group in groups.values():
        if len(group) > 1:
            flagged.update(group)
    return flagged


def _burst_indices(timestamps: list[datetime]) -> set[int]:
    min_count = int(SUSPICION["burst_min_count"])
    if min_count <= 1:
        return set(range(len(timestamps)))
    if len(timestamps) < min_count:
        return set()

    window = timedelta(hours=float(SUSPICION["burst_window_hours"]))
    ordered = sorted(enumerate(timestamps), key=lambda item: item[1])
    flagged: set[int] = set()
    right = 0
    for left, (_, left_time) in enumerate(ordered):
        while right < len(ordered) and ordered[right][1] - left_time <= window:
            right += 1
        if right - left >= min_count:
            flagged.update(original_index for original_index, _ in ordered[left:right])
    return flagged


def _eligible_template_texts(texts: list[str]) -> list[tuple[int, str]]:
    eligible: list[tuple[int, str]] = []
    for index, text in enumerate(texts):
        normalized = _normalize_template_text(text)
        if len(normalized) > 3:
            eligible.append((index, normalized))
    return eligible


def _normalize_template_text(text: str) -> str:
    return "".join(
        char
        for char in text
        if not char.isspace() and not unicodedata.category(char).startswith("P")
    )


def _char_bigrams(text: str) -> set[str]:
    if len(text) < 2:
        return {text} if text else set()
    return {text[index : index + 2] for index in range(len(text) - 1)}


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 1.0
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)
