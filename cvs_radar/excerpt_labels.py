"""LLM-chosen review excerpts, cached by fingerprint.

Picking the sentence a shopper actually benefits from — and, in a post covering
several products, picking only the sentences about *this* one — is judgement, not
pattern matching. Keyword scoring kept choosing promo lines, contentless praise, or
commentary about the other product in the thread.

So the choice is made once per (post, product) pair and cached, mirroring
`sentiment.py` and `product_labels.py`. The label stores only the chosen excerpt,
never the post body: the body already lives in the local store, and a committed
cache should stay small and reviewable.

Downstream stays deterministic — a rebuild, and CI, read labels rather than
re-deciding. The scoring selector remains the fallback for unlabelled pairs.
"""

from __future__ import annotations

import csv
import hashlib
import re
import unicodedata
from pathlib import Path

EXCERPT_LABELS_PATH = "data/labels/excerpt_labels.csv"

PROMPT_VERSION = "excerpt-v1"

FIELDNAMES = (
    "fingerprint",
    "post_id",
    "brand",
    "product_name",
    "excerpt",
    "model",
    "prompt_version",
)


def _normalize(text: str) -> str:
    s = unicodedata.normalize("NFKC", str(text or ""))
    s = s.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    return re.sub(r"\s+", " ", s).strip()


def excerpt_fingerprint(post_id: str, product_name: str, review_text: str) -> str:
    """Identify one product's excerpt within one post.

    The review text is part of the key so that a backfill which finally recovers a
    post's body invalidates the old label instead of silently keeping an excerpt
    chosen from nothing.
    """
    payload = "\x1f".join(
        (
            _normalize(post_id),
            _normalize(product_name),
            _normalize(review_text),
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_excerpt_labels(
    path: str | Path = EXCERPT_LABELS_PATH,
) -> dict[str, str]:
    """Load chosen excerpts keyed by (post, product) fingerprint.

    A blank excerpt is a real verdict — "this post says nothing usable about this
    product" — and is kept, so the caller can tell it apart from an unlabelled pair.
    """
    file_path = Path(path)
    if not file_path.exists():
        return {}

    labels: dict[str, str] = {}
    with open(file_path, encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            fingerprint = str(row.get("fingerprint") or "").strip().lower()
            if not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
                continue
            labels[fingerprint] = _normalize(row.get("excerpt") or "")
    return labels
