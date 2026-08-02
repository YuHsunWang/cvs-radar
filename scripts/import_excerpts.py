#!/usr/bin/env python3
"""Validate and merge LLM-chosen excerpts into the fingerprint cache."""

from __future__ import annotations

import argparse
import csv
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cvs_radar.excerpt_labels import (  # noqa: E402
    EXCERPT_LABELS_PATH,
    FIELDNAMES,
    PROMPT_VERSION,
    excerpt_fingerprint_v2,
)

DEFAULT_LABELS_PATH = ROOT / EXCERPT_LABELS_PATH

MAX_EXCERPT_LEN = 90


def _read_existing(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8-sig", newline="") as handle:
        return {
            str(row.get("fingerprint") or "").strip().lower(): {
                field: str(row.get(field) or "").strip() for field in FIELDNAMES
            }
            for row in csv.DictReader(handle)
            if str(row.get("fingerprint") or "").strip()
        }


def _normalize(text: str) -> str:
    s = unicodedata.normalize("NFKC", str(text or ""))
    s = s.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    return re.sub(r"\s+", " ", s).strip()


def import_labels(
    labeled_path: Path,
    source_path: Path,
    labels_path: Path = DEFAULT_LABELS_PATH,
    *,
    replace: bool = False,
    model_tag: str = "",
) -> tuple[int, int, int]:
    """Merge completed rows and return (added, replaced, skipped_incomplete).

    A blank excerpt is a verdict ("this post says nothing usable about this
    product"), so it is stored. Only a row where nothing at all was filled in
    counts as incomplete.
    """
    existing = _read_existing(labels_path)
    added = replaced = skipped = 0

    with open(source_path, encoding="utf-8-sig", newline="") as handle:
        source_rows = list(csv.DictReader(handle))
    source_by_fingerprint: dict[str, dict[str, str]] = {}
    immutable_fields = (
        "post_id",
        "brand",
        "product_name",
        "other_products",
        "review_text",
        "prompt_version",
    )
    for line_number, row in enumerate(source_rows, start=2):
        fingerprint = str(row.get("fingerprint") or "").strip().lower()
        recomputed = excerpt_fingerprint_v2(
            row.get("post_id") or "",
            row.get("product_name") or "",
            row.get("review_text") or "",
            brand=row.get("brand") or "",
            other_products=row.get("other_products") or "",
            prompt_version=row.get("prompt_version") or "",
        )
        if fingerprint != recomputed:
            raise ValueError(f"source row {line_number}: fingerprint does not match inputs")
        if fingerprint in source_by_fingerprint:
            raise ValueError(f"source row {line_number}: duplicate fingerprint")
        source_by_fingerprint[fingerprint] = row

    with open(labeled_path, encoding="utf-8-sig", newline="") as handle:
        labeled_rows = list(csv.DictReader(handle))
    seen_fingerprints: set[str] = set()
    for line_number, row in enumerate(labeled_rows, start=2):
        fingerprint = str(row.get("fingerprint") or "").strip().lower()
        source = source_by_fingerprint.get(fingerprint)
        if source is None:
            raise ValueError(f"row {line_number}: unknown fingerprint")
        if fingerprint in seen_fingerprints:
            raise ValueError(f"row {line_number}: duplicate fingerprint")
        seen_fingerprints.add(fingerprint)
        for field in immutable_fields:
            if str(row.get(field) or "") != str(source.get(field) or ""):
                raise ValueError(f"row {line_number}: immutable field {field} changed")
        recomputed = excerpt_fingerprint_v2(
            row.get("post_id") or "",
            row.get("product_name") or "",
            row.get("review_text") or "",
            brand=row.get("brand") or "",
            other_products=row.get("other_products") or "",
            prompt_version=row.get("prompt_version") or "",
        )
        if fingerprint != recomputed:
            raise ValueError(f"row {line_number}: fingerprint does not match inputs")

    missing = set(source_by_fingerprint) - seen_fingerprints
    if missing:
        raise ValueError(f"labeled file dropped {len(missing)} source fingerprint(s)")

    for line_number, row in enumerate(labeled_rows, start=2):
        fingerprint = str(row.get("fingerprint") or "").strip().lower()
        excerpt = _normalize(row.get("excerpt"))
        model = str(row.get("model") or "").strip()
        if not excerpt and not model:
            skipped += 1
            continue
        if not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
            raise ValueError(f"row {line_number}: invalid fingerprint")
        if len(excerpt) > MAX_EXCERPT_LEN:
            raise ValueError(
                f"row {line_number}: excerpt longer than {MAX_EXCERPT_LEN} characters"
            )
        if "http" in excerpt.casefold():
            raise ValueError(f"row {line_number}: excerpt contains a URL")
        review_text = _normalize(row.get("review_text"))
        if excerpt and excerpt not in review_text:
            raise ValueError(
                f"row {line_number}: excerpt is not an exact slice of review_text"
            )

        output = {
            "fingerprint": fingerprint,
            "post_id": str(row.get("post_id") or "").strip(),
            "brand": str(row.get("brand") or "").strip(),
            "product_name": str(row.get("product_name") or "").strip(),
            "excerpt": excerpt,
            "model": model_tag or model or "subscription-llm",
            "prompt_version": str(row.get("prompt_version") or PROMPT_VERSION).strip(),
        }
        if fingerprint in existing:
            if not replace:
                continue
            existing[fingerprint] = output
            replaced += 1
        else:
            existing[fingerprint] = output
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
    parser.add_argument("labeled", type=Path)
    parser.add_argument("--source", type=Path, required=True, help="original exported CSV")
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS_PATH)
    parser.add_argument(
        "--model-tag",
        default="",
        help="record this model name instead of the one the labeller wrote "
             "(its value still marks which rows it worked on)",
    )
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()

    added, replaced, skipped = import_labels(
        args.labeled,
        args.source,
        args.labels,
        replace=args.replace,
        model_tag=args.model_tag,
    )
    print(
        f"imported excerpts: {added} added, {replaced} replaced, "
        f"{skipped} skipped (0 errors)"
    )


if __name__ == "__main__":
    main()
