#!/usr/bin/env python3
"""Export raw 商品名稱 fields that have no LLM label yet, for a labelling run."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cvs_radar.product_labels import (  # noqa: E402
    PRODUCT_NAME_LABELS_PATH,
    PROMPT_VERSION,
    format_rule_guess,
    load_product_name_labels,
    product_name_fingerprint,
    product_name_fingerprint_v2,
)
from cvs_radar.store import load_posts  # noqa: E402

DEFAULT_POSTS_PATH = ROOT / "data" / "posts.jsonl"
DEFAULT_OUT_PATH = ROOT / "artifacts" / "unlabeled-product-names.csv"

FIELDNAMES = (
    "fingerprint",
    "item_index",
    "brand",
    "title",
    "raw_name",
    "rule_guess",
    "product_name",
    "price",
    "model",
    "prompt_version",
)


def export_unlabeled_product_names(
    posts_path: Path,
    out_path: Path,
    labels_path: Path,
) -> int:
    """Write one row per distinct unlabelled raw field. Returns the row count."""
    labelled = load_product_name_labels(labels_path)
    posts = load_posts(str(posts_path))

    # Import lazily: the rule engine reads the label cache. Use the rule-only entry
    # point so the guess shown to the labeller — and hashed into the key — depends
    # on the rules alone and stays recomputable from the exported row.
    from cvs_radar.scoring import extract_products_and_prices_by_rules

    seen: set[str] = set()
    rows: list[dict[str, str]] = []
    for post in posts:
        raw_name = post.product_name or ""
        if not raw_name.strip():
            continue
        rule_guess = format_rule_guess(
            extract_products_and_prices_by_rules(raw_name, post.brand)
        )
        fingerprint = product_name_fingerprint_v2(
            post.brand, post.title, raw_name, rule_guess=rule_guess
        )
        legacy = product_name_fingerprint(post.brand, post.title, raw_name)
        if fingerprint in labelled or legacy in labelled or fingerprint in seen:
            continue
        seen.add(fingerprint)
        rows.append(
            {
                "fingerprint": fingerprint,
                "item_index": "0",
                "brand": post.brand,
                "title": post.title,
                "raw_name": raw_name,
                "rule_guess": rule_guess,
                "product_name": "",
                "price": "",
                "model": "",
                "prompt_version": PROMPT_VERSION,
            }
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--posts", type=Path, default=DEFAULT_POSTS_PATH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_PATH)
    parser.add_argument("--labels", type=Path, default=ROOT / PRODUCT_NAME_LABELS_PATH)
    args = parser.parse_args()

    count = export_unlabeled_product_names(args.posts, args.out, args.labels)
    print(f"exported {count} unlabeled product-name fields -> {args.out}")


if __name__ == "__main__":
    main()
