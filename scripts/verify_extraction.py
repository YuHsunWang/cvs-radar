#!/usr/bin/env python3
"""Audit product extraction against stored CVS Radar posts."""

from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cvs_radar.scoring import extract_products_and_prices
from cvs_radar.store import DEFAULT_STORE_PATH, load_posts


OUTPUT_PATH = ROOT / "data" / "labels" / "extraction_audit.csv"
CSV_COLUMNS = [
    "post_id",
    "brand",
    "raw_product_name",
    "extracted_name",
    "extracted_price",
    "status",
]


def status_for(name: str, price: int | None) -> str:
    if not name:
        return "empty"
    if price is not None and 1 <= price <= 400:
        return "ok"
    return "garbage"


def audit_rows() -> list[dict[str, str]]:
    posts = load_posts(DEFAULT_STORE_PATH)
    rows: list[dict[str, str]] = []
    for post in posts:
        raw_name = post.product_name or ""
        preview = raw_name.replace("\n", "\\n")[:80]
        items = extract_products_and_prices(raw_name, post.brand)
        if not items:
            items = [("", None)]
        for name, price in items:
            rows.append(
                {
                    "post_id": post.id,
                    "brand": post.brand,
                    "raw_product_name": preview,
                    "extracted_name": name,
                    "extracted_price": "" if price is None else str(price),
                    "status": status_for(name, price),
                }
            )
    return rows


def write_audit_csv(rows: list[dict[str, str]], path: Path = OUTPUT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def print_summary(rows: list[dict[str, str]]) -> None:
    counts = {"ok": 0, "empty": 0, "garbage": 0}
    for row in rows:
        counts[row["status"]] += 1
    print(
        "Summary: "
        f"total={len(rows)}, "
        f"ok={counts['ok']}, "
        f"empty={counts['empty']}, "
        f"garbage={counts['garbage']}"
    )


def main() -> int:
    store_path = ROOT / DEFAULT_STORE_PATH
    if not store_path.exists():
        print(f"No posts found at {DEFAULT_STORE_PATH}; skipping extraction audit.")
        return 0

    rows = audit_rows()
    write_audit_csv(rows)
    print(f"Wrote {len(rows)} rows to {OUTPUT_PATH.relative_to(ROOT)}")
    print_summary(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
