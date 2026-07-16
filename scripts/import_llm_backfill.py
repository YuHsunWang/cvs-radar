#!/usr/bin/env python3
"""Validate and merge manually labeled comments into the fingerprint label cache."""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LABELS_PATH = ROOT / "data" / "labels" / "sentiment_fingerprint_labels.csv"
OUTPUT_FIELDS = (
    "fingerprint",
    "llm_score",
    "llm_label",
    "is_relevant",
    "model",
    "prompt_version",
)
TRUE_VALUES = {"1", "true", "yes", "y"}
FALSE_VALUES = {"0", "false", "no", "n"}
VALID_LABELS = {"正向", "中性", "負向", "positive", "neutral", "negative"}


def _read_existing(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        return {
            str(row.get("fingerprint") or "").strip().lower(): {
                field: str(row.get(field) or "").strip()
                for field in OUTPUT_FIELDS
            }
            for row in csv.DictReader(f)
            if str(row.get("fingerprint") or "").strip()
        }


def import_labels(
    labeled_path: Path,
    labels_path: Path = DEFAULT_LABELS_PATH,
    *,
    replace: bool = False,
) -> tuple[int, int, int]:
    """Merge completed rows and return (added, replaced, skipped_incomplete)."""
    existing = _read_existing(labels_path)
    added = 0
    replaced = 0
    skipped = 0

    with open(labeled_path, encoding="utf-8-sig", newline="") as f:
        for line_number, row in enumerate(csv.DictReader(f), start=2):
            fingerprint = str(row.get("fingerprint") or "").strip().lower()
            score_raw = str(row.get("llm_score") or "").strip()
            label = str(row.get("llm_label") or "").strip()
            relevant_raw = str(row.get("is_relevant") or "").strip().casefold()
            if not score_raw and not label and not relevant_raw:
                skipped += 1
                continue
            if not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
                raise ValueError(f"row {line_number}: invalid fingerprint")
            if relevant_raw not in TRUE_VALUES | FALSE_VALUES:
                raise ValueError(f"row {line_number}: is_relevant must be true or false")
            is_relevant = relevant_raw in TRUE_VALUES
            if label.casefold() not in {value.casefold() for value in VALID_LABELS}:
                raise ValueError(f"row {line_number}: invalid llm_label {label!r}")

            score = ""
            if is_relevant:
                try:
                    parsed_score = float(score_raw)
                except ValueError as exc:
                    raise ValueError(f"row {line_number}: invalid llm_score") from exc
                if not -1.0 <= parsed_score <= 1.0:
                    raise ValueError(f"row {line_number}: llm_score outside [-1, 1]")
                score = str(round(parsed_score, 4))

            output = {
                "fingerprint": fingerprint,
                "llm_score": score,
                "llm_label": label,
                "is_relevant": "true" if is_relevant else "false",
                "model": str(row.get("model") or "subscription-llm").strip(),
                "prompt_version": str(row.get("prompt_version") or "sentiment-v1").strip(),
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
    with open(temporary, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
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
        args.labeled,
        args.labels,
        replace=args.replace,
    )
    print(
        f"labels merged: added={added} replaced={replaced} "
        f"skipped_incomplete={skipped} path={args.labels}"
    )


if __name__ == "__main__":
    main()
