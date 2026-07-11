#!/usr/bin/env python3
"""Rebuild only review excerpts while preserving every scoring field."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cvs_radar.scoring import (
    _review_excerpt,
    group_products,
    normalize_product,
    preprocess_posts,
    representative_product_name,
)
from cvs_radar.store import DEFAULT_RESULTS_PATH, DEFAULT_STORE_PATH, load_posts


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild product review excerpts from stored posts")
    parser.add_argument("--posts", default=DEFAULT_STORE_PATH, help="Source posts JSONL")
    parser.add_argument("--results", default=DEFAULT_RESULTS_PATH, help="Results JSON to update")
    parser.add_argument("--dry-run", action="store_true", help="Validate and report changes without writing")
    args = parser.parse_args()

    posts = preprocess_posts(load_posts(args.posts))
    if not posts:
        parser.error(f"No posts found in {args.posts}")

    excerpts: dict[str, str] = {}
    for group in group_products(posts).values():
        product_name = representative_product_name(group)
        product_key = f"{group[0].brand}:{normalize_product(group[0].brand, product_name)}"
        excerpts[product_key] = _review_excerpt(group)

    results_path = Path(args.results)
    payload = json.loads(results_path.read_text(encoding="utf-8"))
    reports = payload.get("reports", [])
    result_keys = {report.get("product_key", "") for report in reports}
    missing = sorted(result_keys - excerpts.keys())
    extra = sorted(excerpts.keys() - result_keys)
    if missing or extra:
        raise RuntimeError(
            f"Product key mismatch: missing excerpts={len(missing)}, extra excerpts={len(extra)}"
        )

    changed = 0
    blank = 0
    for report in reports:
        excerpt = excerpts[report["product_key"]]
        changed += excerpt != report.get("review_excerpt", "")
        blank += not excerpt
        report["review_excerpt"] = excerpt

    if not args.dry_run:
        payload["generated_at"] = datetime.now().isoformat(sep=" ", timespec="seconds")
        results_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    mode = "Would update" if args.dry_run else "Updated"
    print(f"{mode} {changed}/{len(reports)} excerpts ({blank} without relevant author text)")


if __name__ == "__main__":
    main()
