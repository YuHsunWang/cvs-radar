"""End-to-end pipeline orchestration."""

from __future__ import annotations

from datetime import date, datetime

from .filters import filter_posts_by_time
from .models import Post, ProductReport
from .preference import AccountProfile, build_profiles
from .scoring import preprocess_posts, score_all
from .sentiment import annotate_posts


def run_pipeline(
    posts: list[Post],
    *,
    start_date: str | date | datetime | None = None,
    end_date: str | date | datetime | None = None,
    recent_days: int | None = None,
    now: datetime | None = None,
) -> tuple[list[ProductReport], dict[str, AccountProfile]]:
    """執行完整資料處理管線。"""
    selected = filter_posts_by_time(
        posts,
        start_date=start_date,
        end_date=end_date,
        recent_days=recent_days,
        now=now,
    )
    preprocessed = preprocess_posts(selected)
    annotated = annotate_posts(preprocessed)
    profiles = build_profiles(annotated)
    reports = score_all(annotated, profiles)
    return reports, profiles
