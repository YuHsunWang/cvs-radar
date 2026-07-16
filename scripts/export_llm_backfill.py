#!/usr/bin/env python3
"""Export account-free, unlabeled historical comments for manual LLM backfill."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from cvs_radar.sentiment import (
    FINGERPRINT_LABELS_PATH,
    _normalize_override_text,
    load_fingerprint_labels,
    load_sentiment_overrides,
    sentiment_fingerprint,
)

ROOT = Path(__file__).resolve().parents[1]
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

    if known_texts is None:
        known_texts = set(load_sentiment_overrides())
    if known_fingerprints is None:
        known_fingerprints = set(load_fingerprint_labels(FINGERPRINT_LABELS_PATH))

    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw_line in posts_path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip():
            continue
        post = json.loads(raw_line)
        source_id = str(post.get("url") or post.get("id") or "")
        for comment in post.get("comments") or []:
            text = str(comment.get("text") or "").strip()
            normalized = _normalize_override_text(text)
            if not normalized or normalized in known_texts:
                continue
            fingerprint = sentiment_fingerprint(source_id, str(comment.get("tag") or ""), text)
            if fingerprint in known_fingerprints or fingerprint in seen:
                continue
            seen.add(fingerprint)
            rows.append(
                {
                    "fingerprint": fingerprint,
                    "brand": str(post.get("brand") or ""),
                    "product_name": str(post.get("product_name") or ""),
                    "post_title": str(post.get("title") or ""),
                    "tag": str(comment.get("tag") or ""),
                    "comment_text": text,
                    "llm_score": "",
                    "llm_label": "",
                    "is_relevant": "",
                    "reason": "",
                    "model": "",
                    "prompt_version": "sentiment-v1",
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
