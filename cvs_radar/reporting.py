"""CLI and JSON reporting with public de-identification by default."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import Any

from .config import PRIVACY
from .models import Contributor, ProductReport
from .preference import AccountProfile


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


def _report_to_dict(report: ProductReport, internal: bool) -> dict[str, Any]:
    data = {
        "brand": report.brand,
        "product_name": report.product_name,
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
