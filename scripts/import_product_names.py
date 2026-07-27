#!/usr/bin/env python3
"""Validate and merge LLM-labelled product names into the fingerprint cache."""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cvs_radar.product_labels import (  # noqa: E402
    FIELDNAMES,
    PRODUCT_NAME_LABELS_PATH,
    PROMPT_VERSION,
)

DEFAULT_LABELS_PATH = ROOT / PRODUCT_NAME_LABELS_PATH

MIN_PRICE = 0
MAX_PRICE = 10000


def _read_existing(path: Path) -> dict[tuple[str, int], dict[str, str]]:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8-sig", newline="") as handle:
        existing: dict[tuple[str, int], dict[str, str]] = {}
        for row in csv.DictReader(handle):
            fingerprint = str(row.get("fingerprint") or "").strip().lower()
            if not fingerprint:
                continue
            try:
                index = int(str(row.get("item_index") or "0").strip())
            except ValueError:
                continue
            existing[(fingerprint, index)] = {
                field: str(row.get(field) or "").strip() for field in FIELDNAMES
            }
        return existing


def import_labels(
    labeled_path: Path,
    labels_path: Path = DEFAULT_LABELS_PATH,
    *,
    replace: bool = False,
) -> tuple[int, int, int]:
    """Merge completed rows and return (added, replaced, skipped_incomplete).

    A row with a blank product_name is a real verdict — "this field carries no
    usable name" — so it is stored, not skipped. Only a row where the labeller
    filled in nothing at all counts as incomplete.
    """
    existing = _read_existing(labels_path)
    added = replaced = skipped = 0

    with open(labeled_path, encoding="utf-8-sig", newline="") as handle:
        for line_number, row in enumerate(csv.DictReader(handle), start=2):
            fingerprint = str(row.get("fingerprint") or "").strip().lower()
            name = str(row.get("product_name") or "").strip()
            price_raw = str(row.get("price") or "").strip()
            model = str(row.get("model") or "").strip()
            if not name and not price_raw and not model:
                skipped += 1
                continue
            if not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
                raise ValueError(f"row {line_number}: invalid fingerprint")

            try:
                index = int(str(row.get("item_index") or "0").strip())
            except ValueError as exc:
                raise ValueError(f"row {line_number}: invalid item_index") from exc
            if index < 0:
                raise ValueError(f"row {line_number}: item_index must not be negative")

            price = ""
            if price_raw:
                try:
                    parsed = int(float(price_raw))
                except ValueError as exc:
                    raise ValueError(f"row {line_number}: invalid price") from exc
                if not MIN_PRICE <= parsed <= MAX_PRICE:
                    raise ValueError(f"row {line_number}: price outside range")
                price = str(parsed)
            if price and not name:
                raise ValueError(f"row {line_number}: price given without a product name")

            output = {
                "fingerprint": fingerprint,
                "item_index": str(index),
                "brand": str(row.get("brand") or "").strip(),
                "raw_name": str(row.get("raw_name") or "").strip(),
                "product_name": name,
                "price": price,
                "model": model or "subscription-llm",
                "prompt_version": str(row.get("prompt_version") or PROMPT_VERSION).strip(),
            }
            key = (fingerprint, index)
            if key in existing:
                if not replace:
                    continue
                existing[key] = output
                replaced += 1
            else:
                existing[key] = output
                added += 1

    labels_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = labels_path.with_suffix(labels_path.suffix + ".tmp")
    with open(temporary, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(existing[key] for key in sorted(existing))
    temporary.replace(labels_path)
    return added, replaced, skipped


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("labeled", type=Path, help="CSV produced by the labelling run")
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS_PATH)
    parser.add_argument("--replace", action="store_true", help="overwrite existing labels")
    args = parser.parse_args()

    added, replaced, skipped = import_labels(
        args.labeled, args.labels, replace=args.replace
    )
    print(
        f"imported product names: {added} added, {replaced} replaced, "
        f"{skipped} skipped (0 errors)"
    )


if __name__ == "__main__":
    main()
