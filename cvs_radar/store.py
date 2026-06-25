"""JSONL persistence for Post objects."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .models import Comment, Post

DEFAULT_STORE_PATH = "data/posts.jsonl"


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
        "comments": [
            {
                "tag": c.tag,
                "user": c.user,
                "text": c.text,
                "posted_at": c.posted_at.isoformat() if c.posted_at else None,
                "sentiment": c.sentiment,
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
