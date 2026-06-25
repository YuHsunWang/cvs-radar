"""Streamlit UI for CVS Radar."""

from __future__ import annotations

from datetime import datetime, timedelta

import streamlit as st

from cvs_radar.app_helpers import (
    ALL_BRANDS,
    brand_options,
    build_product_query,
    load_posts,
    product_rows,
)
from cvs_radar.pipeline import run_pipeline
from cvs_radar.reporting import render_suspicion_detail
from cvs_radar.service import query_products


def main() -> None:
    st.set_page_config(page_title="CVS Radar", page_icon=":bar_chart:", layout="wide")
    st.title("CVS Radar 商品評分排名")
    st.caption("依時間挑選評論、依品牌挑選商品，並用服務層評分結果排序。")

    controls = _render_sidebar()

    try:
        posts = load_posts(
            controls["source"],
            crawl_pages=controls["crawl_pages"],
            start_date=controls["start_date"],
            end_date=controls["end_date"],
            recent_days=controls["recent_days"],
        )
        options = brand_options(
            posts,
            start_date=controls["start_date"],
            end_date=controls["end_date"],
            recent_days=controls["recent_days"],
        )
    except ValueError as exc:
        st.error(str(exc))
        return
    except Exception as exc:  # pragma: no cover - UI safety net
        st.error(f"資料載入失敗：{exc}")
        return

    tab1, tab2 = st.tabs(["商品排名", "帳號信度維運"])

    with tab1:
        selected_brand = st.selectbox("品牌", options, index=0)
        query = build_product_query(
            brand=selected_brand,
            start_date=controls["start_date"],
            end_date=controls["end_date"],
            recent_days=controls["recent_days"],
            min_score=controls["min_score"],
            min_n_eff=controls["min_n_eff"],
            min_posts=controls["min_posts"],
            min_comments=controls["min_comments"],
            limit=controls["limit"],
            internal=False,
        )

        try:
            result = query_products(posts, query)
        except ValueError as exc:
            st.error(str(exc))
            return

        _render_summary(result.to_dict(), selected_brand)
        _render_rankings(result)

    with tab2:
        _render_account_maintenance(posts, controls)


def _render_sidebar() -> dict[str, object]:
    with st.sidebar:
        st.header("篩選")

        source_label = st.radio("資料來源", ["demo 離線樣本", "crawl PTT CVS"], index=0)
        source = "demo" if source_label.startswith("demo") else "crawl"
        crawl_pages = 5
        if source == "crawl":
            st.warning("crawl 會連線到 PTT；demo 不會連網。")
            crawl_pages = int(st.number_input("PTT 頁數", min_value=1, max_value=50, value=5, step=1))

        time_mode = st.radio("時間選擇", ["近 N 天", "起訖日期"], horizontal=True)
        recent_days = None
        start_date = None
        end_date = None
        if time_mode == "近 N 天":
            recent_days = int(st.number_input("近 N 天", min_value=0, max_value=3650, value=30, step=1))
        else:
            today = datetime.now().date()
            default_start = today - timedelta(days=30)
            start_date = st.date_input("起始日期", value=default_start)
            end_date = st.date_input("結束日期", value=today)

        st.subheader("進階篩選")
        use_min_score = st.checkbox("啟用最低分", value=False)
        min_score = None
        if use_min_score:
            min_score = float(st.number_input("min_score", min_value=0.0, max_value=100.0, value=60.0, step=1.0))

        use_min_n_eff = st.checkbox("啟用最低有效樣本", value=False)
        min_n_eff = None
        if use_min_n_eff:
            min_n_eff = float(st.number_input("最低有效樣本值", min_value=0.0, value=1.0, step=0.5))

        min_posts = int(st.number_input("最少貼文", min_value=0, value=0, step=1))
        min_comments = int(st.number_input("最少留言", min_value=0, value=0, step=1))
        limit = int(st.number_input("筆數上限", min_value=1, max_value=500, value=20, step=1))

    return {
        "source": source,
        "crawl_pages": crawl_pages,
        "recent_days": recent_days,
        "start_date": start_date,
        "end_date": end_date,
        "min_score": min_score,
        "min_n_eff": min_n_eff,
        "min_posts": min_posts,
        "min_comments": min_comments,
        "limit": limit,
    }


def _render_summary(payload: dict[str, object], selected_brand: str) -> None:
    filters = payload["filters"]
    brands = payload["brands"]
    reports = payload["reports"]

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("品牌", selected_brand if selected_brand != ALL_BRANDS else "全部")
    col2.metric("符合商品", len(reports))
    col3.metric("篩選後品牌", len(brands))
    col4.metric("時間模式", "近 N 天" if filters["recent_days"] is not None else "起訖日期/不限")

    with st.expander("目前查詢條件", expanded=False):
        st.json(filters)


