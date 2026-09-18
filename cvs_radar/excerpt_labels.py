"""Model-written review summaries, cached by (post, product) fingerprint."""

from __future__ import annotations

import csv
import hashlib
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from .label_validation import parse_source_indices

EXCERPT_LABELS_PATH = "data/labels/excerpt_labels.csv"

PROMPT_VERSION = "excerpt-v2-rewrite"

FIELDNAMES = (
    "fingerprint",
    "post_id",
    "brand",
    "product_name",
    "source_indices",
    "rewrite",
    "model",
    "prompt_version",
)


@dataclass(frozen=True, slots=True)
class ExcerptLabel:
    source_indices: tuple[int, ...]
    rewrite: str


def _normalize(text: str) -> str:
    s = unicodedata.normalize("NFKC", str(text or ""))
    s = s.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    return re.sub(r"\s+", " ", s).strip()


def excerpt_fingerprint(post_id: str, product_name: str, review_text: str) -> str:
    """Legacy fingerprint retained for historical callers, never used for lookup."""

    payload = "\x1f".join(
        (_normalize(post_id), _normalize(product_name), _normalize(review_text))
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def format_other_products(names: Iterable[str]) -> str:
    """Render a sibling-product list the way the exported row shows it."""

    return " | ".join(names)


def excerpt_fingerprint_v2(
    post_id: str,
    product_name: str,
    review_text: str,
    *,
    brand: str = "",
    other_products: str = "",
    candidate_sentences: Iterable[str] = (),
    prompt_version: str = PROMPT_VERSION,
) -> str:
    """Fingerprint everything the rewrite model can read for this pair."""

    candidates = "\x1e".join(_normalize(item) for item in candidate_sentences)
    payload = "\x1f".join(
        (
            _normalize(post_id),
            _normalize(product_name),
            _normalize(review_text),
            _normalize(brand),
            _normalize(other_products),
            candidates,
            str(prompt_version or ""),
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_excerpt_labels(
    path: str | Path = EXCERPT_LABELS_PATH,
) -> dict[str, ExcerptLabel]:
    """Load only current rewrite rows; old verbatim rows are cache misses."""

    file_path = Path(path)
    if not file_path.exists():
        return {}

    labels: dict[str, ExcerptLabel] = {}
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
            try:
                source_indices = parse_source_indices(
                    row.get("source_indices"), field="source_indices"
                )
            except ValueError:
                continue
            labels[fingerprint] = ExcerptLabel(
                source_indices=source_indices,
                rewrite=str(row.get("rewrite") or ""),
            )
    return labels
