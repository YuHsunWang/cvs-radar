"""UI UX Pro Max fork of the shopper-facing Streamlit UI for CVS Radar."""

from __future__ import annotations

from datetime import datetime, timedelta
from html import escape
from typing import Any
from urllib.parse import urlencode

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

UI_UX_PRO_MAX_RECOMMENDATION = """
Generated with UI UX Pro Max design_system.generate_design_system for:
"consumer-facing product-discovery review-rating browser for convenience-store
food snacks food product review rating browsing app"

Category: Review Platform
Pattern: Product Review/Ratings Focused
Style: Vibrant & Block-based
Style keywords: Bold, energetic, playful, block layout, geometric shapes, high
color contrast, duotone, modern, energetic
Palette:
- Primary: #F59E0B
- On Primary: #0F172A
- Secondary: #FBBF24
- Accent/CTA: #16A34A
- Background: #FFFBEB
- Foreground: #0F172A
- Muted: #FCF6F0
- Border: #FAEEE1
- Destructive: #DC2626
- Ring: #F59E0B
Typography: Rubik headings / Nunito Sans body
Key effects: Large sections (48px+ gaps), animated patterns, bold hover
(color shift), scroll-snap, large type (32px+), 200-300ms
Avoid: Flat design without depth + Text-heavy pages
"""

VOLUME_SIGNALS = {
    "聲量充足": ("高聲量", "volume-high", 3),
    "聲量中等": ("中聲量", "volume-mid", 2),
    "聲量不足": ("低聲量", "volume-low", 1),
}

SHELF_SELECTION_PARAM = "cvs_shelf"

BRAND_BADGE_SPECS = {
    "7-11": {
        "text": "7-11",
        "class": "brand-badge-711",
    },
    "全家": {
        "text": "FM",
        "class": "brand-badge-family",
    },
    "萊爾富": {
        "text": "HL",
        "class": "brand-badge-hilife",
    },
    "OK": {
        "text": "OK",
        "class": "brand-badge-ok",
    },
    "美聯社": {
        "text": "美聯",
        "class": "brand-badge-simplemart",
    },
    "其他": {
        "text": "其他",
        "class": "brand-badge-other",
    },
}


