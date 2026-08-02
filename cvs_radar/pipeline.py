"""End-to-end pipeline orchestration."""

from __future__ import annotations

from datetime import date, datetime

from .filters import filter_posts_by_time
from .models import Post, ProductReport
from .preference import AccountProfile, build_profiles
from .scoring import build_comment_opinions, preprocess_posts, score_all
from .sentiment import annotate_posts, apply_sentiment_overrides


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
    annotated = apply_sentiment_overrides(annotate_posts(preprocessed))
    opinions = build_comment_opinions(annotated)
    profiles = build_profiles(annotated, opinions)
    # The same instant drives the time filter and the score decay, so re-running a
    # pipeline with an explicit `now` reproduces its scores instead of drifting as
    # the wall clock moves.
    reports = score_all(annotated, profiles, now, opinions)
    return reports, profiles
