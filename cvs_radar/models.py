"""Data models shared by crawler, parser, scoring, and reporting."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class Comment:
    tag: str
    user: str
    text: str
    posted_at: datetime | None = None
    sentiment: float | None = None


@dataclass(slots=True)
class Post:
    id: str
    source: str = "PTT"
    board: str = "CVS"
    url: str = ""
    title: str = ""
    brand: str = "其他"
    product_name: str = ""
    price: str | None = None
    author: str = ""
    author_score: float | None = None
    review_text: str = ""
    posted_at: datetime | None = None
    is_reply: bool = False
    push_count: int | None = None
    comments: list[Comment] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Contributor:
    user: str
    role: str
    score: float
    weight: float


@dataclass(slots=True)
class ProductReport:
    brand: str
    product_name: str
    fair_score: float | None
    consensus: str
    confidence: str
    n_eff: float
    score_std: float
    n_posts: int
    n_comments: int
    contributors: list[Contributor] = field(default_factory=list)
    rep_positive: list[str] = field(default_factory=list)
    rep_negative: list[str] = field(default_factory=list)
    product_key: str = ""
    score_mean: float = 0.0
    price: int | None = None
    category: str = ""
    competitor_mention_count: int = 0
    competitor_preference_count: int = 0
    competitor_brands: list[str] = field(default_factory=list)
