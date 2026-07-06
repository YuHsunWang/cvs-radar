"""Shopper-facing Streamlit UI for CVS Radar."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from html import escape
import json
from pathlib import Path
from typing import Any

import streamlit as st

from cvs_radar.app_helpers import (
    ALL_BRANDS,
    brand_options,
    build_product_query,
    filter_reports_by_search,
    load_results_or_none,
    load_posts,
    product_rows,
    relative_date_label,
)
from cvs_radar.service import ProductQueryResult, brand_summaries_from_reports, filter_reports, query_products
from cvs_radar.store import DEFAULT_RESULTS_PATH


CONSENSUS_SIGNALS = {
    "一致好評": ("好評明確", "signal-good", ("pos", "pos", "pos", "pos", "pos")),
    "褒貶不一": ("褒貶不一", "signal-mixed", ("pos", "pos", "pos", "neg", "neg")),
    "評價兩極": ("兩極分歧", "signal-polar", ("pos", "pos", "split", "neg", "neg")),
    "一致負評": ("負評明確", "signal-bad", ("neg", "neg", "neg", "neg", "neg")),
    "資料不足": ("資料不足", "signal-low", ("empty", "empty", "empty", "empty", "empty")),
}

VOLUME_SIGNALS = {
    "聲量充足": ("高聲量", "volume-high", 3),
    "聲量中等": ("中聲量", "volume-mid", 2),
    "聲量不足": ("低聲量", "volume-low", 1),
}

BRAND_LOGO_SPECS = {
    "7-11": {
        "text": "7-11",
        "bg": "#ffffff",
        "fg": "#0c6b3c",
        "border": "#0c6b3c",
    },
    "全家": {
        "text": "全家",
        "bg": "#ffffff",
        "fg": "#005bac",
        "border": "#00a650",
    },
    "萊爾富": {
        "text": "HiLife",
        "bg": "#fff7f5",
        "fg": "#d71920",
        "border": "#d71920",
    },
    "OK": {
        "text": "OK",
        "bg": "#fff8df",
        "fg": "#c45f00",
        "border": "#f4a300",
    },
    "美聯社": {
        "text": "美聯",
        "bg": "#f7f1ff",
        "fg": "#6d2ea0",
        "border": "#7a3db8",
    },
    "其他": {
        "text": "店",
        "bg": "#f4f6f8",
        "fg": "#536170",
        "border": "#a7b2bf",
    },
}

CATEGORY_ALL = "全部分類"
CATEGORY_OTHER = "其他"
CATEGORY_FALLBACK_ORDER = ["冰品", "飲料", "甜點", "麵包", "便當", "鹹食", "零食", "泡麵", "乳品", "周邊"]
PAGE_SIZE_STEP = 12
POSTS_PATH = Path("data/posts.jsonl")


def main() -> None:
    st.set_page_config(page_title="CVS Radar", page_icon="🛒", layout="centered")
    _inject_css()
    _render_header()

    search_query = st.text_input("搜尋商品或品牌", placeholder="搜尋商品或品牌…")
    controls = _render_sidebar()

    posts = None
    reports = None
    source = str(controls["source"])
    if source == "results":
        loaded = _load_results_or_none_cached()
        if loaded is None:
            st.warning("找不到預算結果，已改用離線示範資料。")
            source = "demo"
            posts = load_posts("demo")
            options: list[str] = []
        else:
            reports, _profiles = loaded
            brand_set = sorted(set(r.brand for r in reports))
            options = [ALL_BRANDS, *brand_set]
    else:
        try:
            posts = load_posts(source, crawl_pages=int(controls["crawl_pages"]))
            options = []
        except ValueError as exc:
            st.error(str(exc))
            return
        except Exception as exc:  # pragma: no cover - UI safety net
            st.error(f"資料載入失敗：{exc}")
            return

    if source != "results" and posts is not None:
        options = brand_options(posts)

    selected_category = _render_category_filter(reports)
    selected_brand = _render_brand_filter(options)
    filters = _render_filters(source, posts, options, selected_category=selected_category, selected_brand=selected_brand)
    query = build_product_query(
        brand=filters["selected_brand"],
        start_date=filters["start_date"],
        end_date=filters["end_date"],
        recent_days=filters["recent_days"],
        min_score=filters["min_score"],
        min_n_eff=filters["min_n_eff"],
        min_posts=filters["min_posts"],
        min_comments=filters["min_comments"],
        limit=None,
        internal=False,
    )

    try:
        if reports is not None:
            result = _query_precomputed_reports(reports, query)
        else:
            result = query_products(posts, query)
    except ValueError as exc:
        st.error(str(exc))
        return

    if filters["selected_category"] != CATEGORY_ALL:
        result = ProductQueryResult(
            filters=result.filters,
            brands=result.brands,
            reports=[r for r in result.reports if (r.category or CATEGORY_OTHER) == filters["selected_category"]],
        )

    searched_reports = filter_reports_by_search(result.reports, search_query)
    sorted_reports = _sort_reports(searched_reports, str(filters["sort_by"]))
    result_filters = dict(result.filters)
    result_filters["limit"] = None
    result_filters["search_query"] = search_query
    result = ProductQueryResult(
        filters=result_filters,
        brands=brand_summaries_from_reports(sorted_reports),
        reports=sorted_reports,
    )

    _render_context_bar(result, selected_brand=str(filters["selected_brand"]), sort_by=str(filters["sort_by"]), source=source)
    selection_key = "|".join(
        str(filters[k])
        for k in ("selected_brand", "selected_category", "sort_by", "start_date", "end_date", "recent_days")
    )
    selection_key = f"{selection_key}|{search_query}"
    _render_shopper_view(result, selection_key=selection_key, search_query=search_query)


def _sort_reports(reports: list, sort_by: str) -> list:
    if sort_by == "評分最低":
        return sorted(reports, key=lambda r: (r.fair_score is None, r.fair_score if r.fair_score is not None else 0.0))
    if sort_by == "最新發文":
        return sorted(reports, key=lambda r: r.latest_post_date or datetime.min, reverse=True)
    if sort_by == "討論最多":
        return sorted(reports, key=lambda r: r.n_posts + r.n_comments, reverse=True)
    return sorted(reports, key=lambda r: (r.fair_score is not None, r.fair_score or 0.0), reverse=True)


def _category_options_from_reports(reports: list[Any] | None) -> list[str]:
    if not reports:
        return [CATEGORY_ALL, *CATEGORY_FALLBACK_ORDER, CATEGORY_OTHER]

    counts = Counter((getattr(report, "category", None) or CATEGORY_OTHER) for report in reports)
    categories = [category for category, _count in counts.most_common() if category != CATEGORY_OTHER]
    return [CATEGORY_ALL, *categories, CATEGORY_OTHER]


def _render_category_filter(reports: list[Any] | None) -> str:
    options = _category_options_from_reports(reports)
    selected = st.pills(
        "分類",
        options,
        default=CATEGORY_ALL,
        selection_mode="single",
        key="category_filter",
    )
    return str(selected or CATEGORY_ALL)


def _render_brand_filter(options: list[str]) -> str:
    brands = [option for option in options if option != ALL_BRANDS]
    brand_options = [ALL_BRANDS, *brands]
    selected = st.pills(
        "品牌",
        brand_options,
        default=ALL_BRANDS,
        selection_mode="single",
        key="brand_filter",
    )
    return str(selected or ALL_BRANDS)


def _load_results_or_none_cached() -> tuple[list, dict] | None:
    results_path = Path(DEFAULT_RESULTS_PATH)
    try:
        stat = results_path.stat()
        mtime_ns = stat.st_mtime_ns
        size = stat.st_size
    except FileNotFoundError:
        mtime_ns = -1
        size = -1
    return _load_results_cached(str(results_path), mtime_ns, size)


@st.cache_data(show_spinner=False)
def _load_results_cached(path: str, mtime_ns: int, size: int) -> tuple[list, dict] | None:
    return load_results_or_none()


def _load_post_metadata() -> dict[str, dict[str, str]]:
    try:
        stat = POSTS_PATH.stat()
    except FileNotFoundError:
        return {}
    return _load_post_metadata_cached(str(POSTS_PATH), stat.st_mtime_ns, stat.st_size)


@st.cache_data(show_spinner=False)
def _load_post_metadata_cached(path: str, mtime_ns: int, size: int) -> dict[str, dict[str, str]]:
    metadata: dict[str, dict[str, str]] = {}
    with Path(path).open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                post = json.loads(line)
            except json.JSONDecodeError:
                continue
            url = str(post.get("url") or "").strip()
            if not url:
                continue
            posted_at = str(post.get("posted_at") or "").strip()
            metadata[url] = {
                "title": str(post.get("title") or "").strip(),
                "date": posted_at[:10] if len(posted_at) >= 10 else "",
            }
    return metadata


def _inject_css() -> None:
    st.markdown(
        """
        <style>
        :root {
            --cvs-ink: #172033;
            --cvs-muted: #6f7b8a;
            --cvs-soft: #f7f3ea;
            --cvs-line: #e4ded3;
            --cvs-panel: #ffffff;
            --cvs-panel-soft: rgba(255, 255, 255, 0.82);
            --cvs-teal: #0f8f7a;
            --cvs-teal-dark: #006b63;
            --cvs-green: #188657;
            --cvs-green-bg: #edf8f1;
            --cvs-amber: #c46f00;
            --cvs-amber-bg: #fff6df;
            --cvs-red: #c43d36;
            --cvs-red-bg: #fff0ed;
            --cvs-blue-bg: #eef7fb;
            --cvs-shadow: 0 18px 45px rgba(42, 36, 25, 0.08);
        }

        .stApp {
            background:
                radial-gradient(circle at 18% 0%, rgba(15, 143, 122, 0.12), transparent 30rem),
                linear-gradient(180deg, #fbf8f1 0, var(--cvs-soft) 360px, #f6f3ec 100%);
            color: var(--cvs-ink);
        }

        .block-container {
            max-width: 1320px;
            padding-top: 1.05rem;
            padding-bottom: 3rem;
        }

        section[data-testid="stSidebar"] {
            background: linear-gradient(180deg, #fffcf6 0%, #f5efe3 100%);
            border-right: 1px solid #ded4c4;
            box-shadow: 8px 0 30px rgba(42, 36, 25, 0.06);
        }

        section[data-testid="stSidebar"] [data-testid="stSidebarContent"] {
            padding-top: 1.25rem;
        }

        section[data-testid="stSidebar"] h2,
        section[data-testid="stSidebar"] h3 {
            color: var(--cvs-ink);
            letter-spacing: 0;
        }

        div[data-testid="stVerticalBlockBorderWrapper"] {
            border-color: var(--cvs-line) !important;
            border-radius: 8px !important;
            background: rgba(255, 255, 255, 0.72) !important;
            box-shadow: var(--cvs-shadow);
        }

        .shopper-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 1.2rem;
            padding: 1.05rem 1.15rem;
            margin: 0.1rem 0 1rem;
            background: rgba(255, 255, 255, 0.68);
            border: 1px solid rgba(228, 222, 211, 0.86);
            border-radius: 8px;
            box-shadow: var(--cvs-shadow);
            backdrop-filter: blur(12px);
        }

        .brand-lockup {
            display: flex;
            align-items: center;
            gap: 0.95rem;
            min-width: 0;
        }

        .radar-mark {
            width: 58px;
            height: 58px;
            flex: 0 0 auto;
            border-radius: 999px;
            display: grid;
            place-items: center;
            color: var(--cvs-teal-dark);
            background:
                radial-gradient(circle, rgba(255,255,255,0.95) 0 34%, transparent 35%),
                conic-gradient(from 320deg, #68b9a8 0 72%, #d9eee9 72% 100%);
            box-shadow: inset 0 0 0 6px rgba(15, 143, 122, 0.18);
            font-size: 1.7rem;
            font-weight: 900;
        }

        .shopper-title {
            margin: 0;
            color: var(--cvs-ink);
            font-size: clamp(1.82rem, 3vw, 2.5rem);
            line-height: 1.12;
            font-weight: 860;
            letter-spacing: 0.01em;
        }

        .shopper-caption {
            margin-top: 0.38rem;
            color: var(--cvs-muted);
            font-size: 1rem;
            line-height: 1.5;
        }

        .header-chip {
            flex: 0 0 auto;
            padding: 0.62rem 0.92rem;
            border-radius: 999px;
            background: linear-gradient(180deg, #14a58e, #08776f);
            border: 1px solid rgba(0, 107, 99, 0.24);
            color: #ffffff;
            font-size: 0.9rem;
            font-weight: 820;
            white-space: nowrap;
            box-shadow: 0 10px 22px rgba(0, 107, 99, 0.2);
        }

        .filter-title {
            margin: 0 0 0.25rem;
            color: var(--cvs-ink);
            font-size: 1.05rem;
            font-weight: 830;
        }

        div[data-testid="stPills"] {
            overflow-x: auto;
            overflow-y: hidden;
            padding-bottom: 0.16rem;
            scrollbar-width: thin;
        }

        div[data-testid="stPills"] [role="radiogroup"] {
            display: flex;
            flex-wrap: nowrap;
            gap: 0.4rem;
            min-width: max-content;
        }

        .filter-note,
        .context-note,
        .section-note {
            color: var(--cvs-muted);
            font-size: 0.86rem;
            line-height: 1.5;
        }

        .context-bar {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 1rem;
            margin: 0.95rem 0 0.82rem;
            padding: 0.86rem 1rem;
            background: var(--cvs-panel-soft);
            border: 1px solid var(--cvs-line);
            border-radius: 8px;
            box-shadow: 0 10px 28px rgba(42, 36, 25, 0.06);
            backdrop-filter: blur(10px);
        }

        .context-main {
            color: var(--cvs-ink);
            font-size: 1.02rem;
            font-weight: 820;
        }

        .shelf-head {
            display: flex;
            align-items: baseline;
            justify-content: space-between;
            gap: 1rem;
            margin: 0.2rem 0 0.55rem;
        }

        .section-title {
            margin: 0;
            color: var(--cvs-ink);
            font-size: 1.08rem;
            font-weight: 840;
        }

        .product-tile,
        .detail-card {
            background: var(--cvs-panel);
            border: 1px solid var(--cvs-line);
            border-radius: 8px;
            box-shadow: var(--cvs-shadow);
        }

        .product-tile {
            padding: 0.92rem;
            margin-bottom: 0.48rem;
        }

        .product-tile.selected {
            border-color: #f0b45f;
            box-shadow: 0 0 0 2px rgba(240, 180, 95, 0.25), 0 10px 26px rgba(26, 35, 47, 0.08);
        }

        .tile-grid {
            display: grid;
            grid-template-columns: minmax(0, 1fr) auto;
            gap: 0.9rem;
            align-items: start;
        }

        .tile-rank {
            color: var(--cvs-muted);
            font-size: 0.78rem;
            font-weight: 760;
        }

        .tile-name {
            margin-top: 0.18rem;
            color: var(--cvs-ink);
            font-size: 1.04rem;
            line-height: 1.35;
            font-weight: 790;
            overflow-wrap: anywhere;
        }

        .tile-meta,
        .signal-row,
        .detail-meta {
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            gap: 0.42rem;
        }

        .tile-meta {
            margin-top: 0.52rem;
        }

        .pill {
            display: inline-flex;
            align-items: center;
            min-height: 27px;
            padding: 0.22rem 0.58rem;
            border-radius: 999px;
            border: 1px solid transparent;
            font-size: 0.78rem;
            font-weight: 780;
            white-space: nowrap;
        }

        .brand-badge-0 { background: #e9f7f4; color: #0f766e; border-color: #b7ebe2; }
        .brand-badge-1 { background: #edf4ff; color: #1d4ed8; border-color: #cfe1ff; }
        .brand-badge-2 { background: #f5efff; color: #6d28d9; border-color: #e2d6ff; }
        .brand-badge-3 { background: #fff3df; color: #9a5b00; border-color: #ffd99b; }
        .brand-badge-4 { background: #eff8e7; color: #3f7617; border-color: #d0ebb6; }
        .brand-badge-5 { background: #f8eef3; color: #9d174d; border-color: #f3cade; }

        .price-pill { background: #f9fbfd; color: var(--cvs-ink); border-color: #e4ebf2; }
        .date-pill { background: #f7fafc; color: var(--cvs-muted); border-color: #e4ebf2; }

        div[data-testid="stDataFrame"] {
            border-radius: 8px;
            overflow: hidden;
            border: 1px solid var(--cvs-line);
            box-shadow: var(--cvs-shadow);
        }

        div[data-testid="stDataFrame"] [role="grid"] {
            background: #ffffff;
        }

        .score-block {
            min-width: 92px;
            text-align: right;
        }

        .score-number {
            display: inline-flex;
            align-items: baseline;
            justify-content: center;
            min-width: 82px;
            padding: 0.38rem 0.48rem;
            border-radius: 8px;
            color: #ffffff;
            font-size: 1.55rem;
            line-height: 1;
            font-weight: 820;
            box-shadow: inset 0 -1px 0 rgba(0, 0, 0, 0.15);
        }

        .score-number small {
            margin-left: 0.08rem;
            font-size: 0.72rem;
            font-weight: 760;
        }

        .score-good { background: #13865f; }
        .score-ok { background: #d18700; }
        .score-bad { background: #c33329; }
        .score-empty { background: #7b8794; color: #ffffff; }

        .score-caption {
            margin-top: 0.32rem;
            color: var(--cvs-muted);
            font-size: 0.74rem;
            font-weight: 730;
        }

        .signal-row {
            margin-top: 0.62rem;
        }

        .signal {
            display: inline-flex;
            align-items: center;
            gap: 0.34rem;
            min-height: 31px;
            padding: 0.28rem 0.62rem;
            border-radius: 8px;
            border: 1px solid transparent;
            font-weight: 800;
        }

        .signal-label {
            color: var(--cvs-muted);
            font-size: 0.72rem;
            font-weight: 760;
        }

        .signal-value {
            color: var(--cvs-ink);
            font-size: 0.9rem;
            line-height: 1;
            white-space: nowrap;
        }

        .signal-good { background: var(--cvs-green-bg); border-color: #bfebd2; color: var(--cvs-green); }
        .signal-mixed { background: var(--cvs-amber-bg); border-color: #ffe0a0; color: var(--cvs-amber); }
        .signal-polar { background: #fff0df; border-color: #ffd1a8; color: #9a4a00; }
        .signal-bad { background: var(--cvs-red-bg); border-color: #ffd1cb; color: var(--cvs-red); }
        .signal-low { background: #eef2f6; border-color: #dce4ec; color: #536170; }
        .volume-high { background: #fff0df; border-color: #ffc98d; }
        .volume-mid { background: #fff5d6; border-color: #ffe4a3; }
        .volume-low { background: #eef2f6; border-color: #dce4ec; }

        .signal-bar,
        .heat-bar {
            display: inline-grid;
            grid-auto-flow: column;
            gap: 0.16rem;
            align-items: center;
        }

        .signal-bar {
            grid-template-columns: repeat(5, 0.78rem);
        }

        .signal-seg,
        .heat-seg {
            height: 0.42rem;
            border-radius: 999px;
            background: #dce4ec;
        }

        .signal-seg.pos { background: #149066; }
        .signal-seg.neg { background: #c33329; }
        .signal-seg.split { background: linear-gradient(90deg, #149066 0 50%, #c33329 50% 100%); }
        .signal-seg.empty { background: #c7d0d9; }

        .heat-bar {
            grid-template-columns: repeat(3, 0.7rem);
        }

        .heat-seg.on { background: #ef7d00; }

        .sample-count {
            color: var(--cvs-muted);
            font-size: 0.8rem;
            line-height: 1.45;
            margin-top: 0.54rem;
        }

        .detail-card {
            padding: 1.05rem;
        }

        .detail-top {
            display: grid;
            grid-template-columns: 76px minmax(0, 1fr);
            gap: 0.82rem;
            align-items: center;
            margin-bottom: 0.5rem;
        }

        .detail-eyebrow {
            color: var(--cvs-muted);
            font-size: 0.78rem;
            font-weight: 760;
        }

        .detail-name {
            margin: 0.18rem 0 0.2rem;
            color: var(--cvs-ink);
            font-size: 1.38rem;
            line-height: 1.28;
            font-weight: 820;
            overflow-wrap: anywhere;
        }

        .decision-band {
            display: grid;
            grid-template-columns: auto minmax(0, 1fr);
            gap: 0.9rem;
            align-items: center;
            padding: 0.82rem;
            border-radius: 8px;
            background: linear-gradient(180deg, #fbfdfc, #f3f8f5);
            border: 1px solid #d9e8df;
            margin: 0.72rem 0 0.88rem;
        }

        .decision-band .score-number {
            min-width: 104px;
            min-height: 62px;
            font-size: 2.1rem;
        }

        .decision-text {
            color: var(--cvs-ink);
            font-size: 1rem;
            font-weight: 780;
        }

        .decision-sub {
            color: var(--cvs-muted);
            font-size: 0.84rem;
            line-height: 1.45;
            margin-top: 0.18rem;
        }

        .review-excerpt,
        .comment-box,
        .competitor-box {
            border-radius: 8px;
            padding: 0.78rem 0.86rem;
        }

        .review-excerpt {
            background: #fbfdff;
            border: 1px solid #dbe8ee;
            border-left: 4px solid #77b7c9;
            margin: 0.82rem 0;
        }

        .box-title {
            color: var(--cvs-muted);
            font-size: 0.78rem;
            font-weight: 790;
            margin-bottom: 0.35rem;
        }

        .box-body {
            color: var(--cvs-ink);
            font-size: 0.91rem;
            line-height: 1.56;
            overflow-wrap: anywhere;
        }

        .comment-grid {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 0.75rem;
            margin-top: 0.75rem;
        }

        .comment-positive { background: var(--cvs-green-bg); border: 1px solid #bee8d3; }
        .comment-negative { background: var(--cvs-red-bg); border: 1px solid #ffd1cb; }
        .comment-positive .box-title { color: var(--cvs-green); }
        .comment-negative .box-title { color: var(--cvs-red); }

        .comment-list {
            margin: 0;
            padding-left: 1rem;
            color: var(--cvs-ink);
            font-size: 0.88rem;
            line-height: 1.5;
        }

        .comment-list li {
            margin-bottom: 0.32rem;
            overflow-wrap: anywhere;
        }

        .competitor-box {
            background: #fffdf8;
            border: 1px solid #eadfca;
            margin-top: 0.75rem;
        }

        .compare-pills {
            display: flex;
            flex-wrap: wrap;
            gap: 0.45rem;
            margin-top: 0.4rem;
        }

        .compare-win { background: var(--cvs-green-bg); color: var(--cvs-green); border-color: #bee8d3; }
        .compare-lose { background: var(--cvs-red-bg); color: var(--cvs-red); border-color: #ffd1cb; }

        .block-container {
            max-width: 430px;
            padding: 0 0.72rem 2.2rem;
        }

        header[data-testid="stHeader"] {
            background: rgba(255, 252, 246, 0.9);
            backdrop-filter: blur(12px);
        }

        section[data-testid="stSidebar"] {
            display: none;
        }

        .shopper-header {
            position: sticky;
            top: 0;
            z-index: 20;
            margin: 0 -0.72rem 0.8rem;
            padding: 0.68rem 0.86rem;
            border-width: 0 0 1px;
            border-radius: 0;
            box-shadow: 0 6px 18px rgba(26, 35, 47, 0.08);
        }

        .radar-mark {
            width: 38px;
            height: 38px;
            font-size: 1.15rem;
            box-shadow: inset 0 0 0 4px rgba(15, 143, 122, 0.16);
        }

        .brand-lockup {
            gap: 0.68rem;
        }

        .shopper-title {
            font-size: 1.38rem;
            line-height: 1.08;
        }

        .shopper-caption {
            margin-top: 0.18rem;
            font-size: 0.82rem;
            line-height: 1.25;
        }

        .header-chip {
            display: none;
        }

        div[data-testid="stExpander"] {
            border: 1px solid var(--cvs-line);
            border-radius: 8px;
            background: rgba(255, 255, 255, 0.84);
            box-shadow: 0 8px 24px rgba(42, 36, 25, 0.06);
            overflow: visible;
        }

        div[data-testid="stExpander"] details summary {
            min-height: 46px;
        }

        .filter-drawer-copy {
            color: var(--cvs-muted);
            font-size: 0.82rem;
            line-height: 1.45;
            margin: -0.2rem 0 0.65rem;
        }

        .context-bar {
            display: block;
            margin: 0.72rem 0 0.82rem;
            padding: 0.7rem 0.78rem;
            border-color: #bfd8b8;
            background: #fbfff7;
        }

        .context-main {
            font-size: 0.95rem;
        }

        .shelf-head {
            margin: 0.78rem 0 0.5rem;
            padding-top: 0.1rem;
        }

        .section-title {
            font-size: 1.12rem;
        }

        .product-row {
            display: grid;
            grid-template-columns: 34px 74px minmax(0, 1fr);
            gap: 0.66rem;
            align-items: center;
            padding: 0.72rem;
            margin-top: 0.48rem;
            background: var(--cvs-panel);
            border: 1px solid var(--cvs-line);
            border-radius: 8px;
            box-shadow: 0 8px 22px rgba(42, 36, 25, 0.07);
        }

        .rank-mark {
            color: var(--cvs-ink);
            font-size: 1.42rem;
            line-height: 1;
            font-weight: 840;
            text-align: center;
        }

        .product-visual {
            width: 74px;
            height: 74px;
            border-radius: 8px;
            display: grid;
            place-items: center;
            color: var(--tile-fg, #ffffff);
            background: var(--tile-bg, #0f8f7a);
            border: 1px solid var(--tile-border, rgba(0,0,0,0.1));
            box-shadow: inset 0 -18px 0 rgba(0, 0, 0, 0.1);
            overflow: hidden;
        }

        .visual-brand {
            padding: 0 0.35rem;
            font-size: 1.08rem;
            line-height: 1;
            font-weight: 900;
            letter-spacing: 0;
            text-align: center;
            white-space: nowrap;
        }

        .row-main {
            min-width: 0;
        }

        .row-top {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.42rem;
        }

        .row-name {
            margin-top: 0.38rem;
            color: var(--cvs-ink);
            font-size: 1rem;
            line-height: 1.32;
            font-weight: 820;
            overflow-wrap: anywhere;
        }

        .row-signals {
            display: grid;
            grid-template-columns: auto 1fr;
            gap: 0.32rem 0.5rem;
            align-items: center;
            margin-top: 0.42rem;
        }

        .row-score {
            font-size: 2rem;
            line-height: 1;
            font-weight: 900;
        }

        .row-score.score-good {
            background: transparent;
            color: #13865f;
        }

        .row-score.score-ok {
            background: transparent;
            color: #d18700;
        }

        .row-score.score-bad {
            background: transparent;
            color: #c33329;
        }

        .row-score.score-empty {
            background: transparent;
            color: #7b8794;
        }

        .row-score small {
            color: var(--cvs-muted);
            font-size: 0.86rem;
            font-weight: 760;
        }

        .row-meta {
            color: var(--cvs-muted);
            font-size: 0.8rem;
            font-weight: 720;
        }

        .row-consensus {
            display: inline-flex;
            align-items: center;
            gap: 0.38rem;
            min-height: 31px;
            padding: 0.28rem 0.5rem;
            border-radius: 8px;
            border: 1px solid #dce4ec;
            background: #ffffff;
            color: var(--cvs-ink);
            font-size: 0.88rem;
            line-height: 1;
            font-weight: 820;
            white-space: nowrap;
        }

        .row-consensus-segments {
            display: inline-grid;
            grid-auto-flow: column;
            gap: 0.12rem;
            align-items: center;
        }

        .row-consensus-seg {
            width: 0.48rem;
            height: 0.48rem;
            border-radius: 999px;
            background: #d7dee6;
        }

        .row-consensus-seg.pos { background: #13865f; }
        .row-consensus-seg.neg { background: #c33329; }
        .row-consensus-seg.split { background: #d18700; }
        .row-consensus-seg.empty { background: #c8d1da; }

        div[data-testid="stHorizontalBlock"]:has(.product-row) {
            align-items: stretch;
        }

        div[data-testid="stHorizontalBlock"]:has(.product-row) div[data-testid="column"]:last-child {
            display: flex;
        }

        .row-actions {
            height: 100%;
            min-height: 112px;
            display: flex;
            width: 100%;
        }

        .row-actions div[data-testid="stButton"] {
            width: 100%;
            height: 100%;
        }

        .row-actions div[data-testid="stButton"] > button {
            width: 100%;
            min-width: 48px;
            min-height: 112px;
            height: 100%;
            border-radius: 8px;
            color: var(--cvs-teal-dark);
            border-color: #9ed6cf;
            background: #f3fffc;
            padding: 0;
            font-size: 1.1rem;
            font-weight: 820;
        }

        .inline-detail {
            margin: 0.42rem 0 0.72rem;
        }

        .detail-card {
            padding: 0.82rem;
            box-shadow: 0 8px 22px rgba(42, 36, 25, 0.08);
        }

        .detail-top {
            grid-template-columns: 70px minmax(0, 1fr);
            gap: 0.72rem;
        }

        .detail-name {
            font-size: 1.12rem;
        }

        .detail-brand-row {
            display: flex;
            align-items: center;
            gap: 0.42rem;
            flex-wrap: wrap;
        }

        .decision-band {
            grid-template-columns: 94px minmax(0, 1fr);
            padding: 0.72rem;
        }

        .decision-band .score-number {
            min-width: 86px;
            min-height: 58px;
            font-size: 2rem;
        }

        .distribution-card {
            padding: 0.72rem;
            margin-top: 0.7rem;
            border: 1px solid #e3e8dd;
            border-radius: 8px;
            background: #fffefa;
        }

        .distribution-title,
        .volume-title {
            color: var(--cvs-ink);
            font-size: 0.9rem;
            font-weight: 820;
            margin-bottom: 0.42rem;
        }

        .dist-bar {
            display: flex;
            overflow: hidden;
            height: 32px;
            border-radius: 8px;
            background: #edf1ef;
        }

        .dist-seg {
            display: grid;
            place-items: center;
            min-width: 2.1rem;
            color: #ffffff;
            font-size: 0.82rem;
            font-weight: 840;
        }

        .dist-pos { background: #2e7d32; }
        .dist-neu { background: #8a5a00; }
        .dist-neg { background: #c62828; }

        .dist-labels {
            display: flex;
            justify-content: space-between;
            gap: 0.35rem;
            margin-top: 0.38rem;
            font-size: 0.82rem;
            font-weight: 800;
        }

        .dist-labels span:nth-child(1) { color: #2c7d31; }
        .dist-labels span:nth-child(2) { color: #c57400; }
        .dist-labels span:nth-child(3) { color: #c33329; }

        .distribution-empty {
            color: var(--cvs-muted);
            font-size: 0.86rem;
            font-weight: 760;
            padding: 0.58rem 0.66rem;
            border-radius: 8px;
            background: #f4f6f8;
        }

        .volume-card {
            padding: 0.72rem 0 0;
            margin-top: 0.72rem;
            border-top: 1px solid var(--cvs-line);
        }

        .volume-meter {
            height: 14px;
            overflow: hidden;
            border-radius: 999px;
            background: #edf0ec;
        }

        .volume-fill {
            height: 100%;
            border-radius: 999px;
            background: linear-gradient(90deg, #0f8f7a, #18a69b);
        }

        .volume-meter.empty .volume-fill {
            width: 0;
        }

        .detail-action {
            display: block;
            margin-top: 0.78rem;
            padding: 0.72rem 0.9rem;
            border-radius: 8px;
            background: linear-gradient(180deg, #0ca095, #087a74);
            color: #ffffff !important;
            text-align: center;
            text-decoration: none !important;
            font-size: 1rem;
            font-weight: 860;
            box-shadow: 0 10px 20px rgba(8, 122, 116, 0.18);
        }

        .discussion-links {
            margin-top: 0.78rem;
            padding: 0.72rem 0.82rem;
            border-radius: 8px;
            border: 1px solid #d8e7e3;
            background: #f7fffd;
        }

        .discussion-title {
            color: var(--cvs-ink);
            font-size: 0.92rem;
            font-weight: 840;
            margin-bottom: 0.45rem;
        }

        .discussion-list {
            display: flex;
            flex-wrap: wrap;
            gap: 0.42rem;
            margin: 0;
            padding: 0;
            list-style: none;
        }

        .discussion-link {
            display: inline-flex;
            align-items: center;
            min-height: 32px;
            padding: 0.28rem 0.62rem;
            border-radius: 8px;
            background: #0c8f84;
            color: #ffffff !important;
            text-decoration: none !important;
            font-weight: 820;
        }

        .discussion-more {
            margin-top: 0.42rem;
            color: var(--cvs-muted);
            font-size: 0.82rem;
            font-weight: 760;
        }

        @media (max-width: 920px) {
            .context-bar,
            .shelf-head {
                display: block;
            }

            .header-chip,
            .section-note {
                margin-top: 0.4rem;
            }

            .tile-grid,
            .comment-grid {
                grid-template-columns: 1fr;
            }

            .score-block {
                text-align: left;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_header() -> None:
    st.markdown(
        """
        <div class="shopper-header">
            <div class="brand-lockup">
                <div class="radar-mark" aria-hidden="true">◎</div>
                <div>
                    <h1 class="shopper-title">CVS Radar 超商商品雷達</h1>
                    <div class="shopper-caption">站在架前先看這裡：分數、共識、聲量與真實心得，幫你判斷值不值得買。</div>
                </div>
            </div>
            <div class="header-chip">購買決策視圖</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_sidebar() -> dict[str, object]:
    # Data source is fixed to the local precomputed results (built from the
    # crawled posts.jsonl). No user-facing source picker — shoppers never choose.
    return {"source": "results", "crawl_pages": 5}


def _render_filters(
    source: str,
    posts: object,
    options: list[str],
    *,
    selected_category: str,
    selected_brand: str,
) -> dict[str, object]:
    with st.expander("調整篩選", expanded=False):
        st.markdown('<div class="filter-title">縮小架上商品</div>', unsafe_allow_html=True)
        recent_days = None
        start_date = None
        end_date = None

        if source != "results":
            time_mode = st.radio("時間", ["近 N 天", "起訖日期"], horizontal=True)
            if time_mode == "近 N 天":
                recent_days = int(st.number_input("近 N 天", min_value=0, max_value=3650, value=30, step=1))
            else:
                today = datetime.now().date()
                default_start = today - timedelta(days=30)
                start_date = st.date_input("起始日期", value=default_start)
                end_date = st.date_input("結束日期", value=today)

            options = brand_options(
                posts,
                start_date=start_date,
                end_date=end_date,
                recent_days=recent_days,
            )
            if selected_brand not in options:
                selected_brand = ALL_BRANDS

        sort_by = st.selectbox("排序", ["評分最高", "討論最多", "最新發文", "評分最低"], index=0)
        with st.popover("更多條件", use_container_width=True):
            use_min_score = st.checkbox("最低分數", value=False)
            min_score = None
            if use_min_score:
                min_score = float(st.number_input("分數至少", min_value=0.0, max_value=100.0, value=60.0, step=1.0))

            use_min_n_eff = st.checkbox("最低有效樣本", value=False)
            min_n_eff = None
            if use_min_n_eff:
                min_n_eff = float(st.number_input("有效樣本至少", min_value=0.0, value=1.0, step=0.5))

            min_posts = int(st.number_input("最少貼文", min_value=0, value=0, step=1))
            min_comments = int(st.number_input("最少留言", min_value=0, value=0, step=1))

    return {
        "selected_brand": selected_brand,
        "selected_category": selected_category,
        "recent_days": recent_days,
        "start_date": start_date,
        "end_date": end_date,
        "min_score": min_score,
        "min_n_eff": min_n_eff,
        "min_posts": min_posts,
        "min_comments": min_comments,
        "sort_by": sort_by,
    }


def _query_precomputed_reports(reports, query) -> ProductQueryResult:
    filtered = filter_reports(
        reports,
        brand=query.brand,
        min_score=query.min_score,
        min_n_eff=query.min_n_eff,
        min_posts=query.min_posts,
        min_comments=query.min_comments,
        limit=query.limit,
    )
    return ProductQueryResult(
        filters={
            "brand": query.brand,
            "start_date": str(query.start_date) if query.start_date else None,
            "end_date": str(query.end_date) if query.end_date else None,
            "recent_days": query.recent_days,
            "min_score": query.min_score,
            "min_n_eff": query.min_n_eff,
            "min_posts": query.min_posts,
            "min_comments": query.min_comments,
            "limit": query.limit,
            "internal": query.internal,
        },
        brands=brand_summaries_from_reports(filtered),
        reports=filtered,
    )


def _render_context_bar(result: ProductQueryResult, *, selected_brand: str, sort_by: str, source: str) -> None:
    count = len(result.reports)
    brand_label = selected_brand if selected_brand != ALL_BRANDS else "全部品牌"
    if count:
        best = result.reports[0]
        best_text = f"目前最值得先看：{best.product_name}（{_format_score(best.fair_score)} 分）"
    else:
        best_text = "目前沒有符合條件的商品"
    st.markdown(
        f"""
        <div class="context-bar">
            <div>
                <div class="context-main">{escape(best_text)}</div>
                <div class="context-note">找到 {count:,} 項商品，品牌：{escape(brand_label)}，排序：{escape(sort_by)}。</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_shopper_view(result: ProductQueryResult, *, selection_key: str, search_query: str = "") -> None:
    rows = _shopper_rows(result)
    if not rows:
        if search_query.strip():
            st.info("目前條件下沒有符合的商品。可以清除搜尋字串，或放寬品牌、分類或更多條件。")
            return
        st.info("目前條件下沒有符合的商品。可以放寬品牌、分類或更多條件。")
        return

    state_key = f"shopper_open_idx::{selection_key}"
    if state_key not in st.session_state or int(st.session_state[state_key]) >= len(rows):
        st.session_state[state_key] = -1

    page_size_key = f"shopper_page_size::{selection_key}"
    if page_size_key not in st.session_state:
        st.session_state[page_size_key] = PAGE_SIZE_STEP
    page_size = min(int(st.session_state[page_size_key]), len(rows))

    st.markdown(
        """
        <div class="shelf-head">
            <p class="section-title">架上候選商品</p>
            <span class="section-note">點選箭頭後，單品判斷會直接出現在該列下方。</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    for idx, row in enumerate(rows[:page_size]):
        is_open = int(st.session_state[state_key]) == idx
        card_col, toggle_col = st.columns([10, 2], vertical_alignment="center")
        with card_col:
            st.markdown(_product_row_html(row), unsafe_allow_html=True)
        with toggle_col:
            st.markdown('<div class="row-actions">', unsafe_allow_html=True)
            if st.button("收合" if is_open else "展開", key=f"product_toggle::{selection_key}::{idx}", help="切換單品判斷"):
                st.session_state[state_key] = -1 if is_open else idx
                st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)
        if is_open:
            st.markdown('<div class="inline-detail">', unsafe_allow_html=True)
            st.markdown(_product_detail_html(row), unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)

    if page_size < len(rows):
        remaining = len(rows) - page_size
        if st.button(f"顯示更多（還有 {remaining:,} 項）", key=f"show_more::{selection_key}", use_container_width=True):
            st.session_state[page_size_key] = page_size + PAGE_SIZE_STEP
            st.rerun()


def _shopper_rows(result: ProductQueryResult) -> list[dict[str, Any]]:
    rows = product_rows(result)
    post_metadata = _load_post_metadata()
    for row, report in zip(rows, result.reports):
        row["貼文數"] = report.n_posts
        row["留言數"] = report.n_comments
        row["有效樣本"] = report.n_eff
        row["信心"] = report.confidence
        row["貼文資訊"] = [_post_link_info(url, post_metadata) for url in row.get("貼文連結", [])]
    return rows


def _product_row_html(row: dict[str, Any]) -> str:
    consensus_label, consensus_class, segments = _consensus_signal(str(row.get("consensus") or "資料不足"))
    volume_label, volume_class, _level = _volume_signal(str(row.get("討論聲量") or "聲量不足"))
    score_class = _score_class(row.get("fair_score"))
    return f"""
    <div class="product-row">
        <div class="rank-mark">{escape(str(row.get("排名", "-")))}</div>
        {_product_visual_html(row)}
        <div class="row-main">
            <div class="row-top">
                <span class="row-meta">{_row_meta_html(row)}</span>
            </div>
            <div class="row-name">{escape(str(row.get("商品") or "-"))}</div>
            <div class="row-signals">
                <div class="row-score {score_class}">{escape(_format_score(row.get("fair_score")))}<small>/100</small></div>
                <div>
                    {_row_consensus_signal_html(row, consensus_label, consensus_class, segments)}
                    <span class="signal {volume_class}"><span class="signal-value">{escape(volume_label)}</span></span>
                </div>
            </div>
        </div>
    </div>
    """


def _product_visual_html(row: dict[str, Any]) -> str:
    brand = str(row.get("品牌") or "其他")
    spec = BRAND_LOGO_SPECS.get(brand, BRAND_LOGO_SPECS["其他"])
    return (
        '<div class="product-visual" '
        f'style="--tile-bg:{escape(str(spec["fg"]))};--tile-fg:{escape(str(spec["bg"]))};'
        f'--tile-border:{escape(str(spec["border"]))};">'
        f'<div class="visual-brand">{escape(str(spec["text"]))}</div>'
        "</div>"
    )


def _product_detail_html(row: dict[str, Any]) -> str:
    score = row.get("fair_score")
    positive_comments = _split_comments(row.get("正向留言"))
    negative_comments = _split_comments(row.get("負向留言"))
    excerpt = str(row.get("心得節錄") or "").strip()
    return f"""
    <div class="detail-card">
        <div class="decision-band">
            <div class="score-number {_score_class(score)}">{escape(_format_score(score))}<small>/100</small></div>
            <div>
                <div class="decision-text">{escape(_decision_text(score))}</div>
                <div class="decision-sub">{escape(_sample_count(row))}</div>
                <div class="detail-meta">
                    <span class="pill date-pill">最新發文 {escape(str(row.get("最新發文") or "未知"))}</span>
                </div>
            </div>
        </div>
        <div class="comment-grid">
            {_comment_box("大家喜歡的點", positive_comments, "positive")}
            {_comment_box("需要留意的點", negative_comments, "negative")}
        </div>
        {_excerpt_html(excerpt)}
        {_consensus_distribution_html(row)}
        {_volume_meter_html(row)}
        {_competitor_html(row)}
        {_review_action_html(row)}
    </div>
    """


def _row_meta_html(row: dict[str, Any]) -> str:
    price = _format_price(row.get("價格"))
    parts = []
    if price != "價格未明":
        parts.append(price)
    parts.extend([
        str(row.get("分類") or "其他"),
        _row_sample_hint(row),
    ])
    latest = relative_date_label(str(row.get("最新發文") or ""))
    if latest:
        parts.append(latest)
    return escape(" · ".join(parts))


def _consensus_signal(consensus: str) -> tuple[str, str, tuple[str, ...]]:
    return CONSENSUS_SIGNALS.get(consensus, CONSENSUS_SIGNALS["資料不足"])


def _row_consensus_signal_html(
    row: dict[str, Any],
    fallback_label: str,
    fallback_class: str,
    segments: tuple[str, ...],
) -> str:
    distribution = row.get("共識分布")
    if not _valid_distribution(distribution):
        return f'<span class="signal {fallback_class}"><span class="signal-value">{escape(fallback_label)}</span></span>'

    positive = round(float(distribution[0]))
    segment_html = "".join(
        f'<span class="row-consensus-seg {escape(segment)}" aria-hidden="true"></span>' for segment in segments
    )
    return (
        f'<span class="row-consensus" aria-label="正向 {positive}%">'
        f'<span class="row-consensus-segments">{segment_html}</span>'
        f"<span>正向 {positive}%</span>"
        "</span>"
    )


def _row_sample_hint(row: dict[str, Any]) -> str:
    comments = _positive_int(row.get("留言數"))
    posts = _positive_int(row.get("貼文數"))
    if comments > 0:
        return f"{comments:,} 則評價"
    if posts > 0:
        return f"{posts:,} 篇心得"
    return "樣本不足"


def _positive_int(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _volume_signal(volume: str) -> tuple[str, str, int]:
    return VOLUME_SIGNALS.get(volume, VOLUME_SIGNALS["聲量不足"])


def _consensus_distribution_html(row: dict[str, Any]) -> str:
    distribution = row.get("共識分布")
    if not _valid_distribution(distribution):
        return (
            '<div class="distribution-card">'
            '<div class="distribution-title">共識分布</div>'
            '<div class="distribution-empty">資料不足</div>'
            "</div>"
        )
    positive, neutral, negative = distribution
    return (
        '<div class="distribution-card">'
        '<div class="distribution-title">共識分布</div>'
        '<div class="dist-bar">'
        f'<span class="dist-seg dist-pos" style="width:{positive}%">{positive}%</span>'
        f'<span class="dist-seg dist-neu" style="width:{neutral}%">{neutral}%</span>'
        f'<span class="dist-seg dist-neg" style="width:{negative}%">{negative}%</span>'
        "</div>"
        '<div class="dist-labels">'
        f"<span>正向 {positive}%</span><span>中立 {neutral}%</span><span>負向 {negative}%</span>"
        "</div>"
        "</div>"
    )


def _valid_distribution(value: object) -> bool:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return False
    return all(isinstance(item, (int, float)) and item >= 0 for item in value)


def _volume_meter_html(row: dict[str, Any]) -> str:
    volume = str(row.get("討論聲量") or "聲量不足")
    volume_label, volume_class, _level = _volume_signal(volume)
    width = _volume_meter_width(row)
    meter_class = "volume-meter" if width > 0 else "volume-meter empty"
    return (
        '<div class="volume-card">'
        '<div class="volume-title">聲量指標</div>'
        f'<div class="{meter_class}">'
        f'<div class="volume-fill" style="width:{width}%"></div>'
        "</div>"
        '<div class="signal-row">'
        f'<span class="signal {volume_class}"><span class="signal-value">{escape(volume_label)}</span></span>'
        f'<span class="sample-count">{escape(_sample_count(row))}</span>'
        "</div>"
        "</div>"
    )


def _volume_meter_width(row: dict[str, Any]) -> int:
    count = _real_sample_size(row)
    if count <= 0:
        return 0
    return min(100, max(12, round(count / 30 * 100)))


def _real_sample_size(row: dict[str, Any]) -> float:
    for key in ("留言數", "有效樣本", "貼文數"):
        try:
            value = float(row.get(key) or 0)
        except (TypeError, ValueError):
            value = 0
        if value > 0:
            return value
    return 0


def _excerpt_html(excerpt: str) -> str:
    if not excerpt:
        return (
            '<div class="review-excerpt">'
            '<div class="box-title">原PO心得節錄</div>'
            '<div class="box-body">目前沒有可顯示的心得節錄。</div>'
            "</div>"
        )
    return (
        '<div class="review-excerpt">'
        '<div class="box-title">原PO心得節錄</div>'
        f'<div class="box-body">{escape(excerpt)}</div>'
        "</div>"
    )


def _comment_box(title: str, comments: list[str], tone: str) -> str:
    css_class = "comment-positive" if tone == "positive" else "comment-negative"
    fallback = "目前沒有代表性正向留言" if tone == "positive" else "目前沒有代表性負向留言"
    items = comments or [fallback]
    body = "".join(f"<li>{escape(comment)}</li>" for comment in items)
    return (
        f'<div class="comment-box {css_class}">'
        f'<div class="box-title">{escape(title)}</div>'
        f'<ul class="comment-list">{body}</ul>'
        "</div>"
    )


def _competitor_html(row: dict[str, Any]) -> str:
    other = int(row.get("偏好他牌") or 0)
    own = int(row.get("偏好本品") or 0)
    mentions = int(row.get("競品提及") or 0)
    brands = str(row.get("提及競品") or "無")
    if mentions == 0 and other == 0 and own == 0:
        body = "目前幾乎沒有和其他品牌直接比較。"
    elif own > other:
        body = "比較留言偏向本品。"
    elif other > own:
        body = "比較留言偏向他牌，購買前可以多想一下。"
    else:
        body = "比較留言沒有明顯偏向。"
    return (
        '<div class="competitor-box">'
        '<div class="box-title">競品比較</div>'
        f'<div class="box-body">{escape(body)} 提及競品：{escape(brands)}</div>'
        '<div class="compare-pills">'
        f'<span class="pill compare-win">本品較優 {own:,}</span>'
        f'<span class="pill compare-lose">他牌較優 {other:,}</span>'
        f'<span class="pill price-pill">競品提及 {mentions:,}</span>'
        "</div>"
        "</div>"
    )


def _review_action_html(row: dict[str, Any]) -> str:
    links = _post_links(row.get("貼文連結"))
    if len(links) == 1:
        href = links[0]
        return f'<a class="detail-action" href="{escape(href)}" target="_blank" rel="noopener noreferrer">查看心得</a>'
    if links:
        visible_links = links[:5]
        post_info = row.get("貼文資訊")
        items = "".join(
            '<li>'
            f'<a class="discussion-link" href="{escape(href)}" target="_blank" rel="noopener noreferrer">'
            f"{escape(_post_link_label(post_info, idx, href))}</a>"
            "</li>"
            for idx, href in enumerate(visible_links, 1)
        )
        more = len(links) - len(visible_links)
        more_html = f'<div class="discussion-more">還有 {more} 篇</div>' if more > 0 else ""
        return (
            '<div class="discussion-links">'
            f'<div class="discussion-title">相關討論（{len(links)} 篇）</div>'
            f'<ul class="discussion-list">{items}</ul>'
            f"{more_html}"
            "</div>"
        )
    return '<span class="detail-action" aria-disabled="true">查看心得</span>'


def _post_links(value: object) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return []
    return [str(link).strip() for link in value if str(link).strip()]


def _post_link_info(url: object, metadata: dict[str, dict[str, str]]) -> dict[str, str]:
    href = str(url or "").strip()
    info = metadata.get(href, {})
    return {
        "url": href,
        "title": _title_excerpt(info.get("title", "")),
        "date": str(info.get("date") or "").strip(),
    }


def _post_link_label(post_info: object, idx: int, href: str) -> str:
    info: dict[str, str] = {}
    if isinstance(post_info, list) and idx - 1 < len(post_info) and isinstance(post_info[idx - 1], dict):
        candidate = post_info[idx - 1]
        if str(candidate.get("url") or "").strip() == href:
            info = {str(key): str(value) for key, value in candidate.items()}

    title = str(info.get("title") or "").strip()
    date_text = str(info.get("date") or "").strip()
    if title and date_text:
        return f"{title} · {date_text}"
    if title:
        return title
    if date_text:
        return f"貼文{idx} · {date_text}"
    return f"貼文{idx}"


def _title_excerpt(title: str, max_chars: int = 18) -> str:
    text = " ".join(str(title or "").split())
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}..."


def _split_comments(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    return [item.strip() for item in text.split(" / ") if item.strip()]


def _format_price(price: object) -> str:
    if price in (None, ""):
        return "價格未明"
    try:
        return f"${int(price)}"
    except (TypeError, ValueError):
        return str(price)


def _format_score(score: object) -> str:
    if score is None:
        return "--"
    try:
        return f"{float(score):.0f}"
    except (TypeError, ValueError):
        return "--"


def _score_class(score: object) -> str:
    try:
        value = float(score)
    except (TypeError, ValueError):
        return "score-empty"
    if value >= 70:
        return "score-good"
    if value >= 50:
        return "score-ok"
    return "score-bad"


def _decision_text(score: object) -> str:
    try:
        value = float(score)
    except (TypeError, ValueError):
        return "資料還不夠，先別只靠分數決定。"
    if value >= 70:
        return "多數訊號偏正面，可以優先考慮。"
    if value >= 50:
        return "評價有可買理由，也有需要比較的地方。"
    return "目前訊號偏弱，除非很想嘗鮮否則先保守。"


def _sample_count(row: dict[str, Any]) -> str:
    posts = int(row.get("貼文數") or 0)
    comments = int(row.get("留言數") or 0)
    n_eff = row.get("有效樣本")
    try:
        n_eff_text = f"{float(n_eff):.1f}"
    except (TypeError, ValueError):
        n_eff_text = "-"
    return f"{posts:,} 篇心得 / {comments:,} 則留言，有效樣本 {n_eff_text}"


if __name__ == "__main__":
    main()
