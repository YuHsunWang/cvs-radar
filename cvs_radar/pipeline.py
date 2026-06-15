"""End-to-end pipeline orchestration."""

from __future__ import annotations

from .models import Post, ProductReport
from .preference import AccountProfile, build_profiles
from .scoring import score_all
from .sentiment import annotate_posts


def run_pipeline(posts: list[Post]) -> tuple[list[ProductReport], dict[str, AccountProfile]]:
    annotated = annotate_posts(posts)
    profiles = build_profiles(annotated)
    reports = score_all(annotated, profiles)
    return reports, profiles
