"""JSONL persistence for posts and precomputed result objects."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .models import Comment, Contributor, Post, ProductReport
from .preference import AccountProfile, BrandStat

DEFAULT_STORE_PATH = "data/posts.jsonl"
DEFAULT_RESULTS_PATH = "data/results.json"


def post_to_dict(post: Post) -> dict:
    """Serialize a Post to a JSON-safe dict."""
    return {
        "id": post.id,
        "source": post.source,
        "board": post.board,
        "url": post.url,
        "title": post.title,
        "brand": post.brand,
        "product_name": post.product_name,
        "price": post.price,
        "author": post.author,
        "author_score": post.author_score,
        "review_text": post.review_text,
        "posted_at": post.posted_at.isoformat() if post.posted_at else None,
        "is_reply": post.is_reply,
        "push_count": post.push_count,
        "raw": post.raw,
        "comments": [
            {
                "tag": c.tag,
                "user": c.user,
                "text": c.text,
                "posted_at": c.posted_at.isoformat() if c.posted_at else None,
                "sentiment": c.sentiment,
                "backend": c.backend,
            }
            for c in post.comments
        ],
    }


def dict_to_post(data: dict) -> Post:
    """Deserialize a dict back to a Post."""
    comments = [
        Comment(
            tag=c["tag"],
            user=c["user"],
            text=c["text"],
            posted_at=datetime.fromisoformat(c["posted_at"]) if c.get("posted_at") else None,
            sentiment=c.get("sentiment"),
            backend=c.get("backend", ""),
        )
        for c in data.get("comments", [])
    ]
    return Post(
        id=data["id"],
        source=data.get("source", "PTT"),
        board=data.get("board", "CVS"),
        url=data.get("url", ""),
        title=data.get("title", ""),
        brand=data.get("brand", "其他"),
        product_name=data.get("product_name", ""),
        price=data.get("price"),
        author=data.get("author", ""),
        author_score=data.get("author_score"),
        review_text=data.get("review_text", ""),
        posted_at=datetime.fromisoformat(data["posted_at"]) if data.get("posted_at") else None,
        is_reply=data.get("is_reply", False),
        push_count=data.get("push_count"),
        raw=data.get("raw"),
        comments=comments,
    )


def save_posts(posts: list[Post], path: str | Path = DEFAULT_STORE_PATH) -> int:
    """Append posts to a JSONL file. Returns number of NEW posts written."""
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)

    existing_ids = set()
    if file_path.exists():
        existing_ids = {post.id for post in load_posts(path)}

    new_count = 0
    with open(file_path, "a", encoding="utf-8") as f:
        for post in posts:
            if post.id in existing_ids:
                continue
            f.write(json.dumps(post_to_dict(post), ensure_ascii=False) + "\n")
            existing_ids.add(post.id)
            new_count += 1
    return new_count


def load_posts(path: str | Path = DEFAULT_STORE_PATH) -> list[Post]:
    """Load all posts from a JSONL file. Deduplicates by post id."""
    file_path = Path(path)
    if not file_path.exists():
        return []

    seen_ids: set[str] = set()
    posts: list[Post] = []
    for line in file_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        data = json.loads(line)
        if data["id"] in seen_ids:
            continue
        seen_ids.add(data["id"])
        posts.append(dict_to_post(data))
    return posts


def store_stats(path: str | Path = DEFAULT_STORE_PATH) -> dict:
    """Return basic stats about the stored data."""
    posts = load_posts(path)
    brands = set(p.brand for p in posts)
    date_range = None
    dates = [p.posted_at for p in posts if p.posted_at]
    if dates:
        date_range = (min(dates).isoformat(), max(dates).isoformat())
    return {
        "path": str(path),
        "post_count": len(posts),
        "comment_count": sum(len(p.comments) for p in posts),
        "brands": sorted(brands),
        "date_range": date_range,
    }


def report_to_store_dict(report: ProductReport) -> dict:
    """Serialize a ProductReport for storage."""
    return {
        "brand": report.brand,
        "product_name": report.product_name,
        "fair_score": report.fair_score,
        "consensus": report.consensus,
        "confidence": report.confidence,
        "n_eff": report.n_eff,
        "score_std": report.score_std,
        "n_posts": report.n_posts,
        "n_comments": report.n_comments,
        "contributors": [
            {"user": c.user, "role": c.role, "score": c.score, "weight": c.weight}
            for c in report.contributors
        ],
        "rep_positive": report.rep_positive,
        "rep_negative": report.rep_negative,
        "product_key": report.product_key,
        "score_mean": report.score_mean,
        "price": report.price,
        "category": report.category,
        "competitor_mention_count": report.competitor_mention_count,
        "competitor_preference_count": report.competitor_preference_count,
        "competitor_brands": report.competitor_brands,
    }


def store_dict_to_report(data: dict) -> ProductReport:
    """Deserialize a stored dict back to ProductReport."""
    contributors = [
        Contributor(
            user=c["user"],
            role=c["role"],
            score=c["score"],
            weight=c["weight"],
        )
        for c in data.get("contributors", [])
    ]
    return ProductReport(
        brand=data["brand"],
        product_name=data["product_name"],
        fair_score=data.get("fair_score"),
        consensus=data["consensus"],
        confidence=data["confidence"],
        n_eff=data["n_eff"],
        score_std=data["score_std"],
        n_posts=data["n_posts"],
        n_comments=data["n_comments"],
        contributors=contributors,
        rep_positive=data.get("rep_positive", []),
        rep_negative=data.get("rep_negative", []),
        product_key=data.get("product_key", ""),
        score_mean=data.get("score_mean", 0.0),
        price=data.get("price"),
        category=data.get("category", ""),
        competitor_mention_count=data.get("competitor_mention_count", 0),
        competitor_preference_count=data.get("competitor_preference_count", 0),
        competitor_brands=data.get("competitor_brands", []),
    )


def profile_to_store_dict(profile: AccountProfile) -> dict:
    """Serialize an AccountProfile for storage."""
    return {
        "user": profile.user,
        "source": profile.source,
        "brand_stats": {
            brand: {"count": stat.count, "avg_sentiment": stat.avg_sentiment}
            for brand, stat in profile.brand_stats.items()
        },
        "lean_brand": profile.lean_brand,
        "suspicion_score": profile.suspicion_score,
        "suspicion_features": profile.suspicion_features,
        "credibility": profile.credibility,
        "total_comments": profile.total_comments,
    }


def store_dict_to_profile(data: dict) -> AccountProfile:
    """Deserialize a stored dict back to AccountProfile."""
    brand_stats = {
        brand: BrandStat(count=s["count"], avg_sentiment=s["avg_sentiment"])
        for brand, s in data.get("brand_stats", {}).items()
    }
    return AccountProfile(
        user=data["user"],
        source=data.get("source", "PTT"),
        brand_stats=brand_stats,
        lean_brand=data.get("lean_brand"),
        suspicion_score=data.get("suspicion_score", 0.0),
        suspicion_features=data.get("suspicion_features", {}),
        credibility=data.get("credibility", 1.0),
        total_comments=data.get("total_comments", 0),
    )


def save_results(
    reports: list[ProductReport],
    profiles: dict[str, AccountProfile],
    path: str | Path = DEFAULT_RESULTS_PATH,
) -> None:
    """Save computed results (reports + profiles) to a JSON file."""
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now().isoformat(sep=" ", timespec="seconds"),
        "reports": [report_to_store_dict(r) for r in reports],
        "profiles": [profile_to_store_dict(p) for p in profiles.values()],
    }
    file_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_results(
    path: str | Path = DEFAULT_RESULTS_PATH,
) -> tuple[list[ProductReport], dict[str, AccountProfile]] | None:
    """Load precomputed results. Returns None if file doesn't exist."""
    file_path = Path(path)
    if not file_path.exists():
        return None
    data = json.loads(file_path.read_text(encoding="utf-8"))
    reports = [store_dict_to_report(r) for r in data.get("reports", [])]
    profiles = {
        p["user"]: store_dict_to_profile(p)
        for p in data.get("profiles", [])
    }
    return reports, profiles
