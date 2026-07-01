"""Shopper-facing Streamlit UI for CVS Radar."""

from __future__ import annotations

from datetime import datetime, timedelta
from html import escape
from typing import Any
from urllib.parse import quote

import streamlit as st

from cvs_radar.app_helpers import (
    ALL_BRANDS,
    brand_options,
    build_product_query,
    load_results_or_none,
    load_posts,
    product_rows,
)
from cvs_radar.service import ProductQueryResult, brand_summaries_from_reports, filter_reports, query_products


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
        "bars": ("#0c8f48", "#f58220", "#d71920"),
    },
    "全家": {
        "text": "全家",
        "bg": "#ffffff",
        "fg": "#005bac",
        "border": "#00a650",
        "bars": ("#005bac", "#00a650", "#005bac"),
    },
    "萊爾富": {
        "text": "HiLife",
        "bg": "#fff7f5",
        "fg": "#d71920",
        "border": "#d71920",
        "bars": ("#d71920", "#f15a24", "#d71920"),
    },
    "OK": {
        "text": "OK",
        "bg": "#fff8df",
        "fg": "#c45f00",
        "border": "#f4a300",
        "bars": ("#f4a300", "#ef7d00", "#c45f00"),
    },
    "美聯社": {
        "text": "美聯",
        "bg": "#f7f1ff",
        "fg": "#6d2ea0",
        "border": "#7a3db8",
        "bars": ("#7a3db8", "#2e9d57", "#7a3db8"),
    },
    "其他": {
        "text": "店",
        "bg": "#f4f6f8",
        "fg": "#536170",
        "border": "#a7b2bf",
        "bars": ("#a7b2bf", "#c7d0d9", "#a7b2bf"),
    },
}


def main() -> None:
    st.set_page_config(page_title="CVS Radar", page_icon="🛒", layout="wide")
    _inject_css()
    _render_header()

    controls = _render_sidebar()

    posts = None
    reports = None
    source = str(controls["source"])
    if source == "results":
        loaded = load_results_or_none()
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

    filters = _render_filters(source, posts, options)
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

    if filters["selected_category"] != "全部分類":
        result = ProductQueryResult(
            filters=result.filters,
            brands=result.brands,
            reports=[r for r in result.reports if (r.category or "其他") == filters["selected_category"]],
        )

    sorted_reports = _sort_reports(result.reports, str(filters["sort_by"]))
    sorted_reports = sorted_reports[: int(filters["limit"])]
    result_filters = dict(result.filters)
    result_filters["limit"] = filters["limit"]
    result = ProductQueryResult(
        filters=result_filters,
        brands=brand_summaries_from_reports(sorted_reports),
        reports=sorted_reports,
    )

    _render_context_bar(result, selected_brand=str(filters["selected_brand"]), sort_by=str(filters["sort_by"]), source=source)
    selection_key = "|".join(
        str(filters[k])
        for k in ("selected_brand", "selected_category", "sort_by", "limit", "start_date", "end_date", "recent_days")
    )
    _render_shopper_view(result, selection_key=selection_key)


def _sort_reports(reports: list, sort_by: str) -> list:
    if sort_by == "評分最低":
        return sorted(reports, key=lambda r: (r.fair_score is None, r.fair_score if r.fair_score is not None else 0.0))
    if sort_by == "最新發文":
        return sorted(reports, key=lambda r: r.latest_post_date or datetime.min, reverse=True)
    if sort_by == "討論最多":
        return sorted(reports, key=lambda r: r.n_posts + r.n_comments, reverse=True)
    return sorted(reports, key=lambda r: (r.fair_score is not None, r.fair_score or 0.0), reverse=True)


