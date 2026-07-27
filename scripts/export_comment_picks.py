#!/usr/bin/env python3
"""Export products with no representative-comment pick yet, for a labelling run."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cvs_radar.comment_labels import (  # noqa: E402
    COMMENT_PICKS_PATH,
    PROMPT_VERSION,
    comment_picks_fingerprint,
    load_comment_picks,
)
from cvs_radar.scoring import (  # noqa: E402
    _rep_candidates,
    _body_candidates,
    group_products,
    preprocess_posts,
    representative_product_name,
)
from cvs_radar.sentiment import annotate_posts, apply_sentiment_overrides  # noqa: E402
from cvs_radar.store import load_posts  # noqa: E402

DEFAULT_POSTS_PATH = ROOT / "data" / "posts.jsonl"
DEFAULT_OUT_PATH = ROOT / "artifacts" / "unlabeled-comment-picks.csv"

FIELDNAMES = (
    "fingerprint",
    "brand",
    "product_name",
    "other_products",
    "positive_candidates",
    "negative_candidates",
    "body_candidates",
    "positive_picks",
    "negative_picks",
    "positive_body_picks",
    "negative_body_picks",
    "model",
    "prompt_version",
)


def _numbered_candidates(candidates: list[str]) -> str:
    return "\n".join(f"{index}. {text}" for index, text in enumerate(candidates))


def export_unlabeled_comment_picks(
    posts_path: Path,
    out_path: Path,
    labels_path: Path,
) -> int:
    """Write one row per unlabelled product with comment or body candidates."""
    labelled = load_comment_picks(labels_path)
    posts = apply_sentiment_overrides(annotate_posts(preprocess_posts(load_posts(str(posts_path)))))

    # A thread reviewing several products is split into one item per product, but
    # every split item keeps the whole post body. Naming the thread-mates is what
    # lets the labeller keep their sentences out of this product's picks — the same
    # column that fixed cross-product contamination in the excerpt labels.
    thread_products: dict[str, list[str]] = {}
    for post in posts:
        base_id = post.id.split("_", 1)[0]
        names = thread_products.setdefault(base_id, [])
        if post.product_name not in names:
            names.append(post.product_name)

    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for group in group_products(posts).values():
        positive, negative = _rep_candidates(group)
        body = _body_candidates(group)
        if not positive and not negative and not body:
            continue
        brand = group[0].brand
        product_name = representative_product_name(group)
        fingerprint = comment_picks_fingerprint(brand, product_name, positive, negative, body)
        if fingerprint in labelled or fingerprint in seen:
            continue
        seen.add(fingerprint)
        mates: list[str] = []
        for post in group:
            for name in thread_products.get(post.id.split("_", 1)[0], ()):
                if name != post.product_name and name not in mates:
                    mates.append(name)
        rows.append(
            {
                "fingerprint": fingerprint,
                "brand": brand,
                "product_name": product_name,
                "other_products": " | ".join(mates),
                "positive_candidates": _numbered_candidates(positive),
                "negative_candidates": _numbered_candidates(negative),
                "body_candidates": _numbered_candidates(body),
                "positive_picks": "",
                "negative_picks": "",
                "positive_body_picks": "",
                "negative_body_picks": "",
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
    parser.add_argument("--labels", type=Path, default=ROOT / COMMENT_PICKS_PATH)
    args = parser.parse_args()

    count = export_unlabeled_comment_picks(args.posts, args.out, args.labels)
    print(f"exported {count} unlabeled comment-pick products -> {args.out}")


if __name__ == "__main__":
    main()
