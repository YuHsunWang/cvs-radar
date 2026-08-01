#!/usr/bin/env python3
"""Validate and merge LLM-picked representative comments into the fingerprint cache."""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cvs_radar.comment_labels import (  # noqa: E402
    COMMENT_PICKS_PATH,
    FIELDNAMES,
    PROMPT_VERSION,
)

DEFAULT_LABELS_PATH = ROOT / COMMENT_PICKS_PATH


def _read_existing(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8-sig", newline="") as handle:
        return {
            str(row.get("fingerprint") or "").strip().lower(): {
                field: str(row.get(field) or "").strip() for field in FIELDNAMES
            }
            for row in csv.DictReader(handle)
            if str(row.get("fingerprint") or "").strip()
        }


def _candidate_count(raw: str | None, *, line_number: int, polarity: str) -> int:
    lines = [line for line in str(raw or "").splitlines() if line.strip()]
    expected = list(range(len(lines)))
    indexes: list[int] = []
    for line in lines:
        match = re.fullmatch(r"\s*(\d+)\.\s+.+", line)
        if match is None:
            raise ValueError(f"row {line_number}: malformed {polarity}_candidates")
        indexes.append(int(match.group(1)))
    if indexes != expected:
        raise ValueError(f"row {line_number}: malformed {polarity}_candidates")
    return len(lines)


def _parse_picks(
    raw: str | None,
    *,
    count: int,
    line_number: int,
    polarity: str,
) -> tuple[int, ...]:
    text = str(raw or "").strip()
    if not text:
        return ()
    try:
        picks = tuple(int(item.strip()) for item in text.split("|"))
    except ValueError as exc:
        raise ValueError(f"row {line_number}: invalid {polarity}_picks") from exc
    if len(picks) > 3:
        raise ValueError(f"row {line_number}: more than 3 {polarity}_picks")
    if len(set(picks)) != len(picks):
        raise ValueError(f"row {line_number}: duplicate {polarity}_picks")
    if any(index < 0 or index >= count for index in picks):
        raise ValueError(f"row {line_number}: {polarity}_pick outside candidate range")
    return picks


def import_picks(
    labeled_path: Path,
    labels_path: Path = DEFAULT_LABELS_PATH,
    *,
    replace: bool = False,
    model_tag: str = "",
) -> tuple[int, int, int]:
    """Merge completed rows and return (added, replaced, skipped_incomplete).

    Blank pick cells are real verdicts, so they are stored. Only a row with both
    polarities blank and no model was never worked on and is skipped.
    """
    existing = _read_existing(labels_path)
    added = replaced = skipped = 0

    with open(labeled_path, encoding="utf-8-sig", newline="") as handle:
        for line_number, row in enumerate(csv.DictReader(handle), start=2):
            positive_raw = str(row.get("positive_picks") or "").strip()
            negative_raw = str(row.get("negative_picks") or "").strip()
            positive_body_raw = str(row.get("positive_body_picks") or "").strip()
            negative_body_raw = str(row.get("negative_body_picks") or "").strip()
            model = str(row.get("model") or "").strip()
            if not positive_raw and not negative_raw and not positive_body_raw and not negative_body_raw and not model:
                skipped += 1
                continue

            fingerprint = str(row.get("fingerprint") or "").strip().lower()
            if not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
                raise ValueError(f"row {line_number}: invalid fingerprint")
            positive_count = _candidate_count(
                row.get("positive_candidates"), line_number=line_number, polarity="positive"
            )
            negative_count = _candidate_count(
                row.get("negative_candidates"), line_number=line_number, polarity="negative"
            )
            body_count = _candidate_count(
                row.get("body_candidates"), line_number=line_number, polarity="body"
            )
            positive_picks = _parse_picks(
                positive_raw,
                count=positive_count,
                line_number=line_number,
                polarity="positive",
            )
            negative_picks = _parse_picks(
                negative_raw,
                count=negative_count,
                line_number=line_number,
                polarity="negative",
            )
            positive_body_picks = _parse_picks(
                positive_body_raw,
                count=body_count,
                line_number=line_number,
                polarity="positive_body",
            )
            negative_body_picks = _parse_picks(
                negative_body_raw,
                count=body_count,
                line_number=line_number,
                polarity="negative_body",
            )
            if set(positive_body_picks) & set(negative_body_picks):
                raise ValueError(f"row {line_number}: body pick appears in both polarities")
            output = {
                "fingerprint": fingerprint,
                "brand": str(row.get("brand") or "").strip(),
                "product_name": str(row.get("product_name") or "").strip(),
                "positive_picks": "|".join(str(index) for index in positive_picks),
                "negative_picks": "|".join(str(index) for index in negative_picks),
                "positive_body_picks": "|".join(str(index) for index in positive_body_picks),
                "negative_body_picks": "|".join(str(index) for index in negative_body_picks),
                "model": model_tag or model or "subscription-llm",
                "prompt_version": str(row.get("prompt_version") or PROMPT_VERSION).strip(),
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
    with open(temporary, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(existing[key] for key in sorted(existing))
    temporary.replace(labels_path)
    return added, replaced, skipped


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("labeled", type=Path, help="CSV produced by the labelling run")
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS_PATH)
    parser.add_argument(
        "--model-tag",
        default="",
        help="record this model name instead of the one the labeller wrote "
             "(its value still marks which rows it worked on)",
    )
    parser.add_argument("--replace", action="store_true", help="overwrite existing labels")
    args = parser.parse_args()

    added, replaced, skipped = import_picks(args.labeled, args.labels, replace=args.replace, model_tag=args.model_tag)
    print(
        f"imported comment picks: {added} added, {replaced} replaced, "
        f"{skipped} skipped (0 errors)"
    )


if __name__ == "__main__":
    main()
