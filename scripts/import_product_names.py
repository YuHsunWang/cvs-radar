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
    product_name_fingerprint_v2,
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
    source_path: Path,
    labels_path: Path = DEFAULT_LABELS_PATH,
    *,
    replace: bool = False,
    model_tag: str = "",
) -> tuple[int, int, int]:
    """Merge completed rows and return (added, replaced, skipped_incomplete).

    A row with a blank product_name is a real verdict — "this field carries no
    usable name" — so it is stored, not skipped. Only a row where the labeller
    filled in nothing at all counts as incomplete.
    """
    existing = _read_existing(labels_path)
    added = replaced = skipped = 0

    with open(source_path, encoding="utf-8-sig", newline="") as handle:
        source_rows = list(csv.DictReader(handle))
    source_by_fingerprint: dict[str, dict[str, str]] = {}
    immutable_fields = ("brand", "title", "raw_name", "rule_guess", "prompt_version")
    for line_number, row in enumerate(source_rows, start=2):
        fingerprint = str(row.get("fingerprint") or "").strip().lower()
        recomputed = product_name_fingerprint_v2(
            row.get("brand") or "",
            row.get("title") or "",
            row.get("raw_name") or "",
            rule_guess=row.get("rule_guess") or "",
            prompt_version=row.get("prompt_version") or "",
        )
        if fingerprint != recomputed:
            raise ValueError(f"source row {line_number}: fingerprint does not match inputs")
        if fingerprint in source_by_fingerprint:
            raise ValueError(f"source row {line_number}: duplicate fingerprint")
        source_by_fingerprint[fingerprint] = row

    with open(labeled_path, encoding="utf-8-sig", newline="") as handle:
        labeled_rows = list(csv.DictReader(handle))

    grouped_indexes: dict[str, list[int]] = {}
    seen_keys: set[tuple[str, int]] = set()
    for line_number, row in enumerate(labeled_rows, start=2):
        fingerprint = str(row.get("fingerprint") or "").strip().lower()
        source = source_by_fingerprint.get(fingerprint)
        if source is None:
            raise ValueError(f"row {line_number}: unknown fingerprint")
        for field in immutable_fields:
            if str(row.get(field) or "") != str(source.get(field) or ""):
                raise ValueError(f"row {line_number}: immutable field {field} changed")
        recomputed = product_name_fingerprint_v2(
            row.get("brand") or "",
            row.get("title") or "",
            row.get("raw_name") or "",
            rule_guess=row.get("rule_guess") or "",
            prompt_version=row.get("prompt_version") or "",
        )
        if fingerprint != recomputed:
            raise ValueError(f"row {line_number}: fingerprint does not match inputs")
        try:
            index = int(str(row.get("item_index") or "0").strip())
        except ValueError as exc:
            raise ValueError(f"row {line_number}: invalid item_index") from exc
        key = (fingerprint, index)
        if key in seen_keys:
            raise ValueError(f"row {line_number}: duplicate fingerprint/item_index")
        seen_keys.add(key)
        grouped_indexes.setdefault(fingerprint, []).append(index)

    missing = set(source_by_fingerprint) - set(grouped_indexes)
    if missing:
        raise ValueError(f"labeled file dropped {len(missing)} source fingerprint(s)")
    for fingerprint, indexes in grouped_indexes.items():
        if sorted(indexes) != list(range(len(indexes))):
            raise ValueError(f"{fingerprint}: item_index must start at zero with no gaps")

    for line_number, row in enumerate(labeled_rows, start=2):
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
            "title": str(row.get("title") or "").strip(),
            "raw_name": str(row.get("raw_name") or "").strip(),
            "product_name": name,
            "price": price,
            "model": model_tag or model or "subscription-llm",
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
    parser.add_argument("--source", type=Path, required=True, help="original exported CSV")
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS_PATH)
    parser.add_argument(
        "--model-tag",
        default="",
        help="record this model name instead of the one the labeller wrote "
             "(its value still marks which rows it worked on)",
    )
    parser.add_argument("--replace", action="store_true", help="overwrite existing labels")
    args = parser.parse_args()

    added, replaced, skipped = import_labels(
        args.labeled,
        args.source,
        args.labels,
        replace=args.replace,
        model_tag=args.model_tag,
    )
    print(
        f"imported product names: {added} added, {replaced} replaced, "
        f"{skipped} skipped (0 errors)"
    )


if __name__ == "__main__":
    main()