def _inject_css() -> None:
    st.markdown(
        """
        <style>
        :root {
            --cvs-ink: #18232f;
            --cvs-muted: #657384;
            --cvs-line: #dde5ed;
            --cvs-panel: #ffffff;
            --cvs-warm: #fff8ed;
            --cvs-green: #12805c;
            --cvs-green-bg: #e8f6ef;
            --cvs-amber: #a86200;
            --cvs-amber-bg: #fff3d5;
            --cvs-red: #b42318;
            --cvs-red-bg: #fff0ed;
            --cvs-blue: #245fba;
            --cvs-blue-bg: #edf5ff;
        }

        .stApp {
            background:
                linear-gradient(180deg, #fff8ed 0, #f8fbfd 235px, #f8fbfd 100%);
            color: var(--cvs-ink);
        }

        .block-container {
            max-width: 1320px;
            padding-top: 1.35rem;
            padding-bottom: 3rem;
        }

        section[data-testid="stSidebar"] {
            background: #fffdf8;
            border-right: 1px solid #eadfca;
        }

        .shopper-header {
            display: flex;
            align-items: flex-end;
            justify-content: space-between;
            gap: 1rem;
            padding: 0.25rem 0 0.9rem;
            border-bottom: 1px solid rgba(101, 115, 132, 0.22);
            margin-bottom: 0.95rem;
        }

        .shopper-title {
            margin: 0;
            color: var(--cvs-ink);
            font-size: 2rem;
            line-height: 1.12;
            font-weight: 780;
            letter-spacing: 0;
        }

        .shopper-caption {
            margin-top: 0.42rem;
            color: var(--cvs-muted);
            font-size: 0.98rem;
            line-height: 1.5;
        }

        .header-chip {
            flex: 0 0 auto;
            padding: 0.44rem 0.72rem;
            border-radius: 999px;
            background: #ffffff;
            border: 1px solid #e2d6bf;
            color: #75501b;
            font-size: 0.86rem;
            font-weight: 760;
            white-space: nowrap;
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
            margin: 0.9rem 0 0.75rem;
            padding: 0.74rem 0.9rem;
            background: rgba(255, 255, 255, 0.78);
            border: 1px solid var(--cvs-line);
            border-radius: 8px;
        }

        .context-main {
            color: var(--cvs-ink);
            font-size: 1rem;
            font-weight: 760;
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
            font-size: 1.04rem;
            font-weight: 780;
        }

        .product-tile,
        .detail-card {
            background: var(--cvs-panel);
            border: 1px solid var(--cvs-line);
            border-radius: 8px;
            box-shadow: 0 10px 26px rgba(26, 35, 47, 0.07);
        }

        .product-tile {
            padding: 0.92rem;
            margin-bottom: 0.48rem;
        }

        .product-tile.selected {
            border-color: #f0b45f;
            box-shadow: 0 0 0 2px rgba(240, 180, 95, 0.25), 0 10px 26px rgba(26, 35, 47, 0.08);
        }

        /*
         * The shopper shelf uses st.dataframe as a navigational grid: logo
         * images need ImageColumn, and any selected cell should switch the
         * right-side product detail. Suppress glide's read-only edit overlay.
         */
        div[class*="gdg-d19meir1"],
        div.gdg-style:has(.gdg-clip-region) {
            display: none !important;
            visibility: hidden !important;
            pointer-events: none !important;
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
            padding: 0.2rem 0.54rem;
            border-radius: 999px;
            border: 1px solid transparent;
            font-size: 0.78rem;
            font-weight: 740;
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
        .score-empty { background: #7b8794; }

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
            padding: 0.22rem 0.54rem;
            border-radius: 8px;
            border: 1px solid transparent;
            font-weight: 760;
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

        .signal-good { background: var(--cvs-green-bg); border-color: #bee8d3; color: var(--cvs-green); }
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

        .detail-eyebrow {
            color: var(--cvs-muted);
            font-size: 0.78rem;
            font-weight: 760;
        }

        .detail-name {
            margin: 0.18rem 0 0.7rem;
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
            background: #f8fafc;
            border: 1px solid #e4ebf2;
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
            background: #fffdf8;
            border: 1px solid #eadfca;
            border-left: 4px solid #f0b45f;
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
            background: #f8fafc;
            border: 1px solid #e4ebf2;
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

        @media (max-width: 920px) {
            .shopper-header,
            .context-bar,
            .shelf-head {
                display: block;
            }

            .header-chip,
            .section-note {
                margin-top: 0.4rem;
            }

            .tile-grid,
            .decision-band,
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
            <div>
                <h1 class="shopper-title">CVS Radar 超商商品雷達</h1>
                <div class="shopper-caption">站在架前先看這裡：分數、共識、聲量與真實心得，幫你判斷值不值得買。</div>
            </div>
            <div class="header-chip">購買決策視圖</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_sidebar() -> dict[str, object]:
    with st.sidebar:
        st.header("今天想找什麼？")
        st.caption("預設使用已計算好的 results 快照；開發或驗證時才切換其他來源。")

        labels = {
            "results": "最新 results 快照",
            "demo": "離線示範資料",
            "stored": "本機已爬資料",
            "crawl": "即時爬 PTT CVS",
        }
        default_source = "results" if load_results_or_none() is not None else "demo"
        crawl_pages = 5
        with st.expander("資料來源設定", expanded=False):
            source = st.selectbox(
                "資料來源",
                options=list(labels),
                index=list(labels).index(default_source),
                format_func=lambda value: labels[str(value)],
            )
            if source == "results":
                loaded = load_results_or_none()
                if loaded is not None:
                    loaded_reports, loaded_profiles = loaded
                    st.caption(f"{len(loaded_reports):,} 項商品結果，{len(loaded_profiles):,} 個帳號輪廓")
                else:
                    st.warning("目前沒有 results，主畫面會改用 demo。")
            elif source == "stored":
                from cvs_radar.store import store_stats

                stats = store_stats()
                st.caption(f"{stats['post_count']:,} 篇文，{stats['comment_count']:,} 則留言")
            elif source == "crawl":
                st.warning("crawl 會連線到 PTT。")
                crawl_pages = int(st.number_input("PTT 頁數", min_value=1, max_value=50, value=5, step=1))
            else:
                st.caption("demo 不連網，適合快速預覽。")

    return {"source": str(source), "crawl_pages": crawl_pages}


def _render_filters(source: str, posts: object, options: list[str]) -> dict[str, object]:
    with st.container(border=True):
        st.markdown("##### 縮小架上商品")
        recent_days = None
        start_date = None
        end_date = None

        if source == "results":
            st.markdown(
                '<div class="filter-note">results 是預先計算快照；這裡調整品牌、分類、排序與樣本門檻。</div>',
                unsafe_allow_html=True,
            )
        else:
            time_mode_col, time_value_col = st.columns([1, 2])
            with time_mode_col:
                time_mode = st.radio("時間", ["近 N 天", "起訖日期"], horizontal=True)
            with time_value_col:
                if time_mode == "近 N 天":
                    recent_days = int(st.number_input("近 N 天", min_value=0, max_value=3650, value=30, step=1))
                else:
                    today = datetime.now().date()
                    default_start = today - timedelta(days=30)
                    date_cols = st.columns(2)
                    with date_cols[0]:
                        start_date = st.date_input("起始日期", value=default_start)
                    with date_cols[1]:
                        end_date = st.date_input("結束日期", value=today)

            options = brand_options(
                posts,
                start_date=start_date,
                end_date=end_date,
                recent_days=recent_days,
            )

        cat_options = ["全部分類", "冰品", "飲料", "甜點", "麵包", "便當", "鹹食", "零食", "泡麵", "乳品", "周邊", "其他"]
        filter_cols = st.columns([1.25, 1.05, 1.05, 0.8, 0.8])
        with filter_cols[0]:
            selected_brand = st.selectbox("品牌", options, index=0)
        with filter_cols[1]:
            selected_category = st.selectbox("分類", cat_options, index=0)
        with filter_cols[2]:
            sort_by = st.selectbox("排序", ["評分最高", "討論最多", "最新發文", "評分最低"], index=0)
        with filter_cols[3]:
            limit = int(st.number_input("顯示", min_value=1, max_value=200, value=12, step=1))
        with filter_cols[4]:
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
        "limit": limit,
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
            <div class="context-note">source={escape(source)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_shopper_view(result: ProductQueryResult, *, selection_key: str) -> None:
    rows = _shopper_rows(result)
    if not rows:
        st.info("目前條件下沒有符合的商品。可以放寬品牌、分類或更多條件。")
        return

    state_key = f"shopper_selected_idx::{selection_key}"
    table_key = f"shopper_table::{selection_key}"
    if state_key not in st.session_state or int(st.session_state[state_key]) >= len(rows):
        st.session_state[state_key] = 0
    selected_idx = _selected_idx_from_dataframe_state(
        st.session_state.get(table_key),
        fallback_idx=min(int(st.session_state[state_key]), len(rows) - 1),
        row_count=len(rows),
    )
    st.session_state[state_key] = selected_idx

    shelf_col, detail_col = st.columns([1.08, 0.92], gap="large")
    with shelf_col:
        st.markdown(
            """
            <div class="shelf-head">
                <p class="section-title">架上候選商品</p>
                <span class="section-note">點任一列的任一格，右側就會顯示完整心得。</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        event = st.dataframe(
            _shopper_table_rows(rows, selected_idx=selected_idx),
            hide_index=True,
            use_container_width=True,
            on_select="rerun",
            selection_mode="single-cell",
            key=table_key,
            row_height=54,
            height=min(54 * (len(rows) + 1) + 8, 650),
            column_order=["選取", "商標", "品牌", "商品", "分數", "共識", "聲量", "價格"],
            column_config={
                "選取": st.column_config.TextColumn("選取", width="small"),
                "商標": st.column_config.ImageColumn("商標", width="small"),
                "品牌": st.column_config.TextColumn("品牌", width="small"),
                "商品": st.column_config.TextColumn("商品"),
                "分數": st.column_config.NumberColumn("分數", format="%.0f", width="small"),
                "共識": st.column_config.TextColumn("共識", width="small"),
                "聲量": st.column_config.TextColumn("聲量", width="small"),
                "價格": st.column_config.TextColumn("價格", width="small"),
            },
        )
        selected_idx = _selected_idx_from_dataframe_state(event, fallback_idx=selected_idx, row_count=len(rows))
        st.session_state[state_key] = selected_idx

    selected_idx = int(st.session_state[state_key])
    with detail_col:
        st.markdown(
            """
            <div class="shelf-head">
                <p class="section-title">單品判斷</p>
                <span class="section-note">把商品拿在手上時，看這張就夠。</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown(_product_detail_html(rows[selected_idx]), unsafe_allow_html=True)


def _shopper_rows(result: ProductQueryResult) -> list[dict[str, Any]]:
    rows = product_rows(result)
    for row, report in zip(rows, result.reports):
        row["貼文數"] = report.n_posts
        row["留言數"] = report.n_comments
        row["有效樣本"] = report.n_eff
        row["信心"] = report.confidence
    return rows


def _shopper_table_rows(rows: list[dict[str, Any]], *, selected_idx: int) -> list[dict[str, Any]]:
    table_rows = []
    for idx, row in enumerate(rows):
        consensus = str(row.get("consensus") or "資料不足")
        volume = str(row.get("討論聲量") or "聲量不足")
        table_rows.append(
            {
                "選取": "目前" if idx == selected_idx else "",
                "商標": _brand_logo_data_uri(str(row.get("品牌") or "其他")),
                "品牌": str(row.get("品牌") or "-"),
                "商品": str(row.get("商品") or "-"),
                "分數": _score_value(row.get("fair_score")),
                "共識": _consensus_signal(consensus)[0],
                "聲量": _volume_signal(volume)[0],
                "價格": _format_price(row.get("價格")),
            }
        )
    return table_rows


def _brand_logo_data_uri(brand: str) -> str:
    spec = BRAND_LOGO_SPECS.get(brand, BRAND_LOGO_SPECS["其他"])
    bars = "".join(
        f'<rect x="{8 + i * 24}" y="6" width="18" height="4" rx="2" fill="{color}"/>'
        for i, color in enumerate(spec["bars"])
    )
    svg = f"""
    <svg xmlns="http://www.w3.org/2000/svg" width="88" height="36" viewBox="0 0 88 36" role="img" aria-label="{escape(brand)}">
      <rect x="1" y="1" width="86" height="34" rx="7" fill="{spec["bg"]}" stroke="{spec["border"]}" stroke-width="2"/>
      {bars}
      <text x="44" y="25" text-anchor="middle" font-family="Arial, 'Noto Sans TC', sans-serif" font-size="14" font-weight="800" fill="{spec["fg"]}">{escape(str(spec["text"]))}</text>
    </svg>
    """
    return "data:image/svg+xml;utf8," + quote(" ".join(svg.split()))


def _score_value(score: object) -> float | None:
    if score is None:
        return None
    try:
        return float(score)
    except (TypeError, ValueError):
        return None


def _selected_idx_from_dataframe_state(event: Any, *, fallback_idx: int, row_count: int) -> int:
    if not event:
        return fallback_idx
    selection = getattr(event, "selection", None)
    if not selection and isinstance(event, dict):
        selection = event.get("selection")
    if not selection:
        return fallback_idx

    cells = _selection_values(selection, "cells")
    if cells:
        first_cell = cells[0]
        try:
            selected_idx = int(first_cell[0])
        except (TypeError, ValueError, IndexError):
            return fallback_idx
        if 0 <= selected_idx < row_count:
            return selected_idx

    selected_rows = _selection_values(selection, "rows")
    if selected_rows:
        try:
            selected_idx = int(selected_rows[0])
        except (TypeError, ValueError):
            return fallback_idx
        if 0 <= selected_idx < row_count:
            return selected_idx

    return fallback_idx


def _selection_values(selection: Any, key: str) -> list:
    if isinstance(selection, dict):
        return list(selection.get(key) or [])
    return list(getattr(selection, key, []) or [])


def _product_detail_html(row: dict[str, Any]) -> str:
    score = row.get("fair_score")
    positive_comments = _split_comments(row.get("正向留言"))
    negative_comments = _split_comments(row.get("負向留言"))
    excerpt = str(row.get("心得節錄") or "").strip()
    return f"""
    <div class="detail-card">
        <div class="detail-eyebrow">#{escape(str(row.get("排名", "-")))} · {escape(str(row.get("品牌") or "-"))}</div>
        <div class="detail-name">{escape(str(row.get("商品") or "-"))}</div>
        <div class="detail-meta">
            <span class="pill price-pill">{escape(_format_price(row.get("價格")))}</span>
            <span class="pill price-pill">{escape(str(row.get("分類") or "其他"))}</span>
            <span class="pill date-pill">最新發文 {escape(str(row.get("最新發文") or "未知"))}</span>
        </div>
        <div class="decision-band">
            <div class="score-number {_score_class(score)}">{escape(_format_score(score))}<small>/100</small></div>
            <div>
                <div class="decision-text">{escape(_decision_text(score))}</div>
                <div class="decision-sub">{escape(_sample_count(row))}</div>
            </div>
        </div>
        {_signals_html(row)}
        {_excerpt_html(excerpt)}
        <div class="comment-grid">
            {_comment_box("大家喜歡的點", positive_comments, "positive")}
            {_comment_box("需要留意的點", negative_comments, "negative")}
        </div>
        {_competitor_html(row)}
    </div>
    """


def _signals_html(row: dict[str, Any]) -> str:
    consensus = str(row.get("consensus") or "資料不足")
    volume = str(row.get("討論聲量") or "聲量不足")
    consensus_label, consensus_class, consensus_segments = _consensus_signal(consensus)
    volume_label, volume_class, volume_level = _volume_signal(volume)
    return (
        '<div class="signal-row">'
        f'<span class="signal {consensus_class}" title="共識：{escape(consensus)}">'
        '<span class="signal-label">共識</span>'
        f'<span class="signal-value">{escape(consensus_label)}</span>'
        f'{_signal_bar_html(consensus_segments)}'
        "</span>"
        f'<span class="signal {volume_class}" title="討論聲量：{escape(volume)}">'
        '<span class="signal-label">聲量</span>'
        f'<span class="signal-value">{escape(volume_label)}</span>'
        f'{_heat_bar_html(volume_level)}'
        "</span>"
        "</div>"
    )


def _consensus_signal(consensus: str) -> tuple[str, str, tuple[str, ...]]:
    return CONSENSUS_SIGNALS.get(consensus, CONSENSUS_SIGNALS["資料不足"])


def _volume_signal(volume: str) -> tuple[str, str, int]:
    return VOLUME_SIGNALS.get(volume, VOLUME_SIGNALS["聲量不足"])


def _signal_bar_html(segments: tuple[str, ...]) -> str:
    bars = "".join(f'<span class="signal-seg {escape(segment)}"></span>' for segment in segments)
    return f'<span class="signal-bar" aria-hidden="true">{bars}</span>'


def _heat_bar_html(level: int) -> str:
    bars = "".join(
        f'<span class="heat-seg{" on" if idx < level else ""}"></span>'
        for idx in range(3)
    )
    return f'<span class="heat-bar" aria-hidden="true">{bars}</span>'


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
