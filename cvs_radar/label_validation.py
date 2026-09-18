"""Shared validation for model-written review labels.

The label importers deliberately validate instead of normalising bad model output.
That keeps a rewrite traceable to the exported source row and makes a malformed
chunk fail before it can update a committed cache.
"""

from __future__ import annotations

import csv
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from .grounding_verdicts import (
    GROUNDED,
    PROMPT_VERSION as GROUNDING_PROMPT_VERSION,
    UNGROUNDED,
    grounding_fingerprint,
)

MAX_REWRITE_LEN = 30
MIN_MEANINGFUL_OVERLAP = 0.25
MAX_REJECT_RATE = 0.02

_URL_RE = re.compile(r"(?:https?://|www\.)", re.IGNORECASE)
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_MEANINGFUL_CHAR_RE = re.compile(r"[\u3400-\u9fffA-Za-z0-9]")


@dataclass(frozen=True, slots=True)
class Rewrite:
    source_index: int
    text: str


class GroundingUncertain(Exception):
    """The overlap screen could not clear a rewrite and no model verdict exists yet.

    Deliberately not a ``ValueError``: this is not a malformed row, and treating it
    as one is what made honest Chinese paraphrases look like hallucinations. The
    caller must hold the row for adjudication rather than reject it.
    """

    def __init__(self, message: str, *, rewrite: str, source_text: str) -> None:
        super().__init__(message)
        self.rewrite = rewrite
        self.source_text = source_text


@dataclass(frozen=True, slots=True)
class RejectedRow:
    """One row an importer refused, kept out of the cache rather than repaired."""

    line_number: int
    fingerprint: str
    reason: str
    row: dict[str, str]


def enforce_reject_ceiling(
    rejected: list[RejectedRow],
    considered: int,
    *,
    max_reject_rate: float = MAX_REJECT_RATE,
) -> None:
    """Refuse the whole file when failures look systematic rather than isolated.

    Per-row quarantine exists so that one hallucinated rewrite cannot discard an
    entire labelling run. It must not become a way to quietly accept broken model
    output, so anything above the ceiling still refuses everything — the shape of
    the failure decides, not its existence.
    """

    if not rejected:
        return
    rate = len(rejected) / considered if considered else 1.0
    if rate > max_reject_rate:
        sample = "; ".join(f"row {item.line_number}: {item.reason}" for item in rejected[:5])
        raise ValueError(
            f"{len(rejected)}/{considered} rows failed validation ({rate:.1%} exceeds the "
            f"{max_reject_rate:.0%} ceiling); refusing the whole file. First failures: {sample}"
        )


@dataclass(frozen=True, slots=True)
class PendingGrounding:
    """One rewrite held out of the cache until a model has judged it."""

    line_number: int
    fingerprint: str
    field: str
    rewrite: str
    source_text: str
    product_name: str


PENDING_FIELDNAMES = (
    "fingerprint",
    "product_name",
    "field",
    "rewrite",
    "source_text",
    "verdict",
    "model",
    "prompt_version",
)


def write_pending_grounding(path: Path, pending: list[PendingGrounding]) -> None:
    """Write the adjudication queue: one row per rewrite the screen could not clear."""

    path.parent.mkdir(parents=True, exist_ok=True)
    seen: set[tuple[str, str]] = set()
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=PENDING_FIELDNAMES)
        writer.writeheader()
        for item in pending:
            key = (item.rewrite, item.source_text)
            if key in seen:
                continue
            seen.add(key)
            writer.writerow(
                {
                    "fingerprint": grounding_fingerprint(item.rewrite, item.source_text),
                    "product_name": item.product_name,
                    "field": item.field,
                    "rewrite": item.rewrite,
                    "source_text": item.source_text,
                    "verdict": "",
                    "model": "",
                    "prompt_version": GROUNDING_PROMPT_VERSION,
                }
            )


