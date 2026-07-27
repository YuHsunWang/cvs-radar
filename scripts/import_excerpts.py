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
)

DEFAULT_LABELS_PATH = ROOT / EXCERPT_LABELS_PATH

MAX_EXCERPT_LEN = 200


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
    labels_path: Path = DEFAULT_LABELS_PATH,
    *,
    replace: bool = False,
) -> tuple[int, int, int]:
    """Merge completed rows and return (added, replaced, skipped_incomplete).

    A blank excerpt is a verdict ("this post says nothing usable about this
    product"), so it is stored. Only a row where nothing at all was filled in
    counts as incomplete.
    """
    existing = _read_existing(labels_path)
    added = replaced = skipped = 0

    with open(labeled_path, encoding="utf-8-sig", newline="") as handle:
        for line_number, row in enumerate(csv.DictReader(handle), start=2):
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

            output = {
                "fingerprint": fingerprint,
                "post_id": str(row.get("post_id") or "").strip(),
                "brand": str(row.get("brand") or "").strip(),
                "product_name": str(row.get("product_name") or "").strip(),
                "excerpt": excerpt,
                "model": model or "subscription-llm",
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
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS_PATH)
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()

    added, replaced, skipped = import_labels(
        args.labeled, args.labels, replace=args.replace
    )
    print(
        f"imported excerpts: {added} added, {replaced} replaced, "
        f"{skipped} skipped (0 errors)"
    )


if __name__ == "__main__":
    main()
