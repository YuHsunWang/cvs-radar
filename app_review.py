"""Streamlit UI for CVS Radar — 檢查版 (results-only fork with post links for review)."""

from __future__ import annotations

from datetime import datetime, timedelta
from html import escape
from typing import Any

import streamlit as st

from cvs_radar.app_helpers import (
    ALL_BRANDS,
    brand_options,
    build_product_query,
    load_results_or_none,
    product_rows,
)
from cvs_radar.pipeline import run_pipeline
from cvs_radar.reporting import render_suspicion_detail
from cvs_radar.service import ProductQueryResult, brand_summaries_from_reports, filter_reports, query_products


def main() -> None:
    st.set_page_config(page_title="CVS Radar（檢查版）", page_icon=":mag:", layout="wide")
    _inject_css()
    _render_header()

    controls = {"source": "results", "crawl_pages": 5}

    posts = None
    loaded = load_results_or_none()
    if loaded is None:
        st.warning("尚無預算結果。請先執行 `python crawl_job.py` 爬取資料。")
        st.stop()
    reports, profiles = loaded
    brand_set = sorted(set(r.brand for r in reports))
    options = [ALL_BRANDS, *brand_set]

    tab1, tab2 = st.tabs(["商品排名", "帳號信度維運"])

    with tab1:
        filters = _render_ranking_filters(controls["source"], posts, options)

        query = build_product_query(
            brand=filters["selected_brand"],
            start_date=filters["start_date"],
            end_date=filters["end_date"],
            recent_days=filters["recent_days"],
            min_score=filters["min_score"],
            min_n_eff=filters["min_n_eff"],
            min_posts=filters["min_posts"],
            min_comments=filters["min_comments"],
            limit=filters["limit"],
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

        sorted_reports = _sort_reports(result.reports, filters["sort_by"])
        result = ProductQueryResult(
            filters=result.filters,
            brands=brand_summaries_from_reports(sorted_reports),
            reports=sorted_reports,
        )

        _render_summary(result.to_dict(), str(filters["selected_brand"]))
        selection_key = "|".join(
            str(filters[k])
            for k in ("selected_brand", "selected_category", "sort_by", "limit", "start_date", "end_date", "recent_days")
        )
        _render_rankings(result, selection_key=selection_key)

    with tab2:
        _render_account_maintenance(posts, controls, profiles=profiles)


def _sort_reports(reports: list, sort_by: str) -> list:
    if sort_by == "評分最低":
        return sorted(reports, key=lambda r: (r.fair_score is None, r.fair_score if r.fair_score is not None else 0.0))
    if sort_by == "最新發文":
        return sorted(reports, key=lambda r: r.latest_post_date or datetime.min, reverse=True)
    if sort_by == "討論最多":
        return sorted(reports, key=lambda r: r.n_posts + r.n_comments, reverse=True)
    return list(reports)


def _inject_css() -> None:
    st.markdown(
        """
        <style>
        :root {
            --cvs-ink: #16202a;
            --cvs-muted: #617080;
            --cvs-line: #dce4ec;
            --cvs-bg: #f6f8fb;
            --cvs-panel: #ffffff;
            --cvs-green: #12805c;
            --cvs-green-bg: #e8f6ef;
            --cvs-yellow: #9f6b00;
            --cvs-yellow-bg: #fff5d6;
            --cvs-red: #b42318;
            --cvs-red-bg: #fff0ed;
            --cvs-blue: #2563eb;
            --cvs-blue-bg: #edf4ff;
        }

        .stApp {
            background: linear-gradient(180deg, #f7fafc 0%, #eef3f8 260px, #f7fafc 100%);
        }

        .block-container {
            padding-top: 2rem;
            padding-bottom: 3rem;
            max-width: 1400px;
        }

        section[data-testid="stSidebar"] {
            background: #ffffff;
            border-right: 1px solid var(--cvs-line);
        }

        section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {
            color: var(--cvs-muted);
        }

        .dashboard-hero {
            display: flex;
            align-items: flex-end;
            justify-content: space-between;
            gap: 1.25rem;
            padding: 1.25rem 0 0.75rem;
            border-bottom: 1px solid rgba(97, 112, 128, 0.18);
            margin-bottom: 1rem;
        }

        .dashboard-title {
            margin: 0;
            color: var(--cvs-ink);
            font-size: 2.35rem;
            line-height: 1.1;
            letter-spacing: 0;
            font-weight: 760;
        }

        .dashboard-caption {
            color: var(--cvs-muted);
            margin-top: 0.5rem;
            font-size: 1rem;
        }

        .source-chip {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            min-height: 36px;
            padding: 0.42rem 0.8rem;
            border-radius: 999px;
            background: var(--cvs-blue-bg);
            color: #174ea6;
            font-weight: 700;
            border: 1px solid #cfe1ff;
            white-space: nowrap;
        }

        .kpi-card {
            min-height: 126px;
            padding: 1rem 1.05rem;
            background: rgba(255, 255, 255, 0.94);
            border: 1px solid var(--cvs-line);
            border-radius: 8px;
            box-shadow: 0 8px 24px rgba(22, 32, 42, 0.06);
        }

        .kpi-label {
            color: var(--cvs-muted);
            font-size: 0.86rem;
            font-weight: 700;
            margin-bottom: 0.55rem;
        }

        .kpi-value {
            color: var(--cvs-ink);
            font-size: 1.78rem;
            line-height: 1.1;
            font-weight: 780;
            overflow-wrap: anywhere;
        }

        .kpi-help {
            color: var(--cvs-muted);
            font-size: 0.78rem;
            margin-top: 0.45rem;
        }

        .section-head {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 1rem;
            margin: 1.25rem 0 0.65rem;
        }

        .section-title {
            color: var(--cvs-ink);
            font-size: 1.08rem;
            font-weight: 760;
            margin: 0;
        }

        .section-note {
            color: var(--cvs-muted);
            font-size: 0.86rem;
        }

        .product-card {
            background: var(--cvs-panel);
            border: 1px solid var(--cvs-line);
            border-radius: 8px;
            padding: 1.05rem;
            margin-bottom: 0.9rem;
            box-shadow: 0 8px 22px rgba(22, 32, 42, 0.055);
        }

        .product-topline {
            display: grid;
            grid-template-columns: minmax(0, 1fr) auto;
            gap: 1rem;
            align-items: start;
        }

        .product-rank {
            color: var(--cvs-muted);
            font-size: 0.86rem;
            font-weight: 700;
        }

        .product-name {
            color: var(--cvs-ink);
            font-size: 1.18rem;
            line-height: 1.35;
            font-weight: 760;
            margin-top: 0.2rem;
            overflow-wrap: anywhere;
        }

        .badge-row {
            display: flex;
            flex-wrap: wrap;
            gap: 0.45rem;
            margin-top: 0.62rem;
        }

        .pill {
            display: inline-flex;
            align-items: center;
            min-height: 28px;
            padding: 0.22rem 0.58rem;
            border-radius: 999px;
            font-size: 0.78rem;
            font-weight: 730;
            border: 1px solid transparent;
            white-space: nowrap;
        }

        .brand-badge-0 { background: #e9f7f4; color: #0f766e; border-color: #b7ebe2; }
        .brand-badge-1 { background: #edf4ff; color: #1d4ed8; border-color: #cfe1ff; }
        .brand-badge-2 { background: #f3efff; color: #6d28d9; border-color: #ded3ff; }
        .brand-badge-3 { background: #fff4e5; color: #9a5b00; border-color: #ffdca8; }
        .brand-badge-4 { background: #f0f7e8; color: #3f7617; border-color: #d2edb8; }
        .brand-badge-5 { background: #f8eef3; color: #9d174d; border-color: #f3cade; }

        .consensus-good { background: var(--cvs-green-bg); color: var(--cvs-green); border-color: #bee8d3; }
        .consensus-mid { background: var(--cvs-yellow-bg); color: var(--cvs-yellow); border-color: #ffe39a; }
        .consensus-bad { background: var(--cvs-red-bg); color: var(--cvs-red); border-color: #ffd1cb; }
        .consensus-low { background: #eef2f6; color: #506070; border-color: #dce4ec; }

        .score-panel {
            min-width: 132px;
            text-align: right;
        }

        .score-badge {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            min-width: 80px;
            min-height: 40px;
            border-radius: 999px;
            color: #ffffff;
            font-size: 1.08rem;
            font-weight: 800;
            box-shadow: inset 0 -1px 0 rgba(0, 0, 0, 0.12);
        }

        .score-green { background: #16a46f; }
        .score-yellow { background: #d39b12; }
        .score-red { background: #dc3f31; }
        .score-empty { background: #7b8794; }

        .pill.score-green,
        .pill.score-yellow,
        .pill.score-red,
        .pill.score-empty {
            color: #ffffff;
            border-color: transparent;
        }

        .score-track {
            height: 8px;
            width: 132px;
            border-radius: 999px;
            background: #e8edf3;
            margin-top: 0.5rem;
            overflow: hidden;
            margin-left: auto;
        }

        .score-fill {
            height: 8px;
            border-radius: 999px;
        }

        .product-stats {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 0.65rem;
            margin-top: 1rem;
        }

        .mini-stat {
            background: #f7fafc;
            border: 1px solid #e4ebf2;
            border-radius: 8px;
            padding: 0.62rem 0.68rem;
        }

        .mini-stat-label {
            color: var(--cvs-muted);
            font-size: 0.74rem;
            font-weight: 700;
            margin-bottom: 0.2rem;
        }

        .mini-stat-value {
            color: var(--cvs-ink);
            font-size: 0.98rem;
            font-weight: 760;
            overflow-wrap: anywhere;
        }

        .comment-grid {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 0.75rem;
            margin-top: 0.9rem;
        }

        .comment-box {
            border-radius: 8px;
            padding: 0.75rem 0.82rem;
            min-height: 104px;
        }

        .comment-positive {
            background: var(--cvs-green-bg);
            border: 1px solid #bee8d3;
        }

        .comment-negative {
            background: var(--cvs-red-bg);
            border: 1px solid #ffd1cb;
        }

        .comment-title {
            font-size: 0.82rem;
            font-weight: 780;
            margin-bottom: 0.48rem;
        }

        .comment-positive .comment-title { color: var(--cvs-green); }
        .comment-negative .comment-title { color: var(--cvs-red); }

        .comment-list {
            margin: 0;
            padding-left: 1rem;
            color: var(--cvs-ink);
            font-size: 0.88rem;
            line-height: 1.48;
        }

        .comment-list li {
            margin-bottom: 0.28rem;
            overflow-wrap: anywhere;
        }

        .query-panel {
            background: #ffffff;
            border: 1px solid var(--cvs-line);
            border-radius: 8px;
            padding: 0.8rem 0.95rem;
            margin: 0.8rem 0 1.1rem;
        }

        .account-strip {
            background: #ffffff;
            border: 1px solid var(--cvs-line);
            border-radius: 8px;
            padding: 1rem;
            box-shadow: 0 8px 22px rgba(22, 32, 42, 0.05);
        }

        @media (max-width: 900px) {
            .dashboard-hero,
            .product-topline {
                display: block;
            }

            .score-panel {
                text-align: left;
                margin-top: 0.8rem;
            }

            .score-track {
                margin-left: 0;
            }

            .product-stats,
            .comment-grid {
                grid-template-columns: 1fr;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_header() -> None:
    st.markdown(
        """
        <div class="dashboard-hero">
            <div>
                <h1 class="dashboard-title">CVS Radar 商品評分排名</h1>
                <div class="dashboard-caption">依時間挑選評論、依品牌挑選商品，並用服務層評分結果排序。</div>
            </div>
            <div class="source-chip">商品輿情儀表板</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_ranking_filters(source: object, posts: object, options: list[str]) -> dict[str, object]:
    source_name = str(source)
    with st.container(border=True):
        st.markdown("##### 商品篩選")
        recent_days = None
        start_date = None
        end_date = None

        if source_name == "results":
            st.info("results 模式顯示已預先計算的快照，不支援時間篩選；以下排名會套用品牌、分類與進階條件。")
        else:
            time_mode_col, time_value_col = st.columns([1, 2])
            with time_mode_col:
                time_mode = st.radio("時間選擇", ["近 N 天", "起訖日期"], horizontal=True)
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
        filter_cols = st.columns([1.2, 1.1, 0.9, 1.1, 0.8])
        with filter_cols[0]:
            selected_brand = st.selectbox("品牌", options, index=0)
        with filter_cols[1]:
            selected_category = st.selectbox("分類", cat_options, index=0)
        with filter_cols[2]:
            limit = int(st.number_input("筆數上限", min_value=1, max_value=500, value=20, step=1))
        with filter_cols[3]:
            sort_by = st.selectbox("排序方式", ["評分最高", "評分最低", "最新發文", "討論最多"], index=0)
        with filter_cols[4]:
            with st.popover("進階篩選", use_container_width=True):
                use_min_score = st.checkbox("啟用最低分", value=False)
                min_score = None
                if use_min_score:
                    min_score = float(st.number_input("最低分數", min_value=0.0, max_value=100.0, value=60.0, step=1.0))

                use_min_n_eff = st.checkbox("啟用最低有效樣本", value=False)
                min_n_eff = None
                if use_min_n_eff:
                    min_n_eff = float(st.number_input("最低有效樣本值", min_value=0.0, value=1.0, step=0.5))

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




def _render_summary(payload: dict[str, object], selected_brand: str) -> None:
    filters = payload["filters"]
    brands = payload["brands"]
    reports = payload["reports"]
    scored = [report for report in reports if report.get("fair_score") is not None]
    avg_score = sum(float(report["fair_score"]) for report in scored) / len(scored) if scored else None
    top_report = max(scored, key=lambda item: float(item["fair_score"]), default=None)
    total_comments = sum(int(report.get("n_comments") or 0) for report in reports)
    total_posts = sum(int(report.get("n_posts") or 0) for report in reports)
    top_brand = _top_brand_name(brands)
    time_label = "近 N 天" if filters["recent_days"] is not None else "起訖日期/不限"

    cols = st.columns(5)
    kpis = [
        ("查詢品牌", selected_brand if selected_brand != ALL_BRANDS else "全部品牌", "目前商品篩選範圍"),
        ("符合商品", f"{len(reports):,}", f"{len(brands):,} 個品牌命中"),
        ("平均分數", _format_decimal(avg_score), "篩選後商品平均"),
        ("熱門品牌", top_brand, "依商品數與貼文數排序"),
        ("討論量", f"{total_posts:,} / {total_comments:,}", "貼文 / 留言"),
    ]
    for col, (label, value, help_text) in zip(cols, kpis):
        with col:
            _render_kpi(label, value, help_text)

    with st.container():
        if top_report is not None:
            st.markdown(
                f"""
                <div class="query-panel">
                    <div class="section-head" style="margin:0;">
                        <p class="section-title">目前領先商品：{escape(str(top_report.get("product_name", "-")))}</p>
                        <span class="pill {_score_class(top_report.get("fair_score"))}">最高分 {_format_score(top_report.get("fair_score"))}</span>
                    </div>
                    <div class="section-note">時間模式：{escape(time_label)}；查詢條件可在下方展開檢視。</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f"""
                <div class="query-panel">
                    <p class="section-title" style="margin:0 0 0.25rem;">目前查詢沒有可計分商品</p>
                    <div class="section-note">時間模式：{escape(time_label)}；可放寬品牌、時間或進階篩選。</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    with st.expander("目前查詢條件", expanded=False):
        st.json(_localized_filters(filters))


def _render_rankings(result, *, selection_key: str = "") -> None:
    rows = product_rows(result)
    if not rows:
        st.info("目前條件下沒有符合的商品。請放寬時間、品牌或進階篩選。")
        return

    st.markdown(
        """
        <div class="section-head">
            <p class="section-title">評分排名</p>
            <span class="section-note">下方清單點整排任一處即可切換右側洞察卡。</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    state_key = f"review_selected_idx::{selection_key}"
    table_key = f"ranking_table::{selection_key}"
    if state_key not in st.session_state:
        st.session_state[state_key] = 0
    selected_idx = min(int(st.session_state[state_key]), len(rows) - 1)
    selected_idx = _selected_idx_from_dataframe_state(
        st.session_state.get(table_key),
        fallback_idx=selected_idx,
        row_count=len(rows),
    )
    st.session_state[state_key] = selected_idx

    left, right = st.columns([2.3, 1])
    with left:
        event = st.dataframe(
            rows,
            hide_index=True,
            use_container_width=True,
            on_select="rerun",
            selection_mode="single-cell",
            selection_default={"selection": {"cells": [[selected_idx, "商品"]]}},
            key=table_key,
            column_order=[
                "排名",
                "品牌",
                "商品",
                "價格",
                "分類",
                "fair_score",
                "consensus",
                "討論聲量",
            ],
            column_config={
                "排名": st.column_config.NumberColumn("排名", width="small"),
                "品牌": st.column_config.TextColumn("品牌", width="small"),
                "商品": st.column_config.TextColumn("商品"),
                "價格": st.column_config.NumberColumn("價格", format="%d", width="small"),
                "分類": st.column_config.TextColumn("分類", width="small"),
                "fair_score": st.column_config.NumberColumn("公平分數", format="%.1f", width="small"),
                "consensus": st.column_config.TextColumn("共識", width="small"),
                "討論聲量": st.column_config.TextColumn("討論聲量", width="small"),
            },
        )
        selected_idx = _selected_idx_from_dataframe_state(event, fallback_idx=selected_idx, row_count=len(rows))
        st.session_state[state_key] = selected_idx

        import pandas as pd

        df = pd.DataFrame(rows)
        csv = df.to_csv(index=False).encode("utf-8-sig")
        st.download_button("下載 CSV", csv, "cvs_radar_rankings.csv", "text/csv")

    row = rows[selected_idx]
    with right:
        st.markdown("#### 商品洞察卡")
        st.caption(f"目前檢視：#{row['排名']} {row['商品']}")
        st.html(f"<style>{_CARD_CSS}</style>\n{_product_card_html(row)}")


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

    rows = _selection_values(selection, "rows")
    if rows:
        try:
            selected_idx = int(rows[0])
        except (TypeError, ValueError):
            return fallback_idx
        if 0 <= selected_idx < row_count:
            return selected_idx

    return fallback_idx


def _selection_values(selection: Any, key: str) -> list:
    if isinstance(selection, dict):
        return list(selection.get(key) or [])
    return list(getattr(selection, key, []) or [])


_CARD_CSS = """
body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
.product-card { background:#fff; border:1px solid #dce4ec; border-radius:8px; padding:1.05rem; margin-bottom:0.9rem; box-shadow:0 8px 22px rgba(22,32,42,0.055); }
.product-topline { display:flex; flex-wrap:wrap; gap:1rem; align-items:flex-start; justify-content:space-between; }
.product-topline > div:first-child { flex:1 1 220px; min-width:0; }
.product-rank { color:#617080; font-size:0.86rem; font-weight:700; }
.product-name { color:#16202a; font-size:1.18rem; line-height:1.35; font-weight:760; margin-top:0.2rem; overflow-wrap:anywhere; }
.badge-row { display:flex; flex-wrap:wrap; gap:0.45rem; margin-top:0.62rem; }
.pill { display:inline-flex; align-items:center; min-height:28px; padding:0.22rem 0.58rem; border-radius:999px; font-size:0.78rem; font-weight:730; border:1px solid transparent; white-space:nowrap; }
.brand-badge-0{background:#e9f7f4;color:#0f766e;border-color:#b7ebe2;} .brand-badge-1{background:#edf4ff;color:#1d4ed8;border-color:#cfe1ff;} .brand-badge-2{background:#f3efff;color:#6d28d9;border-color:#ded3ff;} .brand-badge-3{background:#fff4e5;color:#9a5b00;border-color:#ffdca8;} .brand-badge-4{background:#f0f7e8;color:#3f7617;border-color:#d2edb8;} .brand-badge-5{background:#f8eef3;color:#9d174d;border-color:#f3cade;}
.consensus-good{background:#e8f6ef;color:#12805c;border-color:#bee8d3;} .consensus-mid{background:#fff5d6;color:#9f6b00;border-color:#ffe39a;} .consensus-bad{background:#fff0ed;color:#b42318;border-color:#ffd1cb;} .consensus-low{background:#eef2f6;color:#506070;border-color:#dce4ec;} .consensus-neg{background:#fff0ed;color:#b42318;border-color:#ffd1cb;}
.score-panel { flex:0 0 auto; min-width:132px; text-align:right; }
.score-badge { display:inline-flex; align-items:center; justify-content:center; min-width:80px; min-height:40px; border-radius:999px; color:#fff; font-size:1.08rem; font-weight:800; box-shadow:inset 0 -1px 0 rgba(0,0,0,0.12); }
.score-green{background:#16a46f;} .score-yellow{background:#d39b12;} .score-red{background:#dc3f31;} .score-empty{background:#7b8794;}
.pill.score-green,.pill.score-yellow,.pill.score-red,.pill.score-empty{color:#fff;border-color:transparent;}
.score-track { height:8px; width:132px; border-radius:999px; background:#e8edf3; margin-top:0.5rem; overflow:hidden; margin-left:auto; }
.score-fill { height:8px; border-radius:999px; }
.product-stats { display:grid; grid-template-columns:repeat(auto-fit, minmax(130px, 1fr)); gap:0.65rem; margin-top:1rem; }
.mini-stat { background:#f7fafc; border:1px solid #e4ebf2; border-radius:8px; padding:0.62rem 0.68rem; }
.mini-stat-label { color:#617080; font-size:0.74rem; font-weight:700; margin-bottom:0.2rem; }
.mini-stat-value { color:#16202a; font-size:0.98rem; font-weight:760; overflow-wrap:anywhere; }
.comment-grid { display:grid; grid-template-columns:repeat(auto-fit, minmax(200px, 1fr)); gap:0.75rem; margin-top:0.9rem; }
.comment-box { border-radius:8px; padding:0.75rem 0.82rem; min-height:104px; }
.comment-positive { background:#e8f6ef; border:1px solid #bee8d3; } .comment-negative { background:#fff0ed; border:1px solid #ffd1cb; }
.comment-title { font-size:0.82rem; font-weight:780; margin-bottom:0.48rem; }
.comment-positive .comment-title{color:#12805c;} .comment-negative .comment-title{color:#b42318;}
.comment-list { margin:0; padding-left:1rem; color:#16202a; font-size:0.88rem; line-height:1.48; }
.comment-list li { margin-bottom:0.28rem; overflow-wrap:anywhere; }
.review-excerpt { margin-top:0.9rem; background:#f7fafc; border:1px solid #e4ebf2; border-left:3px solid #2563eb; border-radius:6px; padding:0.6rem 0.75rem; }
.review-excerpt-title { color:#617080; font-size:0.74rem; font-weight:700; margin-bottom:0.3rem; }
.review-excerpt-body { color:#16202a; font-size:0.86rem; line-height:1.5; overflow-wrap:anywhere; }
.competitor-verdict { display:flex; flex-wrap:wrap; align-items:center; gap:0.4rem; margin-top:0.75rem; }
.cv-label { color:#617080; font-size:0.78rem; font-weight:700; }
.cv-pill { display:inline-flex; align-items:center; padding:0.18rem 0.5rem; border-radius:999px; font-size:0.78rem; font-weight:730; border:1px solid transparent; }
.cv-win { background:#e8f6ef; color:#12805c; border-color:#bee8d3; }
.cv-lose { background:#fff0ed; color:#b42318; border-color:#ffd1cb; }
.post-links { display:flex; flex-direction:column; gap:0.3rem; margin-top:0.85rem; padding-top:0.7rem; border-top:1px dashed #dce4ec; }
.post-link { color:#2563eb; font-size:0.8rem; text-decoration:none; overflow-wrap:anywhere; }
.post-link:hover { text-decoration:underline; }
@media(max-width:900px){ .product-topline{display:block;} .score-panel{text-align:left;margin-top:0.8rem;} .score-track{margin-left:0;} .product-stats,.comment-grid{grid-template-columns:1fr;} }
"""


def _product_card_html(row: dict[str, Any]) -> str:
    score = row.get("fair_score")
    score_width = _score_width(score)
    score_cls = _score_class(score)
    brand = str(row.get("品牌") or "-")
    consensus = str(row.get("consensus") or "-")
    volume = str(row.get("討論聲量") or "-")
    positive_comments = _split_comments(row.get("正向留言"))
    negative_comments = _split_comments(row.get("負向留言"))
    competitor_brands = str(row.get("提及競品") or "無")
    excerpt = str(row.get("心得節錄") or "").strip()
    post_urls = [u for u in (row.get("貼文連結") or []) if u]

    return f"""
    <div class="product-card">
        <div class="product-topline">
            <div>
                <div class="product-rank">#{escape(str(row.get("排名", "-")))} 商品排名</div>
                <div class="product-name">{escape(str(row.get("商品") or "-"))}</div>
                <div class="badge-row">
                    <span class="pill {_brand_class(brand)}">{escape(brand)}</span>
                    <span class="pill {_consensus_class(consensus)}">共識：{escape(consensus)}</span>
                </div>
            </div>
            <div class="score-panel">
                <div class="score-badge {score_cls}">{escape(_format_score(score))}</div>
                <div class="score-track"><div class="score-fill {score_cls}" style="width:{score_width}%;"></div></div>
            </div>
        </div>
        {_excerpt_html(excerpt)}
        <div class="product-stats">
            {_mini_stat("討論聲量", escape(volume))}
            {_mini_stat("競品提及", f'{int(row.get("競品提及") or 0):,} 則')}
            {_mini_stat("提及競品", competitor_brands)}
        </div>
        {_competitor_verdict_html(row)}
        <div class="comment-title" style="margin-top:0.9rem;font-size:0.92rem;font-weight:780;color:#16202a;">代表性留言</div>
        <div class="comment-grid" style="margin-top:0.4rem;">
            {_comment_box("正向", positive_comments, "positive")}
            {_comment_box("負向", negative_comments, "negative")}
        </div>
        {_post_links_html(post_urls)}
    </div>"""


def _post_links_html(urls: list[str]) -> str:
    if not urls:
        return ""
    links = "".join(
        f'<a class="post-link" href="{escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">'
        f"原始貼文 {i}｜{escape(url)}</a>"
        for i, url in enumerate(urls, 1)
    ) if len(urls) > 1 else (
        f'<a class="post-link" href="{escape(urls[0], quote=True)}" target="_blank" rel="noopener noreferrer">'
        f"原始貼文｜{escape(urls[0])}</a>"
    )
    return f'<div class="post-links">{links}</div>'


def _excerpt_html(excerpt: str) -> str:
    if not excerpt:
        return ""
    return (
        '<div class="review-excerpt">'
        '<div class="review-excerpt-title">原PO心得節錄</div>'
        f'<div class="review-excerpt-body">{escape(excerpt)}</div>'
        "</div>"
    )


def _competitor_verdict_html(row: dict[str, Any]) -> str:
    other = int(row.get("偏好他牌") or 0)
    own = int(row.get("偏好本品") or 0)
    if other == 0 and own == 0:
        return ""
    return (
        '<div class="competitor-verdict">'
        '<span class="cv-label">競品比較</span>'
        f'<span class="cv-pill cv-win">本品較優 {own}</span>'
        f'<span class="cv-pill cv-lose">他牌較優 {other}</span>'
        "</div>"
    )


def _render_account_maintenance(posts, controls: dict[str, object], *, profiles=None) -> None:
    if profiles is None:
        try:
            _, profiles = run_pipeline(
                posts,
                start_date=controls.get("start_date"),
                end_date=controls.get("end_date"),
                recent_days=controls.get("recent_days"),
            )
        except ValueError as exc:
            st.error(str(exc))
            return

    active_profiles = [
        profile
        for profile in sorted(profiles.values(), key=lambda item: -item.suspicion_score)
        if profile.suspicion_features
    ]

    st.markdown(
        """
        <div class="section-head">
            <p class="section-title">帳號概覽</p>
            <span class="section-note">預設只顯示可疑分達門檻的帳號，可調整篩選範圍。</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    min_suspicion = st.slider("最低可疑分", 0.0, 1.0, 0.4, 0.01)
    filtered_profiles = [
        profile for profile in active_profiles if profile.suspicion_score >= min_suspicion
    ]

    overview_rows = [
        {
            "帳號": profile.user,
            "留言數": profile.total_comments,
            "傾向品牌": profile.lean_brand or "-",
            "可疑分": profile.suspicion_score,
        }
        for profile in filtered_profiles
    ]

    cols = st.columns(3)
    with cols[0]:
        _render_kpi("可疑帳號", f"{len(filtered_profiles):,}", "符合目前門檻")
    with cols[1]:
        avg_suspicion = (
            sum(profile.suspicion_score for profile in filtered_profiles) / len(filtered_profiles)
            if filtered_profiles
            else None
        )
        _render_kpi("平均可疑分", _format_decimal(avg_suspicion, digits=2), "篩選後帳號")
    with cols[2]:
        top_user = filtered_profiles[0].user if filtered_profiles else "-"
        _render_kpi("最高風險帳號", top_user, "依可疑分排序")

    event = st.dataframe(
        overview_rows,
        hide_index=True,
        use_container_width=True,
        on_select="rerun",
        selection_mode="single-row",
        key=f"account_table::{min_suspicion}",
        column_config={
            "帳號": st.column_config.TextColumn("帳號", width="medium"),
            "留言數": st.column_config.NumberColumn("留言數"),
            "傾向品牌": st.column_config.TextColumn("傾向品牌"),
            "可疑分": st.column_config.NumberColumn("可疑分", format="%.2f"),
        },
    )

    if not filtered_profiles:
        st.info("目前條件下沒有達活動量門檻且符合最低可疑分的帳號。")
        return

    selected_rows = list(event.selection.rows) if event and event.selection else []
    if not selected_rows:
        st.info("點選上方帳號表任一列，查看品牌互動、特徵分數與被標記留言。")
        return

    st.markdown(
        """
        <div class="section-head">
            <p class="section-title">帳號明細</p>
            <span class="section-note">點選表格列切換檢視帳號。</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    selected_profile = filtered_profiles[selected_rows[0]]
    st.caption(f"目前檢視：{selected_profile.user}")

    overview_tab, features_tab, comments_tab = st.tabs(["總覽", "特徵", "留言"])

    with overview_tab:
        col1, col2, col3 = st.columns(3)
        col1.metric("留言數", selected_profile.total_comments)
        col2.metric("可疑分", f"{selected_profile.suspicion_score:.2f}")
        col3.metric("傾向品牌", selected_profile.lean_brand or "-")

        st.markdown("#### 品牌互動")
        brand_rows = [
            {
                "品牌": brand,
                "留言數": stat.count,
                "平均情感": stat.avg_sentiment,
            }
            for brand, stat in sorted(
                selected_profile.brand_stats.items(),
                key=lambda item: (-item[1].count, item[0]),
            )
        ]
        st.dataframe(
            brand_rows,
            hide_index=True,
            use_container_width=True,
            column_config={
                "品牌": st.column_config.TextColumn("品牌"),
                "留言數": st.column_config.NumberColumn("留言數"),
                "平均情感": st.column_config.NumberColumn("平均情感", format="%.2f"),
            },
        )

    with features_tab:
        explanations = {
            "one_sided": ("單一品牌偏向", "偏向單一品牌正面、競品負面的程度"),
            "single_brand": ("單一品牌集中", "留言集中在單一品牌的程度"),
            "extreme": ("極端情感", "極端情感留言比例"),
            "template_like": ("樣板留言", "完全重複或近似樣板留言比例"),
            "burst": ("爆發留言", "同品牌短時間爆發留言比例"),
        }
        feature_rows = [
            {
                "特徵": label,
                "值": selected_profile.suspicion_features.get(name, 0.0),
                "說明": explanation,
            }
            for name, (label, explanation) in explanations.items()
        ]
        st.dataframe(
            feature_rows,
            hide_index=True,
            use_container_width=True,
            column_config={
                "特徵": st.column_config.TextColumn("特徵"),
                "值": st.column_config.NumberColumn("值", format="%.2f"),
                "說明": st.column_config.TextColumn("說明", width="large"),
            },
        )

    with comments_tab:
        display_posts = posts
        if display_posts is None:
            from cvs_radar.store import load_posts as load_stored_posts
            try:
                display_posts = load_stored_posts()
            except Exception:
                display_posts = None
        if display_posts is None:
            st.info("尚無原始留言資料；請先執行爬取或切換到 stored 模式。")
        else:
            st.code(render_suspicion_detail(selected_profile, display_posts), language="text")


def _render_kpi(label: str, value: str, help_text: str) -> None:
    st.markdown(
        f"""
        <div class="kpi-card">
            <div class="kpi-label">{escape(label)}</div>
            <div class="kpi-value">{escape(value)}</div>
            <div class="kpi-help">{escape(help_text)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _mini_stat(label: str, value: object) -> str:
    return (
        '<div class="mini-stat">'
        f'<div class="mini-stat-label">{escape(str(label))}</div>'
        f'<div class="mini-stat-value">{escape(str(value))}</div>'
        "</div>"
    )


def _comment_box(title: str, comments: list[str], tone: str) -> str:
    css_class = "comment-positive" if tone == "positive" else "comment-negative"
    fallback = "尚無正向留言" if tone == "positive" else "尚無負向留言"
    items = comments or [fallback]
    body = "".join(f"<li>{escape(comment)}</li>" for comment in items)
    return (
        f'<div class="comment-box {css_class}">'
        f'<div class="comment-title">{escape(title)}</div>'
        f'<ul class="comment-list">{body}</ul>'
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


def _format_score(score: object) -> str:
    if score is None:
        return "無分數"
    try:
        return f"{float(score):.1f}"
    except (TypeError, ValueError):
        return "無分數"


def _format_decimal(value: object, *, digits: int = 1) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "-"


def _score_width(score: object) -> int:
    try:
        return max(0, min(100, int(round(float(score)))))
    except (TypeError, ValueError):
        return 0


def _score_class(score: object) -> str:
    try:
        value = float(score)
    except (TypeError, ValueError):
        return "score-empty"
    if value >= 70:
        return "score-green"
    if value >= 50:
        return "score-yellow"
    return "score-red"


def _consensus_class(consensus: str) -> str:
    text = consensus.strip()
    if not text or "資料不足" in text or "不足" in text:
        return "consensus-low"
    if any(token in text for token in ("負", "噓", "不推", "差")):
        return "consensus-bad"
    if any(token in text for token in ("正", "推", "推薦", "好")):
        return "consensus-good"
    return "consensus-mid"


def _brand_class(brand: str) -> str:
    index = sum(ord(char) for char in brand) % 6
    return f"brand-badge-{index}"


def _top_brand_name(brands: object) -> str:
    if not brands:
        return "-"
    first = brands[0]
    if isinstance(first, dict):
        return str(first.get("brand") or "-")
    return str(getattr(first, "brand", "-") or "-")


def _localized_filters(filters: dict[str, object]) -> dict[str, object]:
    labels = {
        "brand": "品牌",
        "start_date": "起始日期",
        "end_date": "結束日期",
        "recent_days": "近 N 天",
        "min_score": "最低分數",
        "min_n_eff": "最低有效樣本",
        "min_posts": "最少貼文",
        "min_comments": "最少留言",
        "limit": "筆數上限",
        "internal": "內部欄位",
    }
    return {labels.get(key, key): value for key, value in filters.items()}


if __name__ == "__main__":
    main()
