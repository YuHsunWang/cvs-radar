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
                "共識分布": consensus_distribution(report),
                "討論聲量": volume_label(report),
                "競品提及": report.competitor_mention_count,
                "偏好他牌": report.competitor_preference_count,
                "偏好本品": report.competitor_own_preference_count,
                "提及競品": " / ".join(report.competitor_brands),
                "正向留言": " / ".join(report.rep_positive),
                "負向留言": " / ".join(report.rep_negative),
                "心得節錄": report.review_excerpt,
                "最新發文": report.latest_post_date.strftime("%Y-%m-%d") if report.latest_post_date else "",
                "貼文連結": list(report.post_urls),
            }
        )
    return rows


def filter_reports_by_search(reports: list[ProductReport], query: str) -> list[ProductReport]:
    """Filter reports by product name or brand with shelf-friendly matching."""

    normalized_query = query.strip().casefold()
    compact_query = _compact_search_text(normalized_query)
    if not normalized_query:
        return list(reports)

    matched = []
    for report in reports:
        targets = (report.product_name, report.brand)
        if any(_search_target_matches(target, normalized_query, compact_query) for target in targets):
            matched.append(report)
    return matched


def _search_target_matches(target: str, query: str, compact_query: str) -> bool:
    normalized_target = target.casefold()
    return query in normalized_target or compact_query in _compact_search_text(normalized_target)


def _compact_search_text(text: str) -> str:
    return "".join(text.split())


POLARITY_NEUTRAL_BAND = 0.2


def consensus_distribution(report: ProductReport) -> tuple[int, int, int] | None:
    """Return weighted positive/neutral/negative contributor percentages."""
    totals = {"positive": 0.0, "neutral": 0.0, "negative": 0.0}
    for contributor in report.contributors:
        weight = max(float(contributor.weight), 0.0)
        if weight == 0:
            continue
        if contributor.score > POLARITY_NEUTRAL_BAND:
            totals["positive"] += weight
        elif contributor.score < -POLARITY_NEUTRAL_BAND:
            totals["negative"] += weight
        else:
            totals["neutral"] += weight

    total = sum(totals.values())
    if total <= 0:
        return None

    raw = [
        totals["positive"] / total * 100,
        totals["neutral"] / total * 100,
        totals["negative"] / total * 100,
    ]
    percentages = [int(value) for value in raw]
    remainder = 100 - sum(percentages)
    order = sorted(range(3), key=lambda idx: raw[idx] - percentages[idx], reverse=True)
    for idx in order[:remainder]:
        percentages[idx] += 1
    return (percentages[0], percentages[1], percentages[2])


_VOLUME_TIER = {"高": "充足", "中": "中等", "低": "不足"}


def volume_label(report: ProductReport) -> str:
    """把資料狀態、有效樣本、貼文/留言數合併成單一討論聲量描述。"""
    tier = _VOLUME_TIER.get(report.confidence, "不足")
    if report.consensus == "資料不足":
        tier = "不足"
    return f"聲量{tier}"
