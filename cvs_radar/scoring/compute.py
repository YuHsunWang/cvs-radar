from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timezone
from statistics import mean
from ..config import (
    CONFIDENCE_BANDS,
    CONSENSUS,
    SCORING,
    SHILL_DETECTION,
)
from ..filters import normalize_datetime
from ..models import CommentOpinion, Contributor, Post, ProductReport
from ..preference import AccountProfile

from ._common import (_OFF_TOPIC_COMMENT_RE)
from .attribution import (_comment_attribution, _competitor_stats, _is_reaction_echo_comment)
from .excerpt import (_load_review_excerpt_overrides, _rep_comments, _review_excerpt, representative_product_name)
from .identity import (categorize_product, group_products, normalize_product)


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
    current = normalize_datetime(now or datetime.now(timezone.utc))
    posted_at = normalize_datetime(posted_at)
    days = max(0.0, (current - posted_at).total_seconds() / 86400.0)
    return math.exp(-lam * days)


def build_comment_opinions(
    posts: list[Post],
) -> dict[tuple[str, int], CommentOpinion]:
    """Decide eligibility and target attribution once for profiles and scoring."""
    opinions: dict[tuple[str, int], CommentOpinion] = {}
    for post in posts:
        for index, comment in enumerate(post.comments):
            include = comment.sentiment is not None and bool(comment.user)
            if include and SCORING["exclude_self_push"] and comment.user == post.author:
                include = False
            if include and _OFF_TOPIC_COMMENT_RE.search(comment.text):
                include = False
            if include and _is_reaction_echo_comment(comment.text):
                include = False
            attribution = _comment_attribution(post.brand, comment)
            include = bool(
                include
                and attribution.include_score
                and attribution.effective_sentiment is not None
            )
            opinions[(post.id, index)] = CommentOpinion(
                include_score=include,
                effective_sentiment=(
                    attribution.effective_sentiment if include else None
                ),
            )
    return opinions


def _commenter_contributions(
    posts: list[Post],
    profiles: dict[str, AccountProfile],
    now: datetime | None = None,
    opinions: dict[tuple[str, int], CommentOpinion] | None = None,
) -> list[tuple[str, str, float, float]]:
    """One (user, role, score01, weight) row per eligible comment."""
    role_weight = float(SCORING["role_weight"]["commenter"])
    rows: list[tuple[str, str, float, float]] = []
    opinions = opinions or build_comment_opinions(posts)
    for post in posts:
        for index, comment in enumerate(post.comments):
            opinion = opinions[(post.id, index)]
            if not opinion.include_score or opinion.effective_sentiment is None:
                continue
            score01 = (opinion.effective_sentiment + 1.0) / 2.0
            credibility = _credibility(profiles, comment.user)
            weight = max(
                0.0,
                credibility * role_weight * _decay(comment.posted_at or post.posted_at, now),
            )
            rows.append((comment.user, "commenter", score01, weight))
    return rows


def _author_contributions(
    posts: list[Post],
    profiles: dict[str, AccountProfile],
    now: datetime | None = None,
) -> list[tuple[str, str, float, float]]:
    """One (user, role, score01, weight) row per scored post."""
    role_weight = float(SCORING["role_weight"]["author"])
    rows: list[tuple[str, str, float, float]] = []
    for post in posts:
        if post.author_score is None:
            continue
        score01 = max(0.0, min(1.0, post.author_score / 100.0))
        # An author is the same human as a commenter, so the same credibility and
        # the same per-user cap apply. Leaving authors uncapped let one account post
        # ten reviews of one product and carry ten full votes.
        weight = max(0.0, _credibility(profiles, post.author) * role_weight * _decay(post.posted_at, now))
        rows.append((post.author, "author", score01, weight))
    return rows


def _credibility(profiles: dict[str, AccountProfile], user: str) -> float:
    profile = profiles.get(user)
    return profile.credibility if profile is not None else 1.0


def _opinion_pairs(
    posts: list[Post],
    profiles: dict[str, AccountProfile],
    now: datetime | None = None,
    opinions: dict[tuple[str, int], CommentOpinion] | None = None,
) -> tuple[list[tuple[float, float]], list[Contributor]]:
    """Collapse every contribution to one stance per human when per_user_cap is set.

    Authors and commenters are pooled by account first: `per_user_cap` is meant to
    stop one person outvoting a product, and a person who reviews a product and also
    pushes someone else's thread about it is still one person.
    """
    per_user: dict[str, list[tuple[str, float, float]]] = defaultdict(list)
    for user, role, score01, weight in (
        _author_contributions(posts, profiles, now)
        + _commenter_contributions(posts, profiles, now, opinions)
    ):
        per_user[user].append((role, score01, weight))

    pairs: list[tuple[float, float]] = []
    contributors: list[Contributor] = []
    for user, values in per_user.items():
        if not SCORING["per_user_cap"]:
            for role, score, weight in values:
                pairs.append((score, weight))
                contributors.append(Contributor(user, role, round(score, 4), round(weight, 4)))
            continue
        # Weight each of the person's own opinions by its decay before collapsing
        # them. An unweighted mean lets a 200-day-old push cancel today's complaint
        # outright, which is the opposite of what time_decay_lambda configures.
        total_weight = sum(weight for _, _, weight in values)
        if total_weight > 0:
            stance = sum(score * weight for _, score, weight in values) / total_weight
        else:
            stance = mean(score for _, score, _ in values)
        weight = mean(weight for _, _, weight in values)
        role = max(values, key=lambda item: item[2])[0]
        pairs.append((stance, weight))
        contributors.append(Contributor(user, role, round(stance, 4), round(weight, 4)))
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


