"""App-facing service API for CVS Radar.

The functions here are intentionally framework-free so they can be called from
CLI, FastAPI/Flask, Streamlit, notebooks, or tests with the same behavior.
"""

from __future__ import annotations

import unicodedata
from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any

from .config import BRANDS
from .filters import TimeWindow, build_time_window, filter_posts_by_time
from .models import Post, ProductReport
from .pipeline import run_pipeline
from .reporting import report_to_dict
from .scoring import normalize_product


@dataclass(frozen=True, slots=True)
class ProductQuery:
    brand: str | None = None
    start_date: str | date | datetime | None = None
    end_date: str | date | datetime | None = None
    recent_days: int | None = None
    min_score: float | None = None
    min_n_eff: float | None = None
    min_posts: int | None = None
    min_comments: int | None = None
    limit: int | None = None
    internal: bool = False


@dataclass(frozen=True, slots=True)
class BrandSummary:
    brand: str
    product_count: int
    post_count: int
    comment_count: int


@dataclass(frozen=True, slots=True)
class ProductQueryResult:
    filters: dict[str, Any]
    brands: list[BrandSummary]
    reports: list[ProductReport]

    def to_dict(self) -> dict[str, Any]:
        return {
            "filters": self.filters,
            "brands": [asdict(brand) for brand in self.brands],
            "reports": [report_to_dict(report, internal=bool(self.filters.get("internal"))) for report in self.reports],
        }


def select_reviews(
    posts: list[Post],
    *,
    start_date: str | date | datetime | None = None,
    end_date: str | date | datetime | None = None,
    recent_days: int | None = None,
    now: datetime | None = None,
) -> list[Post]:
    """Filter posts/comments by date without scoring."""

    return filter_posts_by_time(
        posts,
        start_date=start_date,
        end_date=end_date,
        recent_days=recent_days,
        now=now,
    )


def list_brands(
    posts: list[Post],
    *,
    start_date: str | date | datetime | None = None,
    end_date: str | date | datetime | None = None,
    recent_days: int | None = None,
    now: datetime | None = None,
) -> list[BrandSummary]:
    """List brands present in the currently selected data."""

    selected = select_reviews(
        posts,
        start_date=start_date,
        end_date=end_date,
        recent_days=recent_days,
        now=now,
    )
    rows: dict[str, dict[str, Any]] = {}
    for post in selected:
        row = rows.setdefault(post.brand, {"products": set(), "post_count": 0, "comment_count": 0})
        row["products"].add(normalize_product(post.brand, post.product_name))
        row["post_count"] += 1
        row["comment_count"] += len(post.comments)

    summaries = [
        BrandSummary(
            brand=brand,
            product_count=len(values["products"]),
            post_count=int(values["post_count"]),
            comment_count=int(values["comment_count"]),
        )
        for brand, values in rows.items()
    ]
    summaries.sort(key=lambda item: (-item.product_count, -item.post_count, item.brand))
    return summaries


def query_products(
    posts: list[Post],
    query: ProductQuery | None = None,
    *,
    now: datetime | None = None,
    **overrides: Any,
) -> ProductQueryResult:
    """Score and rank products using app-ready filters."""

    if query is None:
        query = ProductQuery(**overrides)
    elif overrides:
        query = ProductQuery(**{**asdict(query), **overrides})
    effective_now = now or (datetime.now() if query.recent_days is not None else None)

    selected = select_reviews(
        posts,
        start_date=query.start_date,
        end_date=query.end_date,
        recent_days=query.recent_days,
        now=effective_now,
    )
    reports, _profiles = run_pipeline(selected)
    reports = filter_reports(
        reports,
        brand=query.brand,
        min_score=query.min_score,
        min_n_eff=query.min_n_eff,
        min_posts=query.min_posts,
        min_comments=query.min_comments,
        limit=query.limit,
    )
    return ProductQueryResult(
        filters=_filters_dict(query, now=effective_now),
        brands=list_brands(
            posts,
            start_date=query.start_date,
            end_date=query.end_date,
            recent_days=query.recent_days,
            now=effective_now,
        ),
        reports=reports,
    )


def filter_reports(
    reports: list[ProductReport],
    *,
    brand: str | None = None,
    min_score: float | None = None,
    min_n_eff: float | None = None,
    min_posts: int | None = None,
    min_comments: int | None = None,
    limit: int | None = None,
) -> list[ProductReport]:
    _validate_non_negative("min_score", min_score)
    _validate_non_negative("min_n_eff", min_n_eff)
    _validate_non_negative("min_posts", min_posts)
    _validate_non_negative("min_comments", min_comments)
    _validate_non_negative("limit", limit)

    filtered = list(reports)
    if brand:
        filtered = [report for report in filtered if _brand_matches(report.brand, brand)]
    if min_score is not None:
        filtered = [report for report in filtered if report.fair_score is not None and report.fair_score >= min_score]
    if min_n_eff is not None:
        filtered = [report for report in filtered if report.n_eff >= min_n_eff]
    if min_posts is not None:
        filtered = [report for report in filtered if report.n_posts >= min_posts]
    if min_comments is not None:
        filtered = [report for report in filtered if report.n_comments >= min_comments]
    if limit is not None:
        filtered = filtered[:limit]
    return filtered


def _validate_non_negative(name: str, value: float | int | None) -> None:
    if value is not None and value < 0:
        raise ValueError(f"{name} must be non-negative")


def _brand_matches(actual: str, requested: str) -> bool:
    actual_token = _brand_token(actual)
    requested_token = _brand_token(requested)
    if not requested_token:
        return True
    if actual_token == requested_token:
        return True
    return _brand_token(_canonical_brand(actual)) == _brand_token(_canonical_brand(requested))


def _canonical_brand(value: str) -> str:
    token = _brand_token(value)
    for brand, keywords in BRANDS.items():
        aliases = [brand, *keywords]
        if token in {_brand_token(alias) for alias in aliases}:
            return brand
    return str(value).strip()


def _brand_token(value: str) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).casefold().strip()


def _filters_dict(query: ProductQuery, *, now: datetime | None) -> dict[str, Any]:
    window: TimeWindow = build_time_window(
        start_date=query.start_date,
        end_date=query.end_date,
        recent_days=query.recent_days,
        now=now,
    )
    return {
        "brand": query.brand,
        "start_date": window.start.isoformat() if window.start else None,
        "end_date": window.end.isoformat() if window.end else None,
        "recent_days": query.recent_days,
        "min_score": query.min_score,
        "min_n_eff": query.min_n_eff,
        "min_posts": query.min_posts,
        "min_comments": query.min_comments,
        "limit": query.limit,
        "internal": query.internal,
    }
