"""Small adapters shared by the Streamlit app and API layer.

These helpers keep framework code focused on input/output while all filtering,
scoring, and ranking stays in ``cvs_radar.service``.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from .models import Post, ProductReport
from .preference import AccountProfile
from .service import ProductQuery, ProductQueryResult, list_brands

ALL_BRANDS = "全部"
SourceName = Literal["demo", "crawl", "stored", "results"]


def load_results_or_none() -> tuple[list[ProductReport], dict[str, AccountProfile]] | None:
    """Try to load precomputed results. Returns (reports, profiles) or None."""
    from .store import load_results

    return load_results()


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
                "價格": report.price,
                "分類": report.category or "其他",
                "fair_score": report.fair_score,
                "consensus": report.consensus,
                "討論聲量": volume_label(report),
                "業配嫌疑": "⚠ 疑似業配" if report.shill_flag else "",
                "競品提及": report.competitor_mention_count,
                "偏好他牌": report.competitor_preference_count,
                "提及競品": " / ".join(report.competitor_brands),
                "正向留言": " / ".join(report.rep_positive),
                "負向留言": " / ".join(report.rep_negative),
                "image_url": report.image_url or "",
            }
        )
    return rows


_VOLUME_TIER = {"高": "充足", "中": "中等", "低": "偏少"}


def volume_label(report: ProductReport) -> str:
    """把資料狀態、有效樣本、貼文/留言數合併成單一討論聲量描述。"""
    tier = _VOLUME_TIER.get(report.confidence, "偏少")
    if report.consensus == "資料不足":
        tier = "偏少"
    return f"聲量{tier}·{report.n_posts}篇/{report.n_comments}則·約{round(report.n_eff)}人"
