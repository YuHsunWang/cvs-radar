from __future__ import annotations

import csv
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cvs_radar.app_helpers import consensus_distribution, volume_label  # noqa: E402
from cvs_radar.store import load_results  # noqa: E402


PRODUCT_OVERRIDES_PATH = ROOT / "data" / "labels" / "product_overrides.csv"
CLEAR_VALUE = "__CLEAR__"


def load_product_overrides(path: Path = PRODUCT_OVERRIDES_PATH) -> dict[str, dict[str, Any]]:
    """Load reviewed public-product corrections keyed by the original product ID."""
    if not path.exists():
        return {}

    overrides: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            product_id = (row.get("product_id") or "").strip()
            if not product_id:
                continue
            overrides[product_id] = {
                key: value.strip()
                for key in ("productName", "category", "price", "excerpt")
                if (value := row.get(key)) is not None and value.strip()
            }
    return overrides


def apply_product_override(product: dict[str, Any], override: dict[str, Any] | None) -> dict[str, Any]:
    """Apply an audited correction without mutating the source report."""
    if not override:
        return product

    corrected = dict(product)
    for field in ("productName", "category", "excerpt"):
        if field in override:
            corrected[field] = "" if override[field] == CLEAR_VALUE else override[field]
    if "price" in override:
        corrected["price"] = None if override["price"] == CLEAR_VALUE else int(override["price"])
    corrected["id"] = f"{corrected['brand']}::{corrected['productName']}"
    return corrected


def clean_volume_label(value: str) -> str:
    match = re.search(r"(充足|中等|不足)", value)
    return match.group(1) if match else "不足"


def calibrate_recommendation_score(fair_score: float) -> int:
    """Map a Bayesian fair score onto a stable, user-facing 0-100 scale."""

    score = max(0.0, min(100.0, float(fair_score)))
    if score <= 50:
        return round(score * 1.2)
    if score <= 80:
        return round(60 + (score - 50) * 1.1)
    return round(93 + (score - 80) * 0.35)


def calibrate_recommendation_scores(reports: list[Any]) -> dict[str, int]:
    return {
        report.product_key: calibrate_recommendation_score(report.fair_score)
        for report in reports
        if report.fair_score is not None
        and report.confidence != "低"
        and report.consensus != "資料不足"
    }


def display_confidence(report: Any) -> str:
    """Keep public confidence labels from overstating a single discussion thread."""

    if report.n_posts < 2 and report.confidence == "高":
        return "中"
    return report.confidence


def to_product(report: Any, recommendation_score: int | None = None) -> dict[str, Any]:
    distribution = None
    if report.confidence != "低" and report.consensus != "資料不足":
        distribution = consensus_distribution(report)
    if distribution is None:
        positive_pct = neutral_pct = negative_pct = None
    else:
        positive_pct, neutral_pct, negative_pct = distribution

    latest_date = None
    if report.latest_post_date is not None:
        latest_date = report.latest_post_date.date().isoformat()

    fair_score = report.fair_score

    return {
        "id": f"{report.brand}::{report.product_name}",
        "brand": report.brand,
        "productName": report.product_name,
        "price": report.price,
        "category": report.category or "",
        "fairScore": round(fair_score) if fair_score is not None else None,
        "recommendationScore": recommendation_score,
        "consensus": report.consensus,
        "confidence": display_confidence(report),
        "nPosts": report.n_posts,
        "nComments": report.n_comments,
        "volumeLevel": clean_volume_label(volume_label(report)),
        "positivePct": positive_pct,
        "neutralPct": neutral_pct,
        "negativePct": negative_pct,
        "likes": list(report.rep_positive or []),
        "cautions": list(report.rep_negative or []),
        "excerpt": report.review_excerpt or "",
        "postUrls": list(report.post_urls or []),
        "latestDate": latest_date,
    }


def main() -> None:
    source = ROOT / "data" / "results.json"
    output = Path(__file__).resolve().parent / "public" / "data.json"
    loaded = load_results(source)
    if loaded is None:
        raise FileNotFoundError(source)

    reports, _profiles = loaded
    recommendation_scores = calibrate_recommendation_scores(reports)
    product_overrides = load_product_overrides()
    products = []
    for report in reports:
        product = to_product(report, recommendation_scores.get(report.product_key))
        products.append(apply_product_override(product, product_overrides.get(product["id"])))
    payload = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "products": products,
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(payload['products'])} products to {output.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
