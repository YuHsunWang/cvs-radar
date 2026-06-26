"""Utilities for creating offline comment-labeling CSV files."""

from __future__ import annotations

import argparse
import csv
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .models import Post


CONTEXT_COLUMNS = [
    "comment_id",
    "source",
    "board",
    "post_id",
    "post_url",
    "post_title",
    "post_brand",
    "product_name",
    "price",
    "post_tag",
    "comment_user",
    "comment_tag",
    "comment_text",
    "comment_posted_at",
    "context",
]

LABEL_COLUMNS = ["sentiment", "target_brand", "is_comparative", "favored_brand", "notes"]
CSV_COLUMNS = [*CONTEXT_COLUMNS, *LABEL_COLUMNS]


@dataclass(frozen=True, slots=True)
class LabelingRow:
    comment_id: str
    source: str
    board: str
    post_id: str
    post_url: str
    post_title: str
    post_brand: str
    product_name: str
    price: str
    post_tag: str
    comment_user: str
    comment_tag: str
    comment_text: str
    comment_posted_at: str
    context: str
    sentiment: str = ""
    target_brand: str = ""
    is_comparative: str = ""
    favored_brand: str = ""
    notes: str = ""

    def to_dict(self) -> dict[str, str]:
        return {column: str(getattr(self, column)) for column in CSV_COLUMNS}


def build_labeling_rows(
    posts: Iterable[Post],
    *,
    limit: int | None = None,
    shuffle: bool = False,
    seed: int = 0,
) -> list[LabelingRow]:
    """Build deterministic rows for human labeling."""
    if limit is not None and limit < 0:
        raise ValueError("limit must be non-negative")

    rows: list[LabelingRow] = []
    for post in posts:
        post_tag = _post_tag(post.title)
        for index, comment in enumerate(post.comments):
            comment_id = f"{post.id}#{index:03d}"
            rows.append(
                LabelingRow(
                    comment_id=comment_id,
                    source=post.source,
                    board=post.board,
                    post_id=post.id,
                    post_url=post.url,
                    post_title=post.title,
                    post_brand=post.brand,
                    product_name=post.product_name,
                    price=post.price or "",
                    post_tag=post_tag,
                    comment_user=comment.user,
                    comment_tag=comment.tag,
                    comment_text=comment.text,
                    comment_posted_at=comment.posted_at.isoformat() if comment.posted_at else "",
                    context=_context(post, post_tag),
                )
            )

    if shuffle:
        rng = random.Random(seed)
        rng.shuffle(rows)

    return rows[:limit] if limit is not None else rows


def write_labeling_csv(rows: Iterable[LabelingRow], path: str | Path) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.to_dict())


def read_labeling_csv(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open("r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _context(post: Post, post_tag: str) -> str:
    parts = [
        f"貼文品牌={post.brand}",
        f"商品={post.product_name or 'unknown'}",
        f"tag={post_tag or 'unknown'}",
    ]
    if post.price:
        parts.append(f"價格={post.price}")
    if post.title:
        parts.append(f"標題={post.title}")
    return "; ".join(parts)


def _post_tag(title: str) -> str:
    match = re.search(r"[\[【](.*?)[\]】]", title or "")
    return match.group(1).strip() if match else ""


def _load_posts(source: str, *, pages: int) -> list[Post]:
    if source == "demo":
        from .sample_data import load_sample

        return load_sample()
    if source == "stored":
        from .store import load_posts as load_stored

        posts = load_stored()
        if not posts:
            raise ValueError("No stored posts found. Run crawl_job.py first.")
        return posts
    if source == "crawl":
        from .crawler import PttCrawler

        return PttCrawler().crawl(max_pages=pages)
    raise ValueError(f"unsupported source: {source}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Create a CVS Radar labeling CSV")
    parser.add_argument("--source", choices=["demo", "crawl", "stored"], default="demo")
    parser.add_argument("--output", default="data/labels/to_label.csv")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--shuffle", action="store_true")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--pages", type=int, default=5, help="PTT pages when --source=crawl")
    args = parser.parse_args(argv)

    posts = _load_posts(args.source, pages=args.pages)
    rows = build_labeling_rows(posts, limit=args.limit, shuffle=args.shuffle, seed=args.seed)
    write_labeling_csv(rows, args.output)
    print(f"Wrote {len(rows)} rows to {args.output}")


if __name__ == "__main__":
    main()
