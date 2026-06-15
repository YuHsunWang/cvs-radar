"""Fair score aggregation and consensus classification for PRD F5/F6/§8."""

from __future__ import annotations

import math
import re
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from statistics import mean

from .config import BRANDS, CONFIDENCE_BANDS, CONSENSUS, SCORING
from .models import Contributor, Post, ProductReport
from .preference import AccountProfile


def normalize_product(brand: str, name: str) -> str:
    """Remove brand prefixes, whitespace, and full-width variants."""
    s = unicodedata.normalize("NFKC", name or "").lower().strip()
    keywords = [k.lower() for k in BRANDS.get(brand, [])] + [brand.lower()]
    for kw in sorted(set(keywords), key=len, reverse=True):
        if kw:
            s = s.replace(kw, " ")
    s = re.sub(r"[\s　]+", "", s)
    s = re.sub(r"[^\w\u4e00-\u9fff]+", "", s)
    return s or "unknown"


def group_products(posts: list[Post]) -> dict[tuple[str, str], list[Post]]:
    groups: dict[tuple[str, str], list[Post]] = defaultdict(list)
    for post in posts:
        groups[(post.brand, normalize_product(post.brand, post.product_name))].append(post)
    return dict(groups)


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
            score01 = (comment.sentiment + 1.0) / 2.0
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
    product_key = f"{posts[0].brand}:{normalize_product(posts[0].brand, posts[0].product_name)}"

    return ProductReport(
        brand=posts[0].brand,
        product_name=posts[0].product_name,
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
    )


def _rep_comments(posts: list[Post], k: int = 3) -> tuple[list[str], list[str]]:
    positive: list[tuple[float, str]] = []
    negative: list[tuple[float, str]] = []
    for post in posts:
        for comment in post.comments:
            if comment.sentiment is None or not comment.text.strip():
                continue
            item = (comment.sentiment, comment.text.strip())
            if comment.sentiment > 0.2:
                positive.append(item)
            elif comment.sentiment < -0.2:
                negative.append(item)
    positive.sort(key=lambda item: -item[0])
    negative.sort(key=lambda item: item[0])
    return [text for _, text in positive[:k]], [text for _, text in negative[:k]]


def score_all(posts: list[Post], profiles: dict[str, AccountProfile]) -> list[ProductReport]:
    reports = [score_product(group, profiles) for group in group_products(posts).values()]
    reports.sort(key=lambda report: (report.fair_score is None, -(report.fair_score or 0.0)))
    return reports
