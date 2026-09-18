#!/usr/bin/env python3
"""Validate and merge LLM-labelled product categories into the fingerprint cache."""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cvs_radar.product_categories import (  # noqa: E402
    CATEGORIES,
    FIELDNAMES,
    PRODUCT_CATEGORY_LABELS_PATH,
    product_category_fingerprint,
)

DEFAULT_LABELS_PATH = ROOT / PRODUCT_CATEGORY_LABELS_PATH

IMMUTABLE_FIELDS = ("brand", "product_name", "prompt_version")


def _read_rows(path: Path) -> list[dict[str, str]]:
    with open(path, encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _read_existing(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    existing: dict[str, dict[str, str]] = {}
    for row in _read_rows(path):
        fingerprint = str(row.get("fingerprint") or "").strip().lower()
        if not fingerprint:
            continue
        existing[fingerprint] = {field: str(row.get(field) or "").strip() for field in FIELDNAMES}
    return existing


def _recompute(row: dict[str, str]) -> str:
    return product_category_fingerprint(
        row.get("brand") or "",
        row.get("product_name") or "",
        prompt_version=row.get("prompt_version") or "",
    )


def import_labels(
    labeled_path: Path,
    source_path: Path,
    labels_path: Path = DEFAULT_LABELS_PATH,
    *,
    replace: bool = False,
    model_tag: str = "",
) -> tuple[int, int, int]:
    """Merge completed rows and return (added, replaced, skipped_incomplete).

    The source file is the delta the labeller was given. Checking every labeled
    row back against it is what stops a run from inventing products, renaming
    one mid-flight, or quietly dropping the rows it found hard.
    """
    existing = _read_existing(labels_path)
    added = replaced = skipped = 0

    source_by_fingerprint: dict[str, dict[str, str]] = {}
    for line_number, row in enumerate(_read_rows(source_path), start=2):
        fingerprint = str(row.get("fingerprint") or "").strip().lower()
        if fingerprint != _recompute(row):
            raise ValueError(f"source row {line_number}: fingerprint does not match inputs")
        if fingerprint in source_by_fingerprint:
            raise ValueError(f"source row {line_number}: duplicate fingerprint")
        source_by_fingerprint[fingerprint] = row

    labeled_rows = _read_rows(labeled_path)
    seen: set[str] = set()
    for line_number, row in enumerate(labeled_rows, start=2):
        fingerprint = str(row.get("fingerprint") or "").strip().lower()
        source = source_by_fingerprint.get(fingerprint)
        if source is None:
            raise ValueError(f"row {line_number}: unknown fingerprint")
        for field in IMMUTABLE_FIELDS:
            if str(row.get(field) or "").strip() != str(source.get(field) or "").strip():
                raise ValueError(f"row {line_number}: immutable field {field} changed")
        if fingerprint != _recompute(row):
            raise ValueError(f"row {line_number}: fingerprint does not match inputs")
        if fingerprint in seen:
            raise ValueError(f"row {line_number}: duplicate fingerprint")
        seen.add(fingerprint)

    dropped = set(source_by_fingerprint) - seen
    if dropped:
        raise ValueError(f"labeled file dropped {len(dropped)} source fingerprint(s)")

    for line_number, row in enumerate(labeled_rows, start=2):
        fingerprint = str(row.get("fingerprint") or "").strip().lower()
        category = str(row.get("category") or "").strip()
        model = str(row.get("model") or "").strip() or model_tag
        if not category and not str(row.get("model") or "").strip():
            skipped += 1
            continue
        if not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
            raise ValueError(f"row {line_number}: invalid fingerprint")
        if category not in CATEGORIES:
            raise ValueError(f"row {line_number}: unknown category {category!r}")

        output = {
            "fingerprint": fingerprint,
            "brand": str(row.get("brand") or "").strip(),
            "product_name": str(row.get("product_name") or "").strip(),
            "rule_guess": str(row.get("rule_guess") or "").strip(),
            "category": category,
            "model": model,
            "prompt_version": str(row.get("prompt_version") or "").strip(),
        }
        if fingerprint in existing:
            if not replace:
                continue
            if existing[fingerprint] != output:
                replaced += 1
        else:
            added += 1
        existing[fingerprint] = output

    rows = sorted(existing.values(), key=lambda item: item["fingerprint"])
    labels_path.parent.mkdir(parents=True, exist_ok=True)
    # BOM + CRLF, matching the four label caches already in data/labels/.
    with open(labels_path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES, lineterminator="\r\n")
        writer.writeheader()
        writer.writerows(rows)
    return added, replaced, skipped


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("labeled", type=Path, help="CSV produced by the labelling run")
    parser.add_argument("--source", type=Path, required=True, help="the delta given to it")
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS_PATH)
    parser.add_argument("--replace", action="store_true", help="overwrite existing labels")
    parser.add_argument("--model-tag", default="", help="model to record when a row omits one")
    args = parser.parse_args()

    added, replaced, skipped = import_labels(
        args.labeled,
        args.source,
        args.labels,
        replace=args.replace,
        model_tag=args.model_tag,
    )
    print(f"added {added}, replaced {replaced}, skipped {skipped} -> {args.labels}")


if __name__ == "__main__":
    main()
