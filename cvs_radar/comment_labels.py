"""LLM-picked representative comments, cached by fingerprint.

Choosing the comments a shopper actually benefits from is judgement, not a
sentiment-magnitude calculation. The old ranking kept promoting contentless
verdicts ("好吃", "推") over comments that explain why a product is worth buying.

So the choice is made once per product's candidate pool and cached, mirroring
`excerpt_labels.py` and `product_labels.py`. The cache stores candidate indices,
never comment text: candidates already live in the local post store, and putting
them in the fingerprint means a changed crawl invalidates a stale pick.

Downstream stays deterministic — a rebuild, and CI, read labels rather than
re-deciding. The sentiment ranking remains the fallback for unlabelled products.
"""

from __future__ import annotations

import csv
import hashlib
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

COMMENT_PICKS_PATH = "data/labels/comment_picks.csv"

PROMPT_VERSION = "comment-picks-v1"

FIELDNAMES = (
    "fingerprint",
    "brand",
    "product_name",
    "positive_picks",
    "negative_picks",
    "positive_body_picks",
    "negative_body_picks",
    "model",
    "prompt_version",
)


@dataclass(frozen=True, slots=True)
class CommentPicks:
    positive: tuple[int, ...]
    negative: tuple[int, ...]
    positive_body: tuple[int, ...]
    negative_body: tuple[int, ...]


def _normalize(text: str) -> str:
    s = unicodedata.normalize("NFKC", str(text or ""))
    s = s.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    return re.sub(r"\s+", " ", s).strip()


def comment_picks_fingerprint(
    brand: str,
    product_name: str,
    positive: list[str],
    negative: list[str],
    body: list[str],
) -> str:
    """Identify one product's representative-comment candidate pool.

    Candidate text is part of the key so that a re-crawl which changes the pool
    invalidates old indices instead of silently applying them to new comments.
    """
    lists = "\x1d".join(
        "\x1e".join(_normalize(item) for item in candidates)
        for candidates in (positive, negative, body)
    )
    payload = "\x1f".join((_normalize(brand), _normalize(product_name), lists))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _parse_picks(raw: str | None) -> tuple[int, ...]:
    picks: list[int] = []
    for item in str(raw or "").split("|"):
        item = item.strip()
        if not item:
            continue
        try:
            picks.append(int(item))
        except ValueError:
            continue
    return tuple(picks)


def load_comment_picks(
    path: str | Path = COMMENT_PICKS_PATH,
) -> dict[str, CommentPicks]:
    """Load representative-comment picks keyed by product fingerprint.

    A blank pick cell is a real verdict — "nothing in this polarity is worth
    showing" — and is kept, so the caller can tell it apart from an unlabelled
    product.
    """
    file_path = Path(path)
    if not file_path.exists():
        return {}

    labels: dict[str, CommentPicks] = {}
    with open(file_path, encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            fingerprint = str(row.get("fingerprint") or "").strip().lower()
            if not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
                continue
            labels[fingerprint] = CommentPicks(
                positive=_parse_picks(row.get("positive_picks")),
                negative=_parse_picks(row.get("negative_picks")),
                positive_body=_parse_picks(row.get("positive_body_picks")),
                negative_body=_parse_picks(row.get("negative_body_picks")),
            )
    return labels