def score_product(
    posts: list[Post],
    profiles: dict[str, AccountProfile],
    now: datetime | None = None,
    opinions: dict[tuple[str, int], CommentOpinion] | None = None,
) -> ProductReport:
    """計算單一商品彙整分數。

    ``now`` is the as-of instant the time decay is measured from. Passing it makes a
    rebuild of a stored snapshot reproduce the scores it was published with; leaving
    it unset means "score as of this moment", which is only correct for a live run.
    """
    if not posts:
        raise ValueError("score_product requires at least one post")

    mu0 = float(SCORING["prior_mean"])
    prior_strength = float(SCORING["prior_strength"])
    shill_ratio, shill_flag = _shill_stats(posts)
    shill_penalty = float(SHILL_DETECTION["post_weight_penalty"]) if shill_flag else 1.0

    opinions = opinions or build_comment_opinions(posts)
    opinion_pairs, opinion_contributors = _opinion_pairs(posts, profiles, now, opinions)
    eligible_comments = [
        comment
        for post in posts
        for index, comment in enumerate(post.comments)
        if opinions[(post.id, index)].include_score
    ]

    if shill_flag and opinion_pairs:
        opinion_pairs = [(score, weight * shill_penalty) for score, weight in opinion_pairs]

    if opinion_pairs:
        weighted_sum = sum(score * weight for score, weight in opinion_pairs)
        weight_sum = sum(weight for _, weight in opinion_pairs)
        weight_square_sum = sum(weight * weight for _, weight in opinion_pairs)
        fair01 = (prior_strength * mu0 + weighted_sum) / (prior_strength + weight_sum)
        mean01 = _weighted_mean(opinion_pairs)
        std = _weighted_std(opinion_pairs, mean01)
        n_eff = _n_eff([weight for _, weight in opinion_pairs])
    else:
        fair01 = None
        weighted_sum = 0.0
        weight_sum = 0.0
        weight_square_sum = 0.0
        mean01 = 0.0
        std = 0.0
        n_eff = 0.0

    contributors = sorted(opinion_contributors, key=lambda c: -c.weight)
    product_name = representative_product_name(posts)
    product_key = f"{posts[0].brand}:{normalize_product(posts[0].brand, product_name)}"
    review_excerpt = _load_review_excerpt_overrides().get(product_key) or _review_excerpt(posts)
    rep_pos, rep_neg = _rep_comments(posts, excerpt=review_excerpt)
    (
        competitor_mention_count,
        competitor_preference_count,
        competitor_own_preference_count,
        competitor_brands,
    ) = _competitor_stats(posts)
    post_dates = [normalize_datetime(p.posted_at) for p in posts if p.posted_at]
    latest_post_date = max(post_dates) if post_dates else None
    priced_posts = [p for p in posts if p.price and p.price.isdigit()]
    latest_priced_post = max(
        priced_posts,
        key=lambda p: normalize_datetime(p.posted_at or datetime.min),
        default=None,
    )
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
        n_eligible_comments=len(eligible_comments),
        n_unique_commenters=len({comment.user for comment in eligible_comments}),
        score_weight_sum=weight_sum,
        score_weighted_sum=weighted_sum,
        score_weight_square_sum=weight_square_sum,
        positive_weight=sum(weight for score, weight in opinion_pairs if score > 0.6),
        neutral_weight=sum(weight for score, weight in opinion_pairs if 0.4 <= score <= 0.6),
        negative_weight=sum(weight for score, weight in opinion_pairs if score < 0.4),
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


def score_all(
    posts: list[Post],
    profiles: dict[str, AccountProfile],
    now: datetime | None = None,
    opinions: dict[tuple[str, int], CommentOpinion] | None = None,
) -> list[ProductReport]:
    """計算所有商品報告並排序。``now`` is the as-of instant for time decay."""
    reports = [
        score_product(group, profiles, now, opinions)
        for group in group_products(posts).values()
    ]
    reports.sort(
        key=lambda report: (
            report.fair_score is None,
            report.confidence == "低" or report.consensus == "資料不足",
            -(report.fair_score or 0.0),
        )
    )
    return reports