def main() -> None:
    st.set_page_config(page_title="CVS Radar Pro", page_icon="🛒", layout="wide")
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
        @import url('https://fonts.googleapis.com/css2?family=Nunito+Sans:wght@300;400;500;600;700;800&family=Rubik:wght@400;500;600;700;800&display=swap');

        :root {
            --pro-primary: #F59E0B;
            --pro-on-primary: #0F172A;
            --pro-secondary: #FBBF24;
            --pro-accent: #16A34A;
            --pro-background: #FFFBEB;
            --pro-foreground: #0F172A;
            --pro-muted: #FCF6F0;
            --pro-border: #FAEEE1;
            --pro-destructive: #DC2626;
            --pro-ring: #F59E0B;
            --pro-card: #ffffff;
            --pro-blue: #2563eb;
            --pro-shadow: rgba(15, 23, 42, 0.18);
            --pro-hard-shadow: 5px 5px 0 #0F172A;
            --pro-radius: 8px;
        }

        .stApp {
            background:
                linear-gradient(135deg, rgba(251, 191, 36, 0.16) 25%, transparent 25%) 0 0 / 52px 52px,
                linear-gradient(135deg, transparent 75%, rgba(22, 163, 74, 0.10) 75%) 0 0 / 52px 52px,
                linear-gradient(180deg, var(--pro-background) 0, #fff7d6 270px, #fffdf7 100%);
            color: var(--pro-foreground);
            font-family: "Nunito Sans", system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        }

        .block-container {
            max-width: 1360px;
            padding-top: 1.45rem;
            padding-bottom: 3.4rem;
        }

        section[data-testid="stSidebar"] {
            background: #fffefa;
            border-right: 2px solid var(--pro-foreground);
            box-shadow: 7px 0 0 rgba(15, 23, 42, 0.08);
        }

        section[data-testid="stSidebar"] h1,
        section[data-testid="stSidebar"] h2,
        section[data-testid="stSidebar"] h3,
        section[data-testid="stSidebar"] label,
        .stMarkdown h1,
        .stMarkdown h2,
        .stMarkdown h3,
        .stMarkdown h4,
        .stMarkdown h5 {
            font-family: "Rubik", "Nunito Sans", sans-serif;
            color: var(--pro-foreground);
            letter-spacing: 0;
        }

        div[data-testid="stVerticalBlockBorderWrapper"] {
            border: 2px solid var(--pro-foreground);
            border-radius: var(--pro-radius);
            background: rgba(255, 255, 255, 0.92);
            box-shadow: var(--pro-hard-shadow);
        }

        .shopper-header {
            display: flex;
            align-items: stretch;
            justify-content: space-between;
            gap: 1.2rem;
            padding: 1.18rem;
            margin: 0 0 1.55rem;
            border: 2px solid var(--pro-foreground);
            border-radius: var(--pro-radius);
            background:
                linear-gradient(90deg, rgba(245, 158, 11, 0.95), rgba(251, 191, 36, 0.78)),
                var(--pro-primary);
            box-shadow: var(--pro-hard-shadow);
        }

        .shopper-title {
            margin: 0;
            color: var(--pro-on-primary);
            font-family: "Rubik", "Nunito Sans", sans-serif;
            font-size: clamp(2rem, 3.4vw, 3.35rem);
            line-height: 1.02;
            font-weight: 800;
            letter-spacing: 0;
        }

        .shopper-caption {
            max-width: 760px;
            margin-top: 0.52rem;
            color: rgba(15, 23, 42, 0.84);
            font-size: 1.05rem;
            line-height: 1.5;
            font-weight: 700;
        }

        .header-chip {
            flex: 0 0 auto;
            align-self: flex-start;
            padding: 0.66rem 0.82rem;
            border-radius: var(--pro-radius);
            background: var(--pro-accent);
            border: 2px solid var(--pro-foreground);
            color: #ffffff;
            font-family: "Rubik", sans-serif;
            font-size: 0.9rem;
            font-weight: 800;
            white-space: nowrap;
            box-shadow: 3px 3px 0 var(--pro-foreground);
        }

        .filter-note,
        .context-note,
        .section-note {
            color: rgba(15, 23, 42, 0.68);
            font-size: 0.88rem;
            line-height: 1.5;
            font-weight: 700;
        }

        .context-bar {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 1rem;
            margin: 2.1rem 0 1.05rem;
            padding: 0.96rem 1.02rem;
            background: #ffffff;
            border: 2px solid var(--pro-foreground);
            border-radius: var(--pro-radius);
            box-shadow: 4px 4px 0 var(--pro-secondary);
        }

        .context-main {
            color: var(--pro-foreground);
            font-family: "Rubik", sans-serif;
            font-size: 1.12rem;
            font-weight: 800;
        }

        .shelf-head {
            display: flex;
            align-items: baseline;
            justify-content: space-between;
            gap: 1rem;
            margin: 0.7rem 0 0.7rem;
        }

        .section-title {
            margin: 0;
            color: var(--pro-foreground);
            font-family: "Rubik", sans-serif;
            font-size: 1.2rem;
            font-weight: 800;
        }

        .product-tile,
        .detail-card {
            background: var(--pro-card);
            border: 2px solid var(--pro-foreground);
            border-radius: var(--pro-radius);
            box-shadow: var(--pro-hard-shadow);
        }

        .shelf-card-list {
            display: grid;
            gap: 0.68rem;
            max-height: 650px;
            overflow-y: auto;
            padding: 0 0.42rem 0.42rem 0;
        }

        .product-tile {
            display: block;
            padding: 0.98rem;
            color: inherit;
            text-decoration: none !important;
            transition: transform 220ms ease, box-shadow 220ms ease, background-color 220ms ease;
        }

        .product-tile:hover,
        .product-tile:focus-visible {
            color: inherit;
            outline: none;
            transform: translate(-1px, -1px);
            box-shadow: 6px 6px 0 var(--pro-foreground);
        }

        .product-tile.selected {
            border-color: var(--pro-primary);
            background: #fffbeb;
            box-shadow: 5px 5px 0 var(--pro-primary);
        }

        .tile-grid {
            display: grid;
            grid-template-columns: minmax(0, 1fr) auto;
            gap: 0.9rem;
            align-items: start;
        }

        .tile-rank {
            color: rgba(15, 23, 42, 0.62);
            font-size: 0.78rem;
            font-weight: 800;
        }

        .tile-name {
            margin-top: 0.18rem;
            color: var(--pro-foreground);
            font-family: "Rubik", sans-serif;
            font-size: 1.04rem;
            line-height: 1.35;
            font-weight: 800;
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
            border-radius: var(--pro-radius);
            border: 2px solid transparent;
            font-size: 0.78rem;
            font-weight: 800;
            white-space: nowrap;
        }

        .brand-badge {
            min-width: 44px;
            justify-content: center;
            font-family: "Rubik", sans-serif;
        }

        .brand-badge-family { background: #e7f8ec; color: #14532d; border-color: #16A34A; }
        .brand-badge-711 { background: #fff7ed; color: #9a3412; border-color: #F97316; }
        .brand-badge-hilife { background: #fee2e2; color: #991b1b; border-color: #DC2626; }
        .brand-badge-ok { background: #fef3c7; color: #92400e; border-color: #FBBF24; }
        .brand-badge-simplemart { background: #f7f1ff; color: #6d2ea0; border-color: #7a3db8; }
        .brand-badge-other { background: #f4f6f8; color: #536170; border-color: #a7b2bf; }

        .price-pill { background: #ffffff; color: var(--pro-foreground); border-color: var(--pro-foreground); }
        .date-pill { background: var(--pro-muted); color: rgba(15, 23, 42, 0.76); border-color: var(--pro-border); }

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
            border-radius: var(--pro-radius);
            border: 2px solid var(--pro-foreground);
            color: var(--pro-foreground);
            font-family: "Rubik", sans-serif;
            font-size: 1.55rem;
            line-height: 1;
            font-weight: 800;
            box-shadow: 3px 3px 0 var(--pro-foreground);
        }

        .score-number small {
            margin-left: 0.08rem;
            font-size: 0.72rem;
            font-weight: 760;
        }

        .score-good { background: #16A34A; color: #ffffff; }
        .score-ok { background: #FBBF24; color: #0F172A; }
        .score-bad { background: #DC2626; color: #ffffff; }
        .score-empty { background: #cbd5e1; color: #0F172A; }

        .score-caption {
            margin-top: 0.32rem;
            color: rgba(15, 23, 42, 0.68);
            font-size: 0.74rem;
            font-weight: 800;
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
            border-radius: var(--pro-radius);
            border: 2px solid transparent;
            font-weight: 800;
        }

        .signal-label {
            color: rgba(15, 23, 42, 0.68);
            font-size: 0.72rem;
            font-weight: 800;
        }

        .signal-value {
            color: var(--pro-foreground);
            font-size: 0.9rem;
            line-height: 1;
            white-space: nowrap;
        }

        .signal-good { background: #dcfce7; border-color: #16A34A; color: #166534; }
        .signal-mixed { background: #fef3c7; border-color: #F59E0B; color: #92400e; }
        .signal-polar { background: #ffedd5; border-color: #fb923c; color: #9a3412; }
        .signal-bad { background: #fee2e2; border-color: #DC2626; color: #991b1b; }
        .signal-low { background: #f1f5f9; border-color: #94a3b8; color: #475569; }
        .volume-high { background: #ffedd5; border-color: #F59E0B; }
        .volume-mid { background: #fef3c7; border-color: #FBBF24; }
        .volume-low { background: #f1f5f9; border-color: #94a3b8; }

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

        .signal-seg.pos { background: #16A34A; }
        .signal-seg.neg { background: #DC2626; }
        .signal-seg.split { background: linear-gradient(90deg, #16A34A 0 50%, #DC2626 50% 100%); }
        .signal-seg.empty { background: #c7d0d9; }

        .heat-bar {
            grid-template-columns: repeat(3, 0.7rem);
        }

        .heat-seg.on { background: #F59E0B; }

        .sample-count {
            color: rgba(15, 23, 42, 0.68);
            font-size: 0.8rem;
            line-height: 1.45;
            margin-top: 0.54rem;
        }

        .detail-card {
            padding: 1.15rem;
            position: sticky;
            top: 1rem;
        }

        .detail-eyebrow {
            color: rgba(15, 23, 42, 0.64);
            font-size: 0.78rem;
            font-weight: 800;
        }

        .detail-name {
            margin: 0.18rem 0 0.7rem;
            color: var(--pro-foreground);
            font-family: "Rubik", sans-serif;
            font-size: 1.55rem;
            line-height: 1.28;
            font-weight: 800;
            overflow-wrap: anywhere;
        }

        .decision-band {
            display: grid;
            grid-template-columns: auto minmax(0, 1fr);
            gap: 0.9rem;
            align-items: center;
            padding: 0.82rem;
            border-radius: var(--pro-radius);
            background: #fff7d6;
            border: 2px solid var(--pro-foreground);
            margin: 0.9rem 0 1rem;
        }

        .decision-band .score-number {
            min-width: 104px;
            min-height: 62px;
            font-size: 2.1rem;
        }

        .decision-text {
            color: var(--pro-foreground);
            font-family: "Rubik", sans-serif;
            font-size: 1rem;
            font-weight: 800;
        }

        .decision-sub {
            color: rgba(15, 23, 42, 0.7);
            font-size: 0.84rem;
            line-height: 1.45;
            margin-top: 0.18rem;
        }

        .review-excerpt,
        .comment-box,
        .competitor-box {
            border-radius: var(--pro-radius);
            padding: 0.78rem 0.86rem;
        }

        .review-excerpt {
            background: #fffbeb;
            border: 2px solid var(--pro-foreground);
            border-left: 9px solid var(--pro-primary);
            margin: 0.82rem 0;
        }

        .box-title {
            color: rgba(15, 23, 42, 0.68);
            font-family: "Rubik", sans-serif;
            font-size: 0.78rem;
            font-weight: 800;
            margin-bottom: 0.35rem;
        }

        .box-body {
            color: var(--pro-foreground);
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

        .comment-positive { background: #dcfce7; border: 2px solid #16A34A; }
        .comment-negative { background: #fee2e2; border: 2px solid #DC2626; }
        .comment-positive .box-title { color: #166534; }
        .comment-negative .box-title { color: #991b1b; }

        .comment-list {
            margin: 0;
            padding-left: 1rem;
            color: var(--pro-foreground);
            font-size: 0.88rem;
            line-height: 1.5;
        }

        .comment-list li {
            margin-bottom: 0.32rem;
            overflow-wrap: anywhere;
        }

        .competitor-box {
            background: #ffffff;
            border: 2px solid var(--pro-foreground);
            margin-top: 0.75rem;
        }

        .compare-pills {
            display: flex;
            flex-wrap: wrap;
            gap: 0.45rem;
            margin-top: 0.4rem;
        }

        .compare-win { background: #dcfce7; color: #166534; border-color: #16A34A; }
        .compare-lose { background: #fee2e2; color: #991b1b; border-color: #DC2626; }

        button,
        [data-testid="stBaseButton-secondary"],
        [data-testid="stBaseButton-primary"] {
            border-radius: var(--pro-radius) !important;
            border: 2px solid var(--pro-foreground) !important;
            font-family: "Rubik", sans-serif !important;
            font-weight: 800 !important;
            transition: transform 200ms ease, background-color 200ms ease, box-shadow 200ms ease;
        }

        button:hover,
        [data-testid="stBaseButton-secondary"]:hover,
        [data-testid="stBaseButton-primary"]:hover {
            transform: translate(-1px, -1px);
            box-shadow: 3px 3px 0 var(--pro-foreground);
        }

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

            .detail-card {
                position: static;
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
            sort_by = st.selectbox("排序", ["評分最高", "討論最多", "最新發文", "評分最低"], index=2)
        with filter_cols[3]:
            limit = int(st.number_input("顯示", min_value=1, max_value=200, value=50, step=1))
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
    if state_key not in st.session_state or int(st.session_state[state_key]) >= len(rows):
        st.session_state[state_key] = 0
    selected_idx = _selected_idx_from_shelf_query(
        selection_key=selection_key,
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
                <span class="section-note">點任一卡片，右側就會顯示完整心得。</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown(
            _shopper_card_list_html(rows, selected_idx=selected_idx, selection_key=selection_key),
            unsafe_allow_html=True,
        )

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


def _shopper_card_list_html(rows: list[dict[str, Any]], *, selected_idx: int, selection_key: str) -> str:
    cards = "".join(
        _shopper_card_html(row, idx=idx, selected_idx=selected_idx, selection_key=selection_key)
        for idx, row in enumerate(rows)
    )
    return f'<div class="shelf-card-list">{cards}</div>'


def _shopper_card_html(row: dict[str, Any], *, idx: int, selected_idx: int, selection_key: str) -> str:
    score = row.get("fair_score")
    selected_class = " selected" if idx == selected_idx else ""
    aria_current = ' aria-current="true"' if idx == selected_idx else ""
    href = "?" + urlencode({SHELF_SELECTION_PARAM: f"{selection_key}|{idx}"})
    return f"""
    <a class="product-tile{selected_class}" href="{escape(href, quote=True)}"{aria_current}>
        <div class="tile-grid">
            <div>
                <div class="tile-meta">
                    {_brand_badge_html(str(row.get("品牌") or "其他"))}
                    <span class="pill price-pill">{escape(_format_price(row.get("價格")))}</span>
                </div>
                <div class="tile-name">{escape(str(row.get("商品") or "-"))}</div>
                {_signals_html(row)}
            </div>
            <div class="score-block">
                <div class="score-number {_score_class(score)}">{escape(_format_score(score))}<small>/100</small></div>
                <div class="score-caption">公正分數</div>
            </div>
        </div>
    </a>
    """


def _brand_badge_html(brand: str) -> str:
    spec = BRAND_BADGE_SPECS.get(brand, BRAND_BADGE_SPECS["其他"])
    return (
        f'<span class="pill brand-badge {escape(str(spec["class"]))}" title="{escape(brand)}">'
        f'{escape(str(spec["text"]))}'
        "</span>"
    )


def _selected_idx_from_shelf_query(*, selection_key: str, fallback_idx: int, row_count: int) -> int:
    token = _query_param_value(SHELF_SELECTION_PARAM)
    prefix = f"{selection_key}|"
    if not token or not token.startswith(prefix):
        return fallback_idx
    try:
        selected_idx = int(token[len(prefix):])
    except ValueError:
        return fallback_idx
    if 0 <= selected_idx < row_count:
        return selected_idx
    return fallback_idx


def _query_param_value(name: str) -> str | None:
    query_params = getattr(st, "query_params", None)
    if query_params is None:
        return None
    try:
        value = query_params.get(name)
    except AttributeError:
        return None
    if isinstance(value, list):
        return str(value[0]) if value else None
    if value is None:
        return None
    return str(value)


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
