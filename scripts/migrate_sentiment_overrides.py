#!/usr/bin/env python3
"""Canonicalize the legacy text sentiment cache without changing runtime scores."""

from __future__ import annotations

import argparse
import csv
import os
import re
import tempfile
import unicodedata
from collections import Counter
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cvs_radar.sentiment import _normalize_override_text


def _resolve(variants: list[tuple[str, str, str]]) -> tuple[str, str, str]:
    """Pick the score a group of punctuation variants should collapse to.

    Runtime strips trailing punctuation, so 「好吃」「好吃!」「好吃!!」「好吃。」 are one
    key and whichever row happened to be last in the file silently won — which is
    import order, not a judgement. 「好吃」 is the clearest case: three rows agree on
    0.8 and the file's last row says 0.6, so the most common comment in the cache
    was scored by the least representative variant.

    Majority first; on a tie, the variant carrying no trailing punctuation, because
    that is exactly the form the key represents once runtime has normalized it.
    Ties beyond that keep the earliest row so the result never depends on ordering.
    """
    counts = Counter(float(score) for _, score, _ in variants)
    ranked = counts.most_common()
    if len(ranked) == 1 or ranked[0][1] > ranked[1][1]:
        winner = ranked[0][0]
        return next(v for v in variants if float(v[1]) == winner)

    key = _normalize_override_text(variants[0][0])
    for variant in variants:
        if _normalize_override_text(variant[0]) == _collapse(variant[0]) == key:
            return variant
    return variants[0]


def _collapse(text: str) -> str:
    """NFKC + whitespace collapse, WITHOUT stripping trailing punctuation."""
    s = unicodedata.normalize("NFKC", str(text or ""))
    s = s.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    return re.sub(r"\s+", " ", s).strip()


def analyze(path: Path) -> tuple[list[tuple[str, str, str]], int, int]:
    """Return canonical rows in original file order, collision and conflict counts.

    Order is preserved so the rewrite shows only the rows it actually removes or
    rescores; sorting the file would bury 15 real changes in 4,795 moved lines.
    """
    order: list[str] = []
    grouped: dict[str, list[tuple[str, str, str]]] = {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            key = _normalize_override_text(row.get("留言內容", ""))
            if not key:
                continue
            if key not in grouped:
                grouped[key] = []
                order.append(key)
            grouped[key].append(
                (row.get("留言內容", ""), row.get("llm分數", ""), row.get("llm判定", ""))
            )

    collisions = conflicts = 0
    rows: list[tuple[str, str, str]] = []
    for key in order:
        variants = grouped[key]
        collisions += len(variants) - 1
        if len({float(score) for _, score, _ in variants}) > 1:
            conflicts += 1
        _, score, label = _resolve(variants)
        # Store the normalized key, not a punctuated variant: the punctuation is
        # discarded at lookup time anyway, and keeping it invites the next editor
        # to add another variant that collapses onto this same row.
        rows.append((key, score, label))
    return rows, collisions, conflicts


def write_atomic(path: Path, rows: list[tuple[str, str, str]]) -> None:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8-sig",
            newline="",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            writer = csv.writer(handle)
            writer.writerow(("留言內容", "llm分數", "llm判定"))
            writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "path", nargs="?", type=Path, default=Path("data/labels/sentiment_overrides.csv")
    )
    parser.add_argument("--write", action="store_true", help="atomically rewrite the file")
    args = parser.parse_args()

    rows, collisions, conflicts = analyze(args.path)
    with args.path.open(encoding="utf-8-sig", newline="") as handle:
        original = sum(1 for _ in csv.DictReader(handle))
    action = "rewrote" if args.write else "WOULD rewrite"
    if args.write:
        write_atomic(args.path, rows)
    print(
        f"{action} {original} rows as {len(rows)} canonical rows; "
        f"removed={original - len(rows)} collisions={collisions} conflicts={conflicts}"
    )


if __name__ == "__main__":
    main()
