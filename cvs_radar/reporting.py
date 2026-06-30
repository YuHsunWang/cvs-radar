"""CLI and JSON reporting with public de-identification by default."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime
from typing import Any

from .config import PRIVACY
from .models import Comment, Contributor, Post, ProductReport
from .preference import AccountProfile, _burst_indices, _template_like_indices


def render_text(reports: list[ProductReport], internal: bool = False) -> str:
    if not reports:
        return "沒有可輸出的商品報告。"

    lines = ["CVS Radar 商品評價報告", ""]
    for index, report in enumerate(reports, 1):
        score = "無分數" if report.fair_score is None else f"{report.fair_score:.1f}"
        note = _evidence_note(report)
        lines.append(
            f"{index}. [{report.brand}] {report.product_name} | 公正分數 {score} | "
            f"{report.consensus} | 信心度 {report.confidence}"
        )
        lines.append(
            f"   樣本: {report.n_posts} 篇文 / {report.n_comments} 則留言；{note}"
        )
        competitor_line = _competitor_line(report)
        if competitor_line:
            lines.append("   " + competitor_line)
        if report.rep_positive:
            lines.append("   代表正評: " + " / ".join(report.rep_positive))
        if report.rep_negative:
            lines.append("   代表負評: " + " / ".join(report.rep_negative))
        if internal and report.contributors:
            lines.append(
                f"   內部診斷: n_eff={report.n_eff}, std={report.score_std}, key={report.product_key}"
            )
            rows = [
                f"{c.role}:{c.user} score={c.score:.3f} weight={c.weight:.3f}"
                for c in report.contributors[:10]
            ]
            lines.append("   貢獻者(內部): " + "; ".join(rows))
    return "\n".join(lines)


def render_json(reports: list[ProductReport], internal: bool = False) -> str:
    payload = [report_to_dict(report, internal=internal) for report in reports]
    return json.dumps(payload, ensure_ascii=False, indent=2)


def report_to_dict(report: ProductReport, internal: bool = False) -> dict[str, Any]:
    return _report_to_dict(report, internal=internal)


def render_suspicion(profiles: dict[str, AccountProfile]) -> str:
    if not profiles:
        return "沒有帳號輪廓。"
    lines = ["帳號信度摘要(內部維運用)"]
    ordered = sorted(profiles.values(), key=lambda p: (-p.suspicion_score, -p.total_comments, p.user))
    for profile in ordered[:30]:
        features = ", ".join(f"{k}={v:.2f}" for k, v in profile.suspicion_features.items()) or "未達活動量門檻"
        lines.append(
            f"- {profile.user}: comments={profile.total_comments}, lean={profile.lean_brand or '-'}, "
            f"suspicion={profile.suspicion_score:.2f}, credibility={profile.credibility:.2f} ({features})"
        )
    return "\n".join(lines)


def render_suspicion_detail(profile: AccountProfile, posts: list[Post]) -> str:
    user_comments = _profile_comments(profile.user, posts)
    template_flagged = _template_flagged_comments(user_comments)
    burst_flagged = _burst_flagged_comments(user_comments)

    lines = [
        f"帳號可疑明細: {profile.user}",
        (
            f"總留言數: {profile.total_comments}; 信度: {profile.credibility:.2f}; "
            f"可疑分: {profile.suspicion_score:.2f}; 傾向品牌: {profile.lean_brand or '-'}"
        ),
        "",
        "品牌互動",
    ]
    if profile.brand_stats:
        for brand, stat in sorted(profile.brand_stats.items(), key=lambda item: (-item[1].count, item[0])):
            lines.append(f"- {brand}: 留言數={stat.count}, 平均情感={stat.avg_sentiment:.2f}")
    else:
        lines.append("- 無")

    lines.extend(["", "特徵明細"])
    explanations = {
        "one_sided": "偏向單一品牌正面、競品負面的程度",
        "single_brand": "留言集中在單一品牌的程度",
        "extreme": "極端情感留言比例",
        "template_like": "完全重複或近似樣板留言比例",
        "burst": "同品牌短時間爆發留言比例",
    }
    if profile.suspicion_features:
        for name, explanation in explanations.items():
            value = profile.suspicion_features.get(name, 0.0)
            lines.append(f"- {name}: {value:.2f} ({explanation})")
    else:
        lines.append("- 未達活動量門檻，未計算特徵")

    lines.extend(["", "template_like 標記留言"])
    lines.extend(_format_flagged_comments(template_flagged[:10]))
    lines.extend(["", "burst 標記留言"])
    lines.extend(_format_flagged_comments(burst_flagged[:10]))
    return "\n".join(lines)


def _report_to_dict(report: ProductReport, internal: bool) -> dict[str, Any]:
    data = {
        "brand": report.brand,
        "product_name": report.product_name,
        "price": report.price,
        "category": report.category,
        "fair_score": report.fair_score,
        "consensus": report.consensus,
        "confidence": report.confidence,
        "evidence_note": _evidence_note(report),
        "n_posts": report.n_posts,
        "n_comments": report.n_comments,
        "rep_positive": report.rep_positive,
        "rep_negative": report.rep_negative,
        "competitor_mentions": {
            "total": report.competitor_mention_count,
            "preferred_other": report.competitor_preference_count,
            "brands": report.competitor_brands,
        },
    }
    if internal:
        data["product_key"] = report.product_key
        data["n_eff"] = report.n_eff
        data["score_std"] = report.score_std
        data["score_mean"] = report.score_mean
        data["contributors"] = [asdict(c) for c in report.contributors]
    elif PRIVACY["public_include_contributors"]:
        data["contributors"] = [_public_contributor(c) for c in report.contributors]
    return data


def _profile_comments(user: str, posts: list[Post]) -> list[tuple[str, Comment]]:
    comments: list[tuple[str, Comment]] = []
    for post in posts:
        for comment in post.comments:
            if comment.user == user:
                comments.append((post.brand, comment))
    return comments


def _template_flagged_comments(user_comments: list[tuple[str, Comment]]) -> list[tuple[str, Comment]]:
    texts = [comment.text for _, comment in user_comments]
    flagged = _template_like_indices(texts)
    return [user_comments[index] for index in sorted(flagged)]


def _burst_flagged_comments(user_comments: list[tuple[str, Comment]]) -> list[tuple[str, Comment]]:
    by_brand: dict[str, list[tuple[int, datetime]]] = {}
    for index, (brand, comment) in enumerate(user_comments):
        if comment.posted_at is None:
            continue
        by_brand.setdefault(brand, []).append((index, comment.posted_at))

    flagged: set[int] = set()
    for values in by_brand.values():
        local_flagged = _burst_indices([timestamp for _, timestamp in values])
        flagged.update(values[index][0] for index in local_flagged)
    return [user_comments[index] for index in sorted(flagged)]


def _format_flagged_comments(flagged: list[tuple[str, Comment]]) -> list[str]:
    if not flagged:
        return ["- 無"]
    lines: list[str] = []
    for brand, comment in flagged:
        posted_at = comment.posted_at.isoformat(sep=" ", timespec="minutes") if comment.posted_at else "時間未知"
        lines.append(f"- [{brand}] {posted_at} {comment.text}")
    return lines


def _evidence_note(report: ProductReport) -> str:
    if report.confidence == "低" or report.consensus == "資料不足":
        return "資料仍少，排名已降權，請保守解讀"
    if report.confidence == "中":
        return "樣本量中等，可作為初步參考"
    return "樣本量較充足"


def _competitor_line(report: ProductReport) -> str:
    if report.competitor_mention_count <= 0:
        return ""
    brands = "、".join(report.competitor_brands) if report.competitor_brands else "未辨識"
    return (
        f"競品提及: {report.competitor_mention_count} 則，"
        f"其中 {report.competitor_preference_count} 則偏好他牌；競品: {brands}"
    )


def _public_contributor(contributor: Contributor) -> dict[str, Any]:
    return {
        "user_hash": hash_user(contributor.user),
        "role": contributor.role,
        "score": contributor.score,
        "weight": contributor.weight,
    }


def hash_user(user: str) -> str:
    salt = str(PRIVACY["hash_salt"])
    return hashlib.sha256(f"{salt}:{user}".encode("utf-8")).hexdigest()[:12]
