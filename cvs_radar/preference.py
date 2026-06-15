"""Account preference and weak suspicion signals for PRD F4."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from statistics import mean

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
    for post in posts:
        for comment in post.comments:
            if comment.sentiment is None or not comment.user:
                continue
            rows[comment.user].append((post.brand, comment.sentiment, comment.text.strip()))

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
        features = _suspicion_features(by_brand, texts)
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


def _suspicion_features(by_brand: dict[str, list[float]], texts: list[str]) -> dict[str, float]:
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
    repeated_ratio = _repeated_text_ratio(texts)

    return {
        "one_sided": round(min(1.0, (pos + competitor_neg) / 2.0), 4),
        "single_brand": round(dominant_count / total if total else 0.0, 4),
        "extreme": round(extreme_ratio, 4),
        "repeated_text": round(repeated_ratio, 4),
    }


def _weighted_suspicion(features: dict[str, float], total: int) -> float:
    if total < int(SUSPICION["min_activity"]) or not features:
        return 0.0
    weights = SUSPICION["feature_weights"]
    return max(0.0, min(1.0, sum(features.get(k, 0.0) * w for k, w in weights.items())))


def _repeated_text_ratio(texts: list[str]) -> float:
    normalized = ["".join(t.split()) for t in texts if t]
    if len(normalized) < 3:
        return 0.0
    counts = Counter(normalized)
    repeated = sum(count for count in counts.values() if count > 1)
    return repeated / len(normalized)
