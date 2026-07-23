"""Backfill missing author review text from stored PTT article URLs."""

from __future__ import annotations

import json
import logging
from collections import Counter
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from .filters import normalize_datetime, parse_datetime
from .parser import parse_ptt_article


logger = logging.getLogger(__name__)


def is_backfill_candidate(row: dict) -> bool:
    """Return whether a stored row is safe and useful to refetch."""
    if str(row.get("review_text") or "").strip():
        return False
    title = str(row.get("title") or "")
    if row.get("is_reply") or title.lower().startswith("re:"):
        return False
    url = str(row.get("url") or "")
    parsed = urlparse(url)
    return (
        parsed.scheme == "https"
        and parsed.netloc == "www.ptt.cc"
        and parsed.path.startswith("/bbs/CVS/")
    )


def backfill_missing_reviews(
    rows: list[dict],
    fetch_html: Callable[[str], str],
    *,
    limit: int | None = None,
) -> tuple[list[dict], int, int]:
    """Refetch candidate rows and return (rows, attempted, updated)."""
    result = [dict(row) for row in rows]
    attempted = 0
    updated = 0
    counts: Counter[str] = Counter()

    for index, row in enumerate(result):
        if not is_backfill_candidate(row):
            continue
        if limit is not None and attempted >= limit:
            break
        attempted += 1
        url = str(row["url"])
        try:
            parsed = parse_ptt_article(fetch_html(url), url, str(row.get("board") or "CVS"))
        except Exception as exc:
            counts[f"transient_failure:{type(exc).__name__}"] += 1
            logger.warning("backfill transient failure for %s (%s): %s", url, type(exc).__name__, exc)
            continue
        if parsed is None:
            counts["non_product"] += 1
            continue
        counts["parse_success"] += 1
        if not parsed.review_text.strip():
            counts["no_review_text"] += 1
            continue
        row["review_text"] = parsed.review_text
        updated += 1
        counts["updated"] += 1

    logger.info("backfill outcome counts: %s", dict(sorted(counts.items())))
    return result, attempted, updated


def is_recent_refresh_candidate(
    row: dict,
    *,
    recent_days: int,
    now: datetime | None = None,
) -> bool:
    """Return whether a stored PTT CVS article should be refreshed for new comments."""
    if recent_days <= 0:
        return False
    url = str(row.get("url") or "")
    parsed_url = urlparse(url)
    if not (
        parsed_url.scheme == "https"
        and parsed_url.netloc == "www.ptt.cc"
        and parsed_url.path.startswith("/bbs/CVS/")
    ):
        return False

    raw_posted_at = row.get("posted_at")
    if not raw_posted_at:
        return False
    posted_at = parse_datetime(str(raw_posted_at))
    if posted_at is None:
        raise ValueError(f"invalid date/datetime: {raw_posted_at!r}")

    current = normalize_datetime(now or datetime.now(timezone.utc))
    age = current - normalize_datetime(posted_at)
    return timedelta(0) <= age <= timedelta(days=recent_days)


def refresh_recent_posts(
    rows: list[dict],
    fetch_html: Callable[[str], str],
    *,
    recent_days: int = 30,
    now: datetime | None = None,
    limit: int | None = None,
) -> tuple[list[dict], int, int]:
    """Refetch recent stored articles and replace their comment snapshots.

    Failed fetches keep the previous row. Successful parses replace comments with
    the article's current complete snapshot, avoiding duplicate accumulation.
    """
    from .store import post_to_dict

    result = [dict(row) for row in rows]
    attempted = 0
    updated = 0
    counts: Counter[str] = Counter()

    for index, row in enumerate(result):
        if not is_recent_refresh_candidate(row, recent_days=recent_days, now=now):
            continue
        if limit is not None and attempted >= limit:
            break
        attempted += 1
        url = str(row["url"])
        try:
            parsed = parse_ptt_article(fetch_html(url), url, str(row.get("board") or "CVS"))
        except Exception as exc:
            counts[f"transient_failure:{type(exc).__name__}"] += 1
            logger.warning("refresh transient failure for %s (%s): %s", url, type(exc).__name__, exc)
            continue
        if parsed is None:
            counts["non_product"] += 1
            continue
        counts["parse_success"] += 1

        refreshed = post_to_dict(parsed)
        merged = dict(row)
        merged.update(refreshed)
        merged["id"] = row.get("id", refreshed["id"])
        if refreshed.get("push_count") is None:
            merged["push_count"] = row.get("push_count")
        if not str(refreshed.get("review_text") or "").strip() and str(row.get("review_text") or "").strip():
            merged["review_text"] = row["review_text"]
        result[index] = merged
        updated += 1
        counts["updated"] += 1

    logger.info("refresh outcome counts: %s", dict(sorted(counts.items())))
    return result, attempted, updated


def read_jsonl(path: str | Path) -> list[dict]:
    file_path = Path(path)
    if not file_path.exists():
        return []
    return [
        json.loads(line)
        for raw_line in file_path.read_text(encoding="utf-8").splitlines()
        if (line := raw_line.strip())
    ]


def write_jsonl_atomic(rows: list[dict], path: str | Path) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = file_path.with_suffix(file_path.suffix + ".tmp")
    temporary.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    temporary.replace(file_path)
