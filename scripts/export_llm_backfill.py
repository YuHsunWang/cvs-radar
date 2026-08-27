#!/usr/bin/env python3
"""Export account-free, unlabeled historical comments for manual LLM backfill."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cvs_radar.sentiment import (  # noqa: E402
    FINGERPRINT_LABELS_PATH,
    SENTIMENT_PROMPT_VERSION,
    _normalize_override_text,
    load_fingerprint_labels,
    load_sentiment_corrections,
    sentiment_fingerprint,
    sentiment_fingerprint_v2,
)
from cvs_radar.scoring import preprocess_posts  # noqa: E402
from cvs_radar.store import load_posts  # noqa: E402

DEFAULT_POSTS_PATH = ROOT / "data" / "posts.jsonl"
DEFAULT_OUT_PATH = ROOT / "artifacts" / "unlabeled-comments.csv"

FIELDNAMES = (
    "fingerprint",
    "brand",
    "product_name",
    "post_title",
    "tag",
    "comment_text",
    "llm_score",
    "llm_label",
    "is_relevant",
    "reason",
    "model",
    "prompt_version",
)


def export_unlabeled_comments(
    posts_path: Path,
    out_path: Path,
    *,
    known_texts: set[str] | None = None,
    known_fingerprints: set[str] | None = None,
) -> int:
    """Write unique comments missing both legacy and fingerprint labels."""
    if not posts_path.exists():
        raise FileNotFoundError(f"no stored posts found at {posts_path}")

    # Only reviewed corrections suppress export: they already have the final say.
    # Legacy text labels deliberately do NOT, so their comments can still receive a
    # context-aware fingerprint label (see load_sentiment_overrides).
    if known_texts is None:
        known_texts = set(load_sentiment_corrections())
    if known_fingerprints is None:
        known_fingerprints = set(load_fingerprint_labels(ROOT / FINGERPRINT_LABELS_PATH))

    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    # Export the same comment population the scorer can reach. Multi-product
    # routing still discards comments that name none of the split products: one
    # scalar sentiment cannot safely represent an unmatched opinion, and paying
    # for those labels buys rows scoring never looks up. A comment that names
    # several of them is no longer discarded — routing hands it to each as a copy
    # tagged with that product, so each copy exports and is labelled separately,
    # which is what lets "糰子不好吃 蕨餅還可以" say opposite things about the two.
    # Everything else shows and hashes source_product_name, the raw context the
    # labeller sees and the scorer preserves for key reconstruction; the tagged
    # copies show and hash the product they carry instead.
    posts = preprocess_posts(load_posts(str(posts_path)))
    for post in posts:
        source_id = post.url or post.id
        for comment in post.comments:
            text = comment.text.strip()
            normalized = _normalize_override_text(text)
            if not normalized:
                continue
            # A reviewed correction has the final say for a comment that belongs to
            # one product, so that comment needs no label. It cannot speak for a
            # tagged copy: corrections are keyed on text alone, and the scorer
            # refuses to put one scalar on every product a comment evaluates, so
            # the copy would end up with no usable verdict at all.
            if normalized in known_texts and not comment.attributed_product:
                continue
            tag = comment.tag
            brand = post.brand
            product_name = (
                comment.attributed_product or post.source_product_name or post.product_name
            )
            post_title = post.title
            fingerprint = sentiment_fingerprint_v2(
                source_id,
                tag,
                text,
                brand=brand,
                product_name=product_name,
                post_title=post_title,
            )
            # A row already answered under the legacy key stays answered; only rows
            # covered by neither key are worth paying a labelling run for.
            legacy = sentiment_fingerprint(source_id, tag, text)
            if fingerprint in known_fingerprints or legacy in known_fingerprints:
                continue
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            rows.append(
                {
                    "fingerprint": fingerprint,
                    "brand": brand,
                    "product_name": product_name,
                    "post_title": post_title,
                    "tag": tag,
                    "comment_text": text,
                    "llm_score": "",
                    "llm_label": "",
                    "is_relevant": "",
                    "reason": "",
                    "model": "",
                    "prompt_version": SENTIMENT_PROMPT_VERSION,
                }
            )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--posts", type=Path, default=DEFAULT_POSTS_PATH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_PATH)
    args = parser.parse_args()

    count = export_unlabeled_comments(args.posts, args.out)
    print(f"exported {count} unlabeled comments to {args.out}")


if __name__ == "__main__":
    main()
