"""Model-written representative comments, cached by candidate-pool fingerprint.

The model receives one mechanically cleaned pool of comments and one pool of
author sentences. It decides whether an item is a positive or negative product
review and writes a short Traditional-Chinese rewrite. The cache stores source
indices with each rewrite so the answer remains auditable without displaying a
verbatim comment to shoppers.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from .label_validation import Rewrite, parse_rewrites
from .models import Post

COMMENT_PICKS_PATH = "data/labels/comment_picks.csv"

PROMPT_VERSION = "comment-picks-v2-rewrite"

FIELDNAMES = (
    "fingerprint",
    "brand",
    "product_name",
    "positive_rewrites",
    "negative_rewrites",
    "positive_body_rewrites",
    "negative_body_rewrites",
    "model",
    "prompt_version",
)


@dataclass(frozen=True, slots=True)
class CommentPicks:
    positive: tuple[Rewrite, ...]
    negative: tuple[Rewrite, ...]
    positive_body: tuple[Rewrite, ...]
    negative_body: tuple[Rewrite, ...]


def _normalize(text: str) -> str:
    s = unicodedata.normalize("NFKC", str(text or ""))
    s = s.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    return re.sub(r"\s+", " ", s).strip()


def comment_picks_fingerprint(
    brand: str,
    product_name: str,
    comments: list[str],
    body: list[str],
    *,
    other_products: str = "",
    prompt_version: str = PROMPT_VERSION,
) -> str:
    """Fingerprint exactly the two pools and context shown to the labeller."""

    lists = "\x1d".join(
        "\x1e".join(_normalize(item) for item in candidates)
        for candidates in (comments, body)
    )
    payload = "\x1f".join(
        (
            _normalize(brand),
            _normalize(product_name),
            lists,
            _normalize(other_products),
            str(prompt_version or ""),
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def comment_picks_fingerprint_v2(
    brand: str,
    product_name: str,
    comments: list[str],
    body: list[str],
    *,
    other_products: str = "",
    prompt_version: str = PROMPT_VERSION,
) -> str:
    """Named v2 entry point used by exporters and scoring."""

    return comment_picks_fingerprint(
        brand,
        product_name,
        comments,
        body,
        other_products=other_products,
        prompt_version=prompt_version,
    )


def other_products_for_group(posts: Iterable[Post]) -> str:
    """Render the thread-mates of a product group deterministically."""

    mates: list[str] = []
    for post in posts:
        for name in post.sibling_products:
            if name not in mates:
                mates.append(name)
    return " | ".join(mates)


def _parse_cached_rewrites(raw: str | None, field: str) -> tuple[Rewrite, ...] | None:
    try:
        return parse_rewrites(raw, field=field)
    except ValueError:
        return None


def load_comment_picks(
    path: str | Path = COMMENT_PICKS_PATH,
) -> dict[str, CommentPicks]:
    """Load only the current rewrite schema and prompt version.

    Old v1 rows deliberately return no labels: prompt-version bumps are the cache
    invalidation mechanism, so the next export re-labels every product.
    """

    file_path = Path(path)
    if not file_path.exists():
        return {}

    labels: dict[str, CommentPicks] = {}
    with open(file_path, encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or any(field not in reader.fieldnames for field in FIELDNAMES):
            return {}
        for row in reader:
            fingerprint = str(row.get("fingerprint") or "").strip().lower()
            if not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
                continue
            if str(row.get("prompt_version") or "").strip() != PROMPT_VERSION:
                continue
            parsed = [
                _parse_cached_rewrites(row.get(field), field)
                for field in (
                    "positive_rewrites",
                    "negative_rewrites",
                    "positive_body_rewrites",
                    "negative_body_rewrites",
                )
            ]
            if any(item is None for item in parsed):
                continue
            labels[fingerprint] = CommentPicks(
                positive=parsed[0] or (),
                negative=parsed[1] or (),
                positive_body=parsed[2] or (),
                negative_body=parsed[3] or (),
            )
    return labels


def rewrites_json(rewrites: Iterable[Rewrite]) -> str:
    """Serialise cache rows in the same shape the importer validates."""

    return json.dumps(
        [{"source_index": item.source_index, "text": item.text} for item in rewrites],
        ensure_ascii=False,
        separators=(",", ":"),
    )
