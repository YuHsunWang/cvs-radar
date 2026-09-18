#!/usr/bin/env python3
"""Validate and merge model grounding verdicts into the committed verdict cache."""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cvs_radar.grounding_verdicts import (  # noqa: E402
    FIELDNAMES as CACHE_FIELDNAMES,
    GROUNDING_VERDICTS_PATH,
    PROMPT_VERSION,
    VERDICTS,
    grounding_fingerprint,
)
from cvs_radar.label_validation import PENDING_FIELDNAMES  # noqa: E402

DEFAULT_LABELS_PATH = ROOT / GROUNDING_VERDICTS_PATH
IMMUTABLE_FIELDS = ("fingerprint", "product_name", "field", "rewrite", "source_text")


def _read_rows(path: Path) -> list[dict[str, str]]:
    with open(path, encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != PENDING_FIELDNAMES:
            raise ValueError(
                f"{path}: unexpected columns; expected {','.join(PENDING_FIELDNAMES)}"
            )
        return list(reader)


def _read_existing(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != CACHE_FIELDNAMES:
            return {}
        return {
            str(row.get("fingerprint") or "").strip().lower(): {
                field: str(row.get(field) or "") for field in CACHE_FIELDNAMES
            }
            for row in reader
            if str(row.get("fingerprint") or "").strip()
        }


def _validate_row(row: dict[str, str], line_number: int) -> str:
    """A verdict is only meaningful for the exact pair the model was shown."""

    fingerprint = str(row.get("fingerprint") or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
        raise ValueError(f"row {line_number}: invalid fingerprint")
    if str(row.get("prompt_version") or "").strip() != PROMPT_VERSION:
        raise ValueError(f"row {line_number}: unexpected prompt_version")
    recomputed = grounding_fingerprint(
        str(row.get("rewrite") or ""), str(row.get("source_text") or "")
    )
    if fingerprint != recomputed:
        raise ValueError(f"row {line_number}: rewrite or source_text was modified")
    verdict = str(row.get("verdict") or "").strip()
    if verdict not in VERDICTS:
        raise ValueError(
            f"row {line_number}: verdict must be one of {'/'.join(VERDICTS)}, got {verdict!r}"
        )
    if not str(row.get("model") or "").strip():
        raise ValueError(f"row {line_number}: model is required")
    return fingerprint


def import_verdicts(
    labeled_path: Path,
    source_path: Path,
    labels_path: Path = DEFAULT_LABELS_PATH,
    *,
    model_tag: str = "",
) -> tuple[int, int]:
    """Refuse the whole file on any bad row; return ``(added, replaced)``.

    No per-row quarantine here, unlike the rewrite importers. This file is small,
    every row is a direct answer to a question we asked, and a malformed answer
    means the adjudication run itself went wrong.
    """

    source_rows = _read_rows(source_path)
    labeled_rows = _read_rows(labeled_path)
    if len(labeled_rows) != len(source_rows):
        raise ValueError(
            f"labeled row count {len(labeled_rows)} does not match source {len(source_rows)}"
        )
    for line_number, (source, labeled) in enumerate(
        zip(source_rows, labeled_rows, strict=True), start=2
    ):
        for field in IMMUTABLE_FIELDS:
            if labeled.get(field, "") != source.get(field, ""):
                raise ValueError(f"row {line_number}: immutable field {field} changed")

    existing = _read_existing(labels_path)
    added = replaced = 0
    for line_number, row in enumerate(labeled_rows, start=2):
        fingerprint = _validate_row(row, line_number)
        output = {
            "fingerprint": fingerprint,
            "rewrite": str(row.get("rewrite") or ""),
            "source_text": str(row.get("source_text") or ""),
            "verdict": str(row.get("verdict") or "").strip(),
            "model": model_tag or str(row.get("model") or "").strip(),
            "prompt_version": PROMPT_VERSION,
        }
        if fingerprint in existing:
            existing[fingerprint] = output
            replaced += 1
        else:
            existing[fingerprint] = output
            added += 1

    labels_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = labels_path.with_suffix(labels_path.suffix + ".tmp")
    with open(temporary, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CACHE_FIELDNAMES)
        writer.writeheader()
        writer.writerows(existing[key] for key in sorted(existing))
    temporary.replace(labels_path)
    return added, replaced


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("labeled", type=Path)
    parser.add_argument("--source", type=Path, required=True, help="pending CSV that was sent")
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS_PATH)
    parser.add_argument("--model-tag", default="")
    args = parser.parse_args()

    added, replaced = import_verdicts(
        args.labeled, args.source, args.labels, model_tag=args.model_tag
    )
    print(f"imported grounding verdicts: {added} added, {replaced} replaced")


if __name__ == "__main__":
    main()
