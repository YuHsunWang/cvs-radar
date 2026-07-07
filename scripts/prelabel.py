#!/usr/bin/env python3
"""Auto-prelabel a to_label CSV using RuleBasedPredictor.

Usage:
    python scripts/prelabel.py --input data/labels/to_label.csv --output data/labels/gold_v2_draft.csv
    python scripts/prelabel.py --source stored --output data/labels/gold_v2_draft.csv
    python scripts/prelabel.py --source demo --output data/labels/gold_v2_draft.csv
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cvs_radar.evaluation import RuleBasedPredictor
from cvs_radar.labeling import (
    CSV_COLUMNS,
    build_labeling_rows,
    read_labeling_csv,
)


SENTIMENT_MAP = {"positive": "正", "negative": "負", "neutral": "中"}
TARGET_MAP = {"own": "本牌", "other": "他牌", "none": "無"}
BOOL_MAP = {True: "是", False: "否"}
FAVORED_MAP = {"own": "本牌", "other": "他牌", "tie": "平手", "unknown": "不明"}


def prelabel_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Fill label columns using RuleBasedPredictor."""
    predictor = RuleBasedPredictor()
    labeled = []
    for row in rows:
        prediction = predictor.predict_row(row)
        row = dict(row)
        row["sentiment"] = SENTIMENT_MAP.get(prediction.sentiment, "中")
        row["target_brand"] = TARGET_MAP.get(prediction.target_brand, "無")
        row["is_comparative"] = BOOL_MAP.get(prediction.is_comparative, "否")
        row["favored_brand"] = FAVORED_MAP.get(prediction.favored_brand, "不明")
        row["notes"] = "auto-prelabeled"
        labeled.append(row)
    return labeled


def write_labeled_csv(rows: list[dict[str, str]], path: str | Path) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Auto-prelabel comments for gold review")
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--input", help="Path to existing to_label CSV")
    input_group.add_argument("--source", choices=["demo", "stored"], help="Generate rows from data source")
    parser.add_argument("--output", default="data/labels/gold_v2_draft.csv", help="Output path")
    parser.add_argument("--limit", type=int, help="Max rows to process")
    parser.add_argument("--shuffle", action="store_true", help="Shuffle before limiting")
    parser.add_argument("--seed", type=int, default=0, help="Random seed for shuffle")
    args = parser.parse_args()

    if args.input:
        rows = read_labeling_csv(args.input)
    else:
        from cvs_radar.labeling import _load_posts

        posts = _load_posts(args.source, pages=5)
        labeling_rows = build_labeling_rows(
            posts,
            limit=args.limit,
            shuffle=args.shuffle,
            seed=args.seed,
        )
        rows = [row.to_dict() for row in labeling_rows]

    if args.limit is not None and args.input:
        rows = rows[: args.limit]

    labeled = prelabel_rows(rows)
    write_labeled_csv(labeled, args.output)
    print(f"Wrote {len(labeled)} pre-labeled rows to {args.output}")


if __name__ == "__main__":
    main()