def _render_rankings(result) -> None:
    rows = product_rows(result)
    if not rows:
        st.info("目前條件下沒有符合的商品。請放寬時間、品牌或進階篩選。")
        return

    st.subheader("評分排名")
    st.dataframe(
        rows,
        hide_index=True,
        use_container_width=True,
        column_config={
            "fair_score": st.column_config.NumberColumn("fair_score", format="%.1f"),
            "有效樣本": st.column_config.NumberColumn("有效樣本", format="%.2f"),
            "n_posts": st.column_config.NumberColumn("貼文數"),
            "n_comments": st.column_config.NumberColumn("留言數"),
            "競品提及": st.column_config.NumberColumn("競品提及"),
            "偏好他牌": st.column_config.NumberColumn("偏好他牌"),
            "提及競品": st.column_config.TextColumn(width="small"),
            "代表性推": st.column_config.TextColumn(width="medium"),
            "代表性噓": st.column_config.TextColumn(width="medium"),
        },
    )

    st.subheader("商品細節")
    for row in rows:
        score = "無分數" if row["fair_score"] is None else f'{row["fair_score"]:.1f}'
        title = f'#{row["排名"]} [{row["品牌"]}] {row["商品"]} - {score}'
        with st.expander(title, expanded=row["排名"] == 1):
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("consensus", row["consensus"])
            c2.metric("confidence", row["confidence"])
            c3.metric("資料狀態", row["資料狀態"])
            c4.metric("貼文/留言", f'{row["n_posts"]}/{row["n_comments"]}')
            st.write(
                "競品提及：",
                f'{row["競品提及"]} 則，其中 {row["偏好他牌"]} 則偏好他牌',
                f'（{row["提及競品"] or "無"}）',
            )
            st.write("代表性推：", row["代表性推"] or "無")
            st.write("代表性噓：", row["代表性噓"] or "無")


def _render_account_maintenance(posts, controls: dict[str, object]) -> None:
    try:
        _, profiles = run_pipeline(
            posts,
            start_date=controls["start_date"],
            end_date=controls["end_date"],
            recent_days=controls["recent_days"],
        )
    except ValueError as exc:
        st.error(str(exc))
        return

    active_profiles = [
        profile
        for profile in sorted(profiles.values(), key=lambda item: -item.suspicion_score)
        if profile.suspicion_features
    ]

    st.subheader("帳號概覽")
    min_suspicion = st.slider("最低可疑分", 0.0, 1.0, 0.0, 0.01)
    filtered_profiles = [
        profile for profile in active_profiles if profile.suspicion_score >= min_suspicion
    ]

    overview_rows = [
        {
            "帳號": profile.user,
            "留言數": profile.total_comments,
            "傾向品牌": profile.lean_brand or "-",
            "可疑分": profile.suspicion_score,
            "信度": profile.credibility,
        }
        for profile in filtered_profiles
    ]
    st.dataframe(
        overview_rows,
        hide_index=True,
        use_container_width=True,
        column_config={
            "留言數": st.column_config.NumberColumn("留言數"),
            "可疑分": st.column_config.NumberColumn("可疑分", format="%.2f"),
            "信度": st.column_config.NumberColumn("信度", format="%.2f"),
        },
    )

    if not filtered_profiles:
        st.info("目前條件下沒有達活動量門檻且符合最低可疑分的帳號。")
        return

    st.subheader("帳號明細")
    selected_user = st.selectbox("選擇帳號", [profile.user for profile in filtered_profiles])
    selected_profile = next(
        profile for profile in filtered_profiles if profile.user == selected_user
    )

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("留言數", selected_profile.total_comments)
    col2.metric("信度", f"{selected_profile.credibility:.2f}")
    col3.metric("可疑分", f"{selected_profile.suspicion_score:.2f}")
    col4.metric("傾向品牌", selected_profile.lean_brand or "-")

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
            "留言數": st.column_config.NumberColumn("留言數"),
            "平均情感": st.column_config.NumberColumn("平均情感", format="%.2f"),
        },
    )

    st.markdown("#### 特徵明細")
    explanations = {
        "one_sided": "偏向單一品牌正面、競品負面的程度",
        "single_brand": "留言集中在單一品牌的程度",
        "extreme": "極端情感留言比例",
        "template_like": "完全重複或近似樣板留言比例",
        "burst": "同品牌短時間爆發留言比例",
    }
    feature_rows = [
        {
            "特徵": name,
            "值": selected_profile.suspicion_features.get(name, 0.0),
            "說明": explanation,
        }
        for name, explanation in explanations.items()
    ]
    st.dataframe(
        feature_rows,
        hide_index=True,
        use_container_width=True,
        column_config={"值": st.column_config.NumberColumn("值", format="%.2f")},
    )

    st.markdown("#### 被標記留言")
    st.code(render_suspicion_detail(selected_profile, posts), language="text")


if __name__ == "__main__":
    main()
