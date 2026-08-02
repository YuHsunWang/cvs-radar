#!/usr/bin/env python3
"""Semi-automatic sentiment relabeling helper (DEV-7).

The daily refresh-data workflow recomputes with the committed
``data/labels/sentiment_overrides.csv`` cache. Comments newer than the cache
fall back to the positive-biased lexicon and get mislabeled (implicit /
comparative Chinese negativity in particular). This helper turns the periodic
"catch the cache up" loop into two commands; the labeling itself is done by an
LLM (e.g. Codex/luna) between the two steps.

Loop
----
1. Extract the delta (surfaced comments not yet in the cache):

       python scripts/relabel_delta.py extract --out to_label.txt

   Source defaults to the live published results.json on main, so no raw
   ``data/posts.jsonl`` is needed (privacy-clean). Only comments that surface
   in each report's ``rep_positive`` / ``rep_negative`` are considered — those
   are the ones that actually drive likes / cautions / consensus.

2. Hand ``to_label.txt`` to an LLM and get back a CSV with columns
   ``留言內容,llm分數,llm判定`` (score in [-1,1]; 判定 in 正向/中性/負向).

3. Merge the labels into the cache:

       python scripts/relabel_delta.py merge labeled.csv

4. Commit ``data/labels/sentiment_overrides.csv`` and trigger the recompute:

       gh workflow run refresh-data.yml --repo <owner>/<repo>

Only NEW comments are ever added; existing rows are never modified.
"""

from __future__ import annotations

import argparse
import csv
import os
import tempfile
import urllib.request
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cvs_radar.sentiment import _normalize_override_text

OVERRIDES_PATH = ROOT / "data" / "labels" / "sentiment_overrides.csv"
LIVE_RESULTS_URL = (
    "https://raw.githubusercontent.com/YuHsunWang/cvs-radar/main/data/results.json"
)
FRESH_CUTOFF = "2026-07-05"  # only consider reports whose latest post is on/after this


normalize = _normalize_override_text


def _score(row: dict[str, str]) -> float:
    return float(str(row.get("llm分數") or "").strip())


def _load_override_rows() -> dict[str, tuple[str, str, str]]:
    rows: dict[str, tuple[str, str, str]] = {}
    if not OVERRIDES_PATH.exists():
        return rows
    with open(OVERRIDES_PATH, encoding="utf-8-sig", newline="") as handle:
        for line_number, row in enumerate(csv.DictReader(handle), start=2):
            key = normalize(row.get("留言內容", ""))
            if not key:
                continue
            value = (key, row.get("llm分數", ""), row.get("llm判定", ""))
            if key in rows and _score({"llm分數": rows[key][1]}) != _score(row):
                raise ValueError(
                    f"{OVERRIDES_PATH}:{line_number}: conflicting normalized key {key!r}"
                )
            rows[key] = value
    return rows


def load_override_keys() -> set[str]:
    return set(_load_override_rows())


def _load_results(source: str):
    import json

    if source.startswith("http://") or source.startswith("https://"):
        with urllib.request.urlopen(source) as resp:  # noqa: S310 (trusted URL)
            return json.load(resp)
    return json.loads(Path(source).read_text(encoding="utf-8"))


def extract(source: str, out_path: Path, cutoff: str) -> int:
    data = _load_results(source)
    existing = load_override_keys()
    seen: set[str] = set()
    todo: list[str] = []
    for report in data.get("reports", []):
        latest = (report.get("latest_post_date") or "")[:10]
        if cutoff and latest < cutoff:
            continue
        for field in ("rep_positive", "rep_negative"):
            for comment in report.get(field) or []:
                key = normalize(comment)
                if not key or key in existing or key in seen:
                    continue
                seen.add(key)
                todo.append(key)
    out_path.write_text(
        "".join(f"{i}\t{text}\n" for i, text in enumerate(todo, 1)),
        encoding="utf-8",
    )
    return len(todo)


def merge(labeled_path: Path) -> tuple[int, int]:
    existing = _load_override_rows()
    added = 0
    with open(labeled_path, encoding="utf-8-sig", newline="") as f:
        for line_number, row in enumerate(csv.DictReader(f), start=2):
            text = row.get("留言內容", "")
            key = normalize(text)
            if not key:
                continue
            value = (key, row.get("llm分數", ""), row.get("llm判定", ""))
            if key in existing:
                if _score({"llm分數": existing[key][1]}) != _score(row):
                    raise ValueError(
                        f"{labeled_path}:{line_number}: conflicting normalized key {key!r}"
                    )
                continue
            existing[key] = value
            added += 1

    OVERRIDES_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8-sig",
            newline="",
            dir=OVERRIDES_PATH.parent,
            prefix=f".{OVERRIDES_PATH.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            writer = csv.writer(handle)
            writer.writerow(("留言內容", "llm分數", "llm判定"))
            writer.writerows(existing[key] for key in sorted(existing))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, OVERRIDES_PATH)
    except Exception:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise
    return added, len(existing)


def main() -> None:
    parser = argparse.ArgumentParser(description="Semi-automatic sentiment relabeling helper")
    sub = parser.add_subparsers(dest="command", required=True)

    p_extract = sub.add_parser("extract", help="write surfaced comments not yet in the cache")
    p_extract.add_argument("--results", default=LIVE_RESULTS_URL, help="results.json path or URL")
    p_extract.add_argument("--out", type=Path, default=Path("to_label.txt"))
    p_extract.add_argument("--cutoff", default=FRESH_CUTOFF, help="min latest_post_date (YYYY-MM-DD), '' for all")

    p_merge = sub.add_parser("merge", help="append a labeled CSV into the override cache")
    p_merge.add_argument("labeled", type=Path, help="CSV with columns 留言內容,llm分數,llm判定")

    args = parser.parse_args()
    if args.command == "extract":
        count = extract(args.results, args.out, args.cutoff)
        print(f"wrote {count} comments to {args.out}")
        if count == 0:
            print("cache is already up to date — nothing to label.")
    elif args.command == "merge":
        added, total = merge(args.labeled)
        print(f"merged {added} new rows into {OVERRIDES_PATH.name} (total {total})")


if __name__ == "__main__":
    main()