def write_rejects(
    path: Path, rejected: list[RejectedRow], fieldnames: tuple[str, ...]
) -> None:
    """Write quarantined rows verbatim, plus why each was refused.

    Nothing here is repaired. A quarantined row simply never reaches the cache, so
    the next export sees it as unlabelled again and it is re-labelled from scratch.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    columns = (*fieldnames, "reject_reason")
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for item in rejected:
            writer.writerow(
                {
                    **{field: item.row.get(field, "") for field in fieldnames},
                    "reject_reason": item.reason,
                }
            )


def numbered_candidates(raw: str | None, *, field: str) -> list[str]:
    """Parse a stable ``0. text`` candidate cell without repairing it."""

    raw_text = str(raw or "")
    lines = raw_text.splitlines()
    if any(not line.strip() for line in lines):
        raise ValueError(f"malformed {field}: blank candidate line")
    candidates: list[str] = []
    for expected, line in enumerate(lines):
        match = re.fullmatch(rf"\s*{expected}\.\s+(.+)\s*", line)
        if match is None:
            raise ValueError(f"malformed {field}: expected {expected}. text")
        candidates.append(match.group(1))
    return candidates


def parse_source_indices(raw: str | None, *, field: str, max_items: int = 3) -> tuple[int, ...]:
    text = str(raw or "")
    if not text.strip():
        return ()
    if text != text.strip() or any(part.strip() != part for part in text.split("|")):
        raise ValueError(f"{field} contains surrounding whitespace")
    parts = text.split("|")
    if len(parts) > max_items:
        raise ValueError(f"{field} has more than {max_items} source indices")
    try:
        indices = tuple(int(part) for part in parts)
    except ValueError as exc:
        raise ValueError(f"{field} contains a non-integer source index") from exc
    if len(set(indices)) != len(indices) or any(index < 0 for index in indices):
        raise ValueError(f"{field} contains duplicate or negative source indices")
    return indices


def parse_rewrites(raw: str | None, *, field: str, max_items: int = 3) -> tuple[Rewrite, ...]:
    """Parse the JSON rewrite list emitted by the comment labeller."""

    text = str(raw or "")
    if not text.strip():
        return ()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{field} is not valid JSON") from exc
    if not isinstance(payload, list):
        raise ValueError(f"{field} must be a JSON list")
    if len(payload) > max_items:
        raise ValueError(f"{field} has more than {max_items} rewrites")

    rewrites: list[Rewrite] = []
    seen: set[int] = set()
    for item in payload:
        if not isinstance(item, dict) or set(item) != {"source_index", "text"}:
            raise ValueError(f"{field} item must contain source_index and text only")
        index = item["source_index"]
        if isinstance(index, bool) or not isinstance(index, int) or index < 0:
            raise ValueError(f"{field} contains an invalid source_index")
        if index in seen:
            raise ValueError(f"{field} contains duplicate source_index {index}")
        seen.add(index)
        if not isinstance(item["text"], str):
            raise ValueError(f"{field} rewrite text must be a string")
        rewrites.append(Rewrite(index, item["text"]))
    return tuple(rewrites)


def validate_rewrite(
    rewrite: str,
    *,
    source_texts: list[str],
    source_indices: tuple[int, ...],
    other_products: str,
    field: str,
    verdicts: dict[str, str] | None = None,
) -> None:
    """Reject malformed or cross-product model text; screen the rest for grounding.

    Every check here except the last is decisive. The last one — distinct-character
    overlap with the cited source — is only a *screen*, because Chinese paraphrase
    defeats it in both directions: 「太貴了」 → 「價格偏高」 is a faithful rewrite
    sharing zero characters, while an invention can accidentally share several. On a
    real 824-row run it flagged roughly four honest rewrites for every hallucinated
    one, so it decides nothing on its own.

    Below the threshold the rewrite is handed to a cached model verdict instead: a
    recorded ``ungrounded`` rejects the row, a recorded ``grounded`` clears it, and
    no record at all raises :class:`GroundingUncertain` so the caller can hold the
    row for adjudication rather than discard a good rewrite.
    """

    if not source_indices:
        if rewrite:
            raise ValueError(f"{field}: rewrite is non-empty without source_indices")
        return
    if not rewrite:
        raise ValueError(f"{field}: source_indices require a non-empty rewrite")
    if len(rewrite) > MAX_REWRITE_LEN:
        raise ValueError(f"{field}: rewrite longer than {MAX_REWRITE_LEN} characters")
    if rewrite != rewrite.strip() or any(char in rewrite for char in "\r\n\t"):
        raise ValueError(f"{field}: rewrite is not a single normalised line")
    if _CONTROL_RE.search(rewrite) or "\ufffd" in rewrite:
        raise ValueError(f"{field}: rewrite contains control or replacement characters")
    if _contains_width_garbage(rewrite):
        raise ValueError(f"{field}: rewrite contains full-width/half-width garbage")
    if _URL_RE.search(rewrite):
        raise ValueError(f"{field}: rewrite contains a URL")

    rewrite_compact = re.sub(r"\s+", "", unicodedata.normalize("NFKC", rewrite))
    for product in (part.strip() for part in str(other_products or "").split("|")):
        product_compact = re.sub(r"\s+", "", unicodedata.normalize("NFKC", product))
        if product_compact and product_compact in rewrite_compact:
            raise ValueError(f"{field}: rewrite names other product {product!r}")

    if any(index >= len(source_texts) for index in source_indices):
        raise ValueError(f"{field}: source index outside candidate pool")

    rewrite_chars = _meaningful_chars(rewrite)
    if not rewrite_chars:
        raise ValueError(f"{field}: rewrite has no meaningful characters")
    source_chars = set().union(
        *(_meaningful_chars(source_texts[index]) for index in source_indices)
    )
    overlap = len(rewrite_chars & source_chars) / len(rewrite_chars)
    if overlap >= MIN_MEANINGFUL_OVERLAP:
        return

    source_text = cited_source_text(source_texts, source_indices)
    verdict = (verdicts or {}).get(
        grounding_fingerprint(rewrite, source_text)
    )
    if verdict == GROUNDED:
        return
    if verdict == UNGROUNDED:
        raise ValueError(
            f"{field}: model judged the rewrite ungrounded in its cited source "
            f"(overlap {overlap:.2f})"
        )
    raise GroundingUncertain(
        f"{field}: overlap {overlap:.2f} < {MIN_MEANINGFUL_OVERLAP:.2f}; "
        "awaiting a grounding verdict",
        rewrite=rewrite,
        source_text=source_text,
    )


def cited_source_text(source_texts: list[str], source_indices: tuple[int, ...]) -> str:
    """Render exactly the source a verdict is about, in cited order."""

    return "\n".join(source_texts[index] for index in source_indices)


def _meaningful_chars(text: str) -> set[str]:
    return {char for char in text if _MEANINGFUL_CHAR_RE.fullmatch(char)}


def _contains_width_garbage(text: str) -> bool:
    """Reject Latin/digit full-width and half-width forms, not normal CJK punctuation."""

    for char in text:
        if unicodedata.normalize("NFKC", char) == char:
            continue
        name = unicodedata.name(char, "")
        if "HALFWIDTH" in name or "FULLWIDTH LATIN" in name or "FULLWIDTH DIGIT" in name:
            return True
    return False
