#!/usr/bin/env python3
"""Audit product category changes against stored CVS Radar posts."""

from __future__ import annotations

import csv
import sys
import unicodedata
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cvs_radar.config import PRODUCT_CATEGORIES
from cvs_radar.scoring import categorize_product
from cvs_radar.store import DEFAULT_STORE_PATH, load_posts


OUTPUT_PATH = ROOT / "data" / "labels" / "category_audit.csv"
ADDED_CATEGORY = "周邊"
ADDED_KEYWORDS: dict[str, set[str]] = {
    "冰品": {"檸檬繽球", "繽球"},
    "飲料": {"龜記", "微醉"},
    "便當": {"焗飯", "白醬洋芋", "洋芋"},
    "鹹食": {"招財堡", "好多蛋"},
}
CSV_COLUMNS = ["product_name", "old_category", "new_category"]


def old_product_categories() -> dict[str, list[str]]:
    """Approximate the category rules before this audit's keyword additions."""
    categories: dict[str, list[str]] = {}
    for category, keywords in PRODUCT_CATEGORIES.items():
        if category == ADDED_CATEGORY:
            continue
        added = ADDED_KEYWORDS.get(category, set())
        categories[category] = [keyword for keyword in keywords if keyword not in added]
    return categories


def categorize_with_categories(name: str, categories: Mapping[str, Sequence[str]]) -> str:
    text = unicodedata.normalize("NFKC", name or "").lower()
    for category, keywords in categories.items():
        for keyword in keywords:
            if keyword.lower() in text:
                return category
    return "其他"


def unique_product_names() -> list[str]:
    posts = load_posts(DEFAULT_STORE_PATH)
    seen: set[str] = set()
    names: list[str] = []
    for post in posts:
        name = " ".join(post.product_name.split())
        if not name or name in seen:
            continue
        seen.add(name)
        names.append(name)
    return names


def write_audit_csv(path: Path = OUTPUT_PATH) -> int:
    old_categories = old_product_categories()
    rows = [
        {
            "product_name": name,
            "old_category": categorize_with_categories(name, old_categories),
            "new_category": categorize_product(name),
        }
        for name in unique_product_names()
    ]

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def main() -> None:
    row_count = write_audit_csv()
    print(f"Wrote {row_count} rows to {OUTPUT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
