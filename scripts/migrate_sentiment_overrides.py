#!/usr/bin/env python3
"""Canonicalize the legacy text sentiment cache without changing runtime scores."""

from __future__ import annotations

import argparse
import csv
import os
import tempfile
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cvs_radar.sentiment import _normalize_override_text


def analyze(path: Path) -> tuple[list[tuple[str, str, str]], int, int]:
    """Return last-row-wins canonical rows, collision count, and conflict count."""
    rows: dict[str, tuple[str, str, str]] = {}
    collisions = conflicts = 0
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            key = _normalize_override_text(row.get("留言內容", ""))
            if not key:
                continue
            value = (key, row.get("llm分數", ""), row.get("llm判定", ""))
            if key in rows:
                collisions += 1
                if float(rows[key][1]) != float(value[1]):
                    conflicts += 1
            rows[key] = value
    return [rows[key] for key in sorted(rows)], collisions, conflicts


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
