#!/usr/bin/env python3
"""Export (post, product) pairs with no excerpt label yet, for a labelling run."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cvs_radar.excerpt_labels import (  # noqa: E402
    EXCERPT_LABELS_PATH,
    PROMPT_VERSION,
    excerpt_fingerprint,
    load_excerpt_labels,
)
from cvs_radar.store import load_posts  # noqa: E402

DEFAULT_POSTS_PATH = ROOT / "data" / "posts.jsonl"
DEFAULT_OUT_PATH = ROOT / "artifacts" / "unlabeled-excerpts.csv"

FIELDNAMES = (
    "fingerprint",
    "post_id",
    "brand",
    "product_name",
    "other_products",
    "review_text",
    "excerpt",
    "model",
    "prompt_version",
)


def export_unlabeled_excerpts(posts_path: Path, out_path: Path, labels_path: Path) -> int:
    """Write one row per unlabelled (post, product) pair. Returns the row count."""
    labelled = load_excerpt_labels(labels_path)
    from cvs_radar.scoring import preprocess_posts

    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for post in load_posts(str(posts_path)):
        products = preprocess_posts([post])
        names = [item.product_name for item in products]
        for item in products:
            review = item.review_text or ""
            if not review.strip():
                continue
            fingerprint = excerpt_fingerprint(item.id, item.product_name, review)
            if fingerprint in labelled or fingerprint in seen:
                continue
            seen.add(fingerprint)
            rows.append(
                {
                    "fingerprint": fingerprint,
                    "post_id": item.id,
                    "brand": item.brand,
                    "product_name": item.product_name,
                    # Naming the thread's other products is what lets the labeller
                    # keep their sentences out of this product's excerpt.
                    "other_products": " | ".join(n for n in names if n != item.product_name),
                    "review_text": review,
                    "excerpt": "",
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
    parser.add_argument("--labels", type=Path, default=ROOT / EXCERPT_LABELS_PATH)
    args = parser.parse_args()

    count = export_unlabeled_excerpts(args.posts, args.out, args.labels)
    print(f"exported {count} unlabeled (post, product) pairs -> {args.out}")


if __name__ == "__main__":
    main()
