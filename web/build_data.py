from __future__ import annotations

import csv
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cvs_radar.app_helpers import consensus_distribution, volume_label  # noqa: E402
from cvs_radar.store import load_results  # noqa: E402


PRODUCT_OVERRIDES_PATH = ROOT / "data" / "labels" / "product_overrides.csv"
CLEAR_VALUE = "__CLEAR__"
REPRESENTATIVE_LIMIT = 3
DATA_STALE_DAYS = 14
TAIPEI_TIMEZONE = ZoneInfo("Asia/Taipei")


def resolve_data_timestamps(source: Path, site_built_at: datetime) -> tuple[str, str]:
    source_payload = json.loads(source.read_text(encoding="utf-8"))
    source_generated_at = source_payload.get("generated_at")
    if not source_generated_at:
        print("WARNING: source data has no generated_at; using site build time for generatedAt")
        return site_built_at.isoformat(), site_built_at.isoformat()

    data_generated_at = datetime.strptime(
        source_generated_at, "%Y-%m-%d %H:%M:%S"
    ).replace(tzinfo=TAIPEI_TIMEZONE)
    data_age = site_built_at - data_generated_at.astimezone(timezone.utc)
    if data_age > timedelta(days=DATA_STALE_DAYS):
        print(
            "WARNING: source data is stale: "
            f"generated_at={source_generated_at} is "
            f"{data_age.total_seconds() / 86400:.1f} days old "
            f"(threshold: {DATA_STALE_DAYS} days)"
        )

    return data_generated_at.isoformat(), site_built_at.isoformat()


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
            values = {
                key: value.strip()
                for key in ("brand", "productName", "category", "price", "excerpt", "exclude")
                if (value := row.get(key)) is not None and value.strip()
            }
            price = values.get("price")
            if price and price != CLEAR_VALUE and not price.isdigit():
                raise ValueError(f"invalid product override price for {product_id}: {price!r}")
            exclude = values.get("exclude", "").lower()
            if exclude and exclude not in {"1", "true", "yes"}:
                raise ValueError(f"invalid product override exclude flag for {product_id}: {exclude!r}")
            overrides[product_id] = values
    return overrides


def apply_product_override(
    product: dict[str, Any], override: dict[str, Any] | None
) -> dict[str, Any] | None:
    """Apply an audited correction without mutating the source report."""
    if not override:
        return product
    if override.get("exclude", "").lower() in {"1", "true", "yes"}:
        return None

    corrected = dict(product)
    for field in ("brand", "productName", "category", "excerpt"):
        if field in override:
            corrected[field] = "" if override[field] == CLEAR_VALUE else override[field]
    if "price" in override:
        corrected["price"] = None if override["price"] == CLEAR_VALUE else int(override["price"])
    corrected["id"] = f"{corrected['brand']}::{corrected['productName']}"
    return corrected


def _evidence(product: dict[str, Any]) -> float:
    n_eff = float(product.get("_nEff") or 0)
    return n_eff if n_eff > 0 else float(product.get("nComments") or 0)


def _unique_representatives(products: list[dict[str, Any]], field: str) -> list[str]:
    return list(dict.fromkeys(item for product in products for item in product.get(field, [])))[
        :REPRESENTATIVE_LIMIT
    ]


def merge_products(products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge products that canonicalize to the same final public ID."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for product in products:
        grouped.setdefault(product["id"], []).append(product)

    merged_products = []
    for members in grouped.values():
        dominant = max(members, key=lambda item: (_evidence(item), item.get("nComments", 0)))
        merged = dict(dominant)

        if len(members) > 1:
            merged["nPosts"] = sum(item.get("nPosts", 0) for item in members)
            merged["nComments"] = sum(item.get("nComments", 0) for item in members)

            scored = [
                (item.get("_fairScoreRaw", item.get("fairScore")), _evidence(item))
                for item in members
                if item.get("_fairScoreRaw", item.get("fairScore")) is not None
            ]
            if scored:
                total_weight = sum(weight for _, weight in scored)
                merged_fair_score = (
                    sum(float(score) * weight for score, weight in scored) / total_weight
                    if total_weight > 0
                    else sum(float(score) for score, _ in scored) / len(scored)
                )
                merged["fairScore"] = round(merged_fair_score)
                merged["recommendationScore"] = calibrate_recommendation_score(merged_fair_score)
            else:
                merged["fairScore"] = None
                merged["recommendationScore"] = None

            latest_dates = [item["latestDate"] for item in members if item.get("latestDate")]
            merged["latestDate"] = max(latest_dates) if latest_dates else None
            if any("firstDate" in item for item in members):
                first_dates = [item["firstDate"] for item in members if item.get("firstDate")]
                merged["firstDate"] = min(first_dates) if first_dates else None
            merged["likes"] = _unique_representatives(members, "likes")
            merged["cautions"] = _unique_representatives(members, "cautions")

        merged.pop("_nEff", None)
        merged.pop("_fairScoreRaw", None)
        merged_products.append(merged)

    return merged_products


def assert_unique_product_ids(products: list[dict[str, Any]]) -> None:
    ids = [product["id"] for product in products]
    if len(ids) != len(set(ids)):
        duplicates = sorted(product_id for product_id in set(ids) if ids.count(product_id) > 1)
        raise ValueError(f"duplicate public product ids after merge: {duplicates}")


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


def main(
    source: Path | None = None,
    output: Path | None = None,
    site_built_at: datetime | None = None,
) -> None:
    source = source or ROOT / "data" / "results.json"
    output = output or Path(__file__).resolve().parent / "public" / "data.json"
    site_built_at = site_built_at or datetime.now(timezone.utc)
    loaded = load_results(source)
    if loaded is None:
        raise FileNotFoundError(source)

    reports, _profiles = loaded
    recommendation_scores = calibrate_recommendation_scores(reports)
    product_overrides = load_product_overrides()
    products = []
    for report in reports:
        product = to_product(report, recommendation_scores.get(report.product_key))
        product["_nEff"] = report.n_eff
        product["_fairScoreRaw"] = report.fair_score
        corrected = apply_product_override(product, product_overrides.get(product["id"]))
        if corrected is not None:
            products.append(corrected)
    products = merge_products(products)
    assert_unique_product_ids(products)
    generated_at, site_built_at_iso = resolve_data_timestamps(source, site_built_at)
    payload = {
        "generatedAt": generated_at,
        "siteBuiltAt": site_built_at_iso,
        "products": products,
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(payload['products'])} products to {output.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
