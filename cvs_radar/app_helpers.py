"""Small adapters shared by the Streamlit app and API layer.

These helpers keep framework code focused on input/output while all filtering,
scoring, and ranking stays in ``cvs_radar.service``.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from .models import Post
from .service import ProductQuery, ProductQueryResult, list_brands

ALL_BRANDS = "全部"
SourceName = Literal["demo", "crawl", "stored"]


def load_posts(
    source: SourceName = "demo",
    *,
    crawl_pages: int = 5,
    start_date: str | date | datetime | None = None,
    end_date: str | date | datetime | None = None,
    recent_days: int | None = None,
    now: datetime | None = None,
) -> list[Post]:
    """Load posts from the selected source.

    The demo source is the default and never uses the network. The crawl branch
    is intentionally narrow so the app can expose the future path without
    changing service APIs.
    """

    if source == "demo":
        from .sample_data import load_sample

        return load_sample()

    if source == "stored":
        from .store import load_posts as load_stored

        return load_stored()

    if source == "crawl":
        from .crawler import PttCrawler

        return PttCrawler().crawl(
            max_pages=crawl_pages,
            start_date=start_date,
            end_date=end_date,
            recent_days=recent_days,
            now=now,
        )

    raise ValueError(f"unsupported source: {source}")


def brand_options(
    posts: list[Post],
    *,
    start_date: str | date | datetime | None = None,
    end_date: str | date | datetime | None = None,
    recent_days: int | None = None,
    now: datetime | None = None,
) -> list[str]:
    """Return app-ready brand choices for the selected time window."""

    summaries = list_brands(
        posts,
        start_date=start_date,
        end_date=end_date,
        recent_days=recent_days,
        now=now,
    )
    return [ALL_BRANDS, *(summary.brand for summary in summaries)]


def build_product_query(
    *,
    brand: str | None = None,
    start_date: str | date | datetime | None = None,
    end_date: str | date | datetime | None = None,
    recent_days: int | None = None,
    min_score: float | None = None,
    min_n_eff: float | None = None,
    min_posts: int | None = None,
    min_comments: int | None = None,
    limit: int | None = None,
    internal: bool = False,
) -> ProductQuery:
    """Normalize UI/API parameters into the service query object."""

    return ProductQuery(
        brand=None if not brand or brand == ALL_BRANDS else brand,
        start_date=start_date,
        end_date=end_date,
        recent_days=recent_days,
        min_score=min_score,
        min_n_eff=min_n_eff,
        min_posts=min_posts,
        min_comments=min_comments,
        limit=limit,
        internal=internal,
    )


def product_rows(result: ProductQueryResult) -> list[dict[str, Any]]:
    """Convert service output into rows suitable for Streamlit tables."""

    rows: list[dict[str, Any]] = []
    for rank, report in enumerate(result.reports, 1):
        rows.append(
            {
                "排名": rank,
                "品牌": report.brand,
                "商品": report.product_name,
                "fair_score": report.fair_score,
                "consensus": report.consensus,
                "confidence": report.confidence,
                "資料狀態": _evidence_note(report.confidence, report.consensus),
                "有效樣本": report.n_eff,
                "n_posts": report.n_posts,
                "n_comments": report.n_comments,
                "競品提及": report.competitor_mention_count,
                "偏好他牌": report.competitor_preference_count,
                "提及競品": " / ".join(report.competitor_brands),
                "代表性推": " / ".join(report.rep_positive),
                "代表性噓": " / ".join(report.rep_negative),
            }
        )
    return rows


def _evidence_note(confidence: str, consensus: str) -> str:
    if confidence == "低" or consensus == "資料不足":
        return "資料仍少，排名已降權"
    if confidence == "中":
        return "樣本量中等"
    return "樣本量較充足"
