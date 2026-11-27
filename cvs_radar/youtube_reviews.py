"""YouTube creators' spoken verdicts, one row per product mentioned in a video.

`scripts/youtube_reviews.py` fills the CSV (transcribe, LLM extract, LLM verify);
`web/build_data.py` reads it. Only the creator's own verdict is kept, summarised
in our words with a link to the second it is said. Comments are never read, so
no viewer identity can enter this file.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any

from cvs_radar.product_categories import CATEGORIES

REVIEWS_PATH = Path("data/labels/youtube_reviews.csv")
VIDEOS_PATH = Path("data/labels/youtube_videos.csv")

REVIEW_FIELDS = (
    "video_id", "channel", "video_date", "start_seconds", "brand", "product_name",
    "product_id", "category", "price", "creator_score", "summary",
)
VIDEO_FIELDS = ("video_id", "channel", "published", "status", "processed_at")

BRANDS = ("7-11", "全家", "萊爾富", "OK")
MAX_SUMMARY_CHARS = 40
VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
# As the creator said it: "9/10", "6.5/10", "4/5", "85/100".
CREATOR_SCORE = re.compile(r"\d{1,3}(?:\.\d)?/(?:5|10|100)")
URL = re.compile(r"https?://|www\.", re.I)


def review_errors(row: dict[str, str], duration_seconds: int | None = None) -> list[str]:
    """Mechanical checks an extracted row must pass before it can be published."""
    errors = []
    if not VIDEO_ID.fullmatch(row.get("video_id", "")):
        errors.append("bad video_id")
    if not row.get("channel", "").strip():
        errors.append("missing channel")
    if not DATE.fullmatch(row.get("video_date", "")):
        errors.append("bad video_date")
    start = row.get("start_seconds", "")
    if not start.isdigit():
        errors.append("bad start_seconds")
    elif duration_seconds is not None and int(start) > duration_seconds:
        errors.append("start_seconds past the end of the video")
    if row.get("brand") not in BRANDS:
        errors.append(f"brand {row.get('brand')!r} is not one of {BRANDS}")
    name = row.get("product_name", "").strip()
    if not name or len(name) > 30:
        errors.append("product_name empty or longer than 30")
    if row.get("category") not in CATEGORIES:
        errors.append(f"category {row.get('category')!r} not in the closed list")
    price = row.get("price", "")
    if price and not (price.isdigit() and 0 < int(price) < 2000):
        errors.append("bad price")
    score = row.get("creator_score", "")
    if score and not CREATOR_SCORE.fullmatch(score):
        errors.append("bad creator_score")
    summary = row.get("summary", "").strip()
    if not summary or len(summary) > MAX_SUMMARY_CHARS:
        errors.append(f"summary empty or longer than {MAX_SUMMARY_CHARS}")
    if URL.search(summary) or URL.search(name):
        errors.append("URL in text")
    return errors


def load_reviews(path: Path = REVIEWS_PATH) -> list[dict[str, str]]:
    """Committed rows; a malformed row stops the build instead of reaching the site."""
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != REVIEW_FIELDS:
            raise ValueError(f"invalid columns in {path}")
        rows = list(reader)
    for line, row in enumerate(rows, start=2):
        if errors := review_errors(row):
            raise ValueError(f"{path} line {line}: {'; '.join(errors)}")
    return rows


def public_review(row: dict[str, str]) -> dict[str, Any]:
    return {
        "channel": row["channel"],
        "summary": row["summary"].strip(),
        "score": row["creator_score"] or None,
        "url": f"https://www.youtube.com/watch?v={row['video_id']}&t={int(row['start_seconds'])}s",
        "date": row["video_date"],
    }


def load_videos(path: Path = VIDEOS_PATH) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return {row["video_id"]: row for row in csv.DictReader(handle)}


def append_rows(path: Path, fields: tuple[str, ...], rows: list[dict[str, Any]]) -> None:
    """Append, writing the header (with BOM, like the other label CSVs) on first use."""
    new = not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8-sig" if new else "utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        if new:
            writer.writeheader()
        writer.writerows({key: row.get(key, "") for key in fields} for row in rows)
