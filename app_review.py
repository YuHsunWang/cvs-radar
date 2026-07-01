"""Streamlit UI for CVS Radar — 檢查版 (results-only fork with post links for review)."""

from __future__ import annotations

from datetime import datetime
from html import escape
from typing import Any

import streamlit as st

from cvs_radar.app_helpers import (
    ALL_BRANDS,
    build_product_query,
    load_results_or_none,
    product_rows,
)
from cvs_radar.pipeline import run_pipeline
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
        filters = _render_ranking_filters(options)

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

        sorted_reports = _sort_reports(result.reports, filters["sort_by"])
        sorted_reports = sorted_reports[: int(filters["limit"])]
        result_filters = dict(result.filters)
        result_filters["limit"] = filters["limit"]
        result = ProductQueryResult(
            filters=result_filters,
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
            --qa-ink: #1f2933;
            --qa-muted: #5f6b76;
            --qa-line: #d7dde3;
            --qa-soft: #f5f7f9;
        }

        .stApp {
            background: #ffffff;
        }

        .block-container {
            padding-top: 0.85rem;
            padding-bottom: 2.5rem;
            max-width: 1420px;
        }

        .qa-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.75rem;
            padding-bottom: 0.45rem;
            margin-bottom: 0.55rem;
            border-bottom: 1px solid var(--qa-line);
        }

        .qa-title {
            margin: 0;
            color: var(--qa-ink);
            font-size: 1.25rem;
            line-height: 1.25;
            font-weight: 700;
            letter-spacing: 0;
        }

        .qa-caption,
        .qa-meta,
        .section-note {
            color: var(--qa-muted);
            font-size: 0.84rem;
            line-height: 1.45;
        }

        .qa-meta {
            font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
            white-space: nowrap;
        }

        .section-head {
            display: flex;
            align-items: baseline;
            justify-content: space-between;
            gap: 1rem;
            margin: 0.65rem 0 0.35rem;
        }

        .section-title {
            color: var(--qa-ink);
            font-size: 0.98rem;
            font-weight: 700;
            margin: 0;
        }

        .qa-summary {
            margin: 0.45rem 0 0.65rem;
            padding: 0.48rem 0.6rem;
            border: 1px solid var(--qa-line);
            background: var(--qa-soft);
            color: var(--qa-ink);
            font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
            font-size: 0.82rem;
            line-height: 1.55;
            overflow-wrap: anywhere;
        }

        .qa-summary strong {
            font-weight: 700;
        }

        .qa-filter-note {
            color: var(--qa-muted);
            font-size: 0.82rem;
            margin: -0.25rem 0 0.55rem;
        }

        .qa-inspector-hint {
            color: var(--qa-muted);
            font-size: 0.82rem;
            margin-bottom: 0.4rem;
        }

        /*
         * Streamlit 1.58.0 renders dataframe cells through glide-data-grid.
         * A read-only dataframe can still open glide's overlay editor on a
         * double-click; with selection reruns, that portal can remain visible
         * below the grid. These grids are navigational, not editable, so
         * suppress only the overlay editor while preserving cell selection.
         */
        div[class*="gdg-d19meir1"],
        div.gdg-style:has(.gdg-clip-region) {
            display: none !important;
            visibility: hidden !important;
            pointer-events: none !important;
        }

        @media (max-width: 900px) {
            .qa-header,
            .section-head {
                display: block;
            }

            .qa-meta {
                white-space: normal;
                margin-top: 0.2rem;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_header() -> None:
    st.markdown(
        """
        <div class="qa-header">
            <div>
                <h1 class="qa-title">CVS Radar QA</h1>
                <div class="qa-caption">results 快照查詢，供內部人工核對 scoring output 與 PTT 原文。</div>
            </div>
            <div class="qa-meta">source=results</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_ranking_filters(options: list[str]) -> dict[str, object]:
    with st.container(border=True):
        st.markdown("##### 查詢條件")
        st.markdown(
            '<div class="qa-filter-note">results 模式固定使用 data/results.json；這裡只調整排名清單如何篩選與排序。</div>',
            unsafe_allow_html=True,
        )
        recent_days = None
        start_date = None
        end_date = None

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
    top_label = "-"
    if top_report is not None:
        top_label = f"{top_report.get('product_name', '-')} ({_format_score(top_report.get('fair_score'))})"

    parts = [
        f"brand={selected_brand if selected_brand != ALL_BRANDS else 'ALL'}",
        f"products={len(reports):,}",
        f"scored={len(scored):,}",
        f"avg_fair_score={_format_decimal(avg_score)}",
        f"top_brand={top_brand}",
        f"posts/comments={total_posts:,}/{total_comments:,}",
        f"top={top_label}",
    ]
    if filters.get("min_score") is not None:
        parts.append(f"min_score={filters['min_score']}")
    if filters.get("min_n_eff") is not None:
        parts.append(f"min_n_eff={filters['min_n_eff']}")
    if int(filters.get("min_posts") or 0):
        parts.append(f"min_posts={filters['min_posts']}")
    if int(filters.get("min_comments") or 0):
        parts.append(f"min_comments={filters['min_comments']}")

    st.markdown(
        f'<div class="qa-summary"><strong>result</strong> | {escape(" | ".join(parts))}</div>',
        unsafe_allow_html=True,
    )


def _render_rankings(result, *, selection_key: str = "") -> None:
    rows = product_rows(result)
    if not rows:
        st.info("目前條件下沒有符合的商品。請放寬時間、品牌或進階篩選。")
        return

    st.markdown(
        """
        <div class="section-head">
            <p class="section-title">商品 ranking</p>
            <span class="section-note">點表格任一儲存格切換右側檢查記錄。</span>
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

    left, right = st.columns([1.45, 1], gap="medium")
    with left:
        event = st.dataframe(
            rows,
            hide_index=True,
            use_container_width=True,
            on_select="rerun",
            selection_mode="single-cell",
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
                "排名": st.column_config.NumberColumn("排名", width="small", disabled=True),
                "品牌": st.column_config.TextColumn("品牌", width="small", disabled=True),
                "商品": st.column_config.TextColumn("商品", disabled=True),
                "價格": st.column_config.NumberColumn("價格", format="%d", width="small", disabled=True),
                "分類": st.column_config.TextColumn("分類", width="small", disabled=True),
                "fair_score": st.column_config.NumberColumn("公平分數", format="%.1f", width="small", disabled=True),
                "consensus": st.column_config.TextColumn("共識", width="small", disabled=True),
                "討論聲量": st.column_config.TextColumn("討論聲量", width="small", disabled=True),
            },
        )
        selected_idx = _selected_idx_from_dataframe_state(event, fallback_idx=selected_idx, row_count=len(rows))
        st.session_state[state_key] = selected_idx

    row = rows[selected_idx]
    with right:
        _render_product_inspector(row)


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


_INSPECTOR_CSS = """
body { margin:0; font-family:-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; color:#1f2933; }
.record { border:1px solid #d7dde3; background:#fff; padding:0.75rem 0.8rem; }
.record-head { border-bottom:1px solid #d7dde3; padding-bottom:0.45rem; margin-bottom:0.55rem; }
.record-meta { color:#5f6b76; font-family:ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size:0.78rem; line-height:1.45; overflow-wrap:anywhere; }
.record-title { margin:0.18rem 0 0; font-size:1.02rem; line-height:1.35; font-weight:700; overflow-wrap:anywhere; }
.kv { display:grid; grid-template-columns:minmax(6.8rem, 0.8fr) minmax(0, 1.2fr); border-top:1px solid #e5e9ee; }
.kv:first-of-type { border-top:0; }
.kv-label { color:#5f6b76; font-size:0.78rem; padding:0.32rem 0.55rem 0.32rem 0; }
.kv-value { color:#1f2933; font-size:0.86rem; padding:0.32rem 0; font-weight:600; overflow-wrap:anywhere; }
.score-value { font-family:ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size:1rem; }
.block { margin-top:0.7rem; }
.block-title { color:#5f6b76; font-size:0.78rem; font-weight:700; margin-bottom:0.25rem; }
.text-block { border:1px solid #d7dde3; background:#f8fafc; padding:0.48rem 0.55rem; font-size:0.84rem; line-height:1.55; white-space:pre-wrap; overflow-wrap:anywhere; }
.comment-grid { display:grid; grid-template-columns:repeat(2, minmax(0, 1fr)); gap:0.55rem; }
.comment-list { margin:0; padding-left:1rem; font-size:0.83rem; line-height:1.5; }
.comment-list li { margin-bottom:0.2rem; overflow-wrap:anywhere; }
.post-links { display:flex; flex-direction:column; gap:0.25rem; margin-top:0.7rem; padding-top:0.55rem; border-top:1px solid #d7dde3; }
.post-link { color:#1f5fbf; font-size:0.8rem; overflow-wrap:anywhere; text-decoration:none; }
.post-link:hover { text-decoration:underline; }
@media(max-width:900px){ .comment-grid,.kv{grid-template-columns:1fr;} .kv-label{padding-bottom:0;} }
"""


def _render_product_inspector(row: dict[str, Any]) -> None:
    st.markdown("##### Selected record")
    st.markdown(
        f'<div class="qa-inspector-hint">#{escape(str(row.get("排名", "-")))} '
        f'{escape(str(row.get("品牌") or "-"))} / {escape(str(row.get("商品") or "-"))}</div>',
        unsafe_allow_html=True,
    )
    st.html(f"<style>{_INSPECTOR_CSS}</style>\n{_product_inspector_html(row)}")
    with st.expander("raw row", expanded=False):
        st.json(_json_safe_row(row), expanded=False)


def _product_inspector_html(row: dict[str, Any]) -> str:
    score = row.get("fair_score")
    brand = str(row.get("品牌") or "-")
    consensus = str(row.get("consensus") or "-")
    category = str(row.get("分類") or "-")
    volume = str(row.get("討論聲量") or "-")
    positive_comments = _split_comments(row.get("正向留言"))
    negative_comments = _split_comments(row.get("負向留言"))
    competitor_brands = str(row.get("提及競品") or "無")
    excerpt = str(row.get("心得節錄") or "").strip()
    post_urls = [u for u in (row.get("貼文連結") or []) if u]
    latest_post = str(row.get("最新發文") or "未知")
    own = int(row.get("偏好本品") or 0)
    other = int(row.get("偏好他牌") or 0)

    return f"""
    <section class="record">
        <div class="record-head">
            <div class="record-meta">rank={escape(str(row.get("排名", "-")))} | brand={escape(brand)} | category={escape(category)}</div>
            <h2 class="record-title">{escape(str(row.get("商品") or "-"))}</h2>
        </div>
        {_kv("fair_score", _format_score(score), value_class="score-value")}
        {_kv("consensus", consensus)}
        {_kv("discussion_volume", volume)}
        {_kv("latest_post_date", latest_post)}
        {_kv("competitor_preference", f'own={own:,} / other={other:,}')}
        {_kv("competitor_mentions", f'{int(row.get("競品提及") or 0):,}')}
        {_kv("competitor_brands", competitor_brands)}
        {_excerpt_html(excerpt)}
        <div class="block">
            <div class="block-title">representative comments</div>
            <div class="comment-grid">
                {_comment_block("positive", positive_comments, "尚無正向留言")}
                {_comment_block("negative", negative_comments, "尚無負向留言")}
            </div>
        </div>
        {_post_links_html(post_urls)}
    </section>"""


def _kv(label: str, value: object, *, value_class: str = "") -> str:
    css_class = f"kv-value {value_class}".strip()
    return (
        '<div class="kv">'
        f'<div class="kv-label">{escape(label)}</div>'
        f'<div class="{css_class}">{escape(str(value))}</div>'
        "</div>"
    )


def _comment_block(title: str, comments: list[str], fallback: str) -> str:
    items = comments or [fallback]
    body = "".join(f"<li>{escape(comment)}</li>" for comment in items)
    return (
        '<div class="text-block">'
        f'<div class="block-title">{escape(title)}</div>'
        f'<ul class="comment-list">{body}</ul>'
        "</div>"
    )


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
        '<div class="block">'
        '<div class="block-title">review_excerpt</div>'
        f'<div class="text-block">{escape(excerpt)}</div>'
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
            <p class="section-title">帳號信度維運</p>
            <span class="section-note">調整門檻後點選帳號，檢查完整留言歷史。</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    min_suspicion = st.slider("最低可疑分", 0.0, 1.0, 0.4, 0.01)
    filtered_profiles = [
        profile for profile in active_profiles if profile.suspicion_score >= min_suspicion
    ]

    avg_suspicion = (
        sum(profile.suspicion_score for profile in filtered_profiles) / len(filtered_profiles)
        if filtered_profiles
        else None
    )
    top_user = filtered_profiles[0].user if filtered_profiles else "-"
    st.markdown(
        '<div class="qa-summary"><strong>accounts</strong> | '
        f'threshold={min_suspicion:.2f} | suspicious={len(filtered_profiles):,} | '
        f'avg_suspicion={_format_decimal(avg_suspicion, digits=2)} | top_user={escape(top_user)}</div>',
        unsafe_allow_html=True,
    )

    overview_rows = [
        {
            "帳號": profile.user,
            "留言數": profile.total_comments,
            "傾向品牌": profile.lean_brand or "-",
            "可疑分": profile.suspicion_score,
        }
        for profile in filtered_profiles
    ]

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
            <span class="section-note">總覽、特徵與完整留言歷史分開核對。</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    selected_profile = filtered_profiles[selected_rows[0]]
    st.markdown(
        '<div class="qa-summary"><strong>selected_account</strong> | '
        f'user={escape(selected_profile.user)} | comments={selected_profile.total_comments:,} | '
        f'suspicion={selected_profile.suspicion_score:.2f} | '
        f'lean_brand={escape(selected_profile.lean_brand or "-")}</div>',
        unsafe_allow_html=True,
    )

    overview_tab, features_tab, comments_tab = st.tabs(["總覽", "特徵", "留言"])

    with overview_tab:
        st.markdown("##### 品牌互動")
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
        st.caption("可疑分由下列特徵加權而成；值越高代表越需要人工檢查。")
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
            st.info("尚無原始留言資料；請先執行爬取，讓本機 store 可讀取完整留言。")
        else:
            rows = _account_comment_rows(selected_profile.user, display_posts)
            if not rows:
                st.info("找不到此帳號在目前原始資料中的留言。")
            else:
                st.caption(f"共 {len(rows):,} 則留言；表格顯示完整留言，不只顯示被標記的子集合。")
                st.dataframe(
                    rows,
                    hide_index=True,
                    use_container_width=True,
                    column_order=["時間", "品牌", "商品/標題", "留言", "原文"],
                    column_config={
                        "時間": st.column_config.TextColumn("時間", width="small"),
                        "品牌": st.column_config.TextColumn("品牌", width="small"),
                        "商品/標題": st.column_config.TextColumn("商品/標題", width="medium"),
                        "留言": st.column_config.TextColumn("留言", width="large"),
                        "原文": st.column_config.LinkColumn("原文", display_text="PTT"),
                    },
                )


def _account_comment_rows(user: str, posts) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for post in posts or []:
        for comment in post.comments:
            if comment.user != user:
                continue
            rows.append(
                {
                    "時間": comment.posted_at.strftime("%Y-%m-%d %H:%M") if comment.posted_at else "",
                    "品牌": post.brand,
                    "商品/標題": post.product_name or post.title,
                    "留言": comment.text,
                    "原文": post.url,
                }
            )
    rows.sort(key=lambda row: str(row["時間"]), reverse=True)
    return rows


def _json_safe_row(row: dict[str, Any]) -> dict[str, object]:
    safe: dict[str, object] = {}
    for key, value in row.items():
        if isinstance(value, datetime):
            safe[key] = value.isoformat()
        elif isinstance(value, (str, int, float, bool)) or value is None:
            safe[key] = value
        elif isinstance(value, (list, tuple)):
            safe[key] = [str(item) for item in value]
        else:
            safe[key] = str(value)
    return safe


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


def _top_brand_name(brands: object) -> str:
    if not brands:
        return "-"
    first = brands[0]
    if isinstance(first, dict):
        return str(first.get("brand") or "-")
    return str(getattr(first, "brand", "-") or "-")


if __name__ == "__main__":
    main()
