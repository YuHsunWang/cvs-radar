"""Backfill missing author review text from stored PTT article URLs."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlparse

from .parser import parse_ptt_article


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

    for index, row in enumerate(result):
        if not is_backfill_candidate(row):
            continue
        if limit is not None and attempted >= limit:
            break
        attempted += 1
        url = str(row["url"])
        try:
            parsed = parse_ptt_article(fetch_html(url), url, str(row.get("board") or "CVS"))
        except Exception:
            continue
        if parsed is None or not parsed.review_text.strip():
            continue
        row["review_text"] = parsed.review_text
        updated += 1

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
