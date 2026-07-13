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
import re
import sys
import unicodedata
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OVERRIDES_PATH = ROOT / "data" / "labels" / "sentiment_overrides.csv"
LIVE_RESULTS_URL = (
    "https://raw.githubusercontent.com/YuHsunWang/cvs-radar/main/data/results.json"
)
FRESH_CUTOFF = "2026-07-05"  # only consider reports whose latest post is on/after this


def normalize(text: str) -> str:
    """Match cvs_radar.sentiment._normalize_override_text (NFKC + whitespace collapse)."""
    s = unicodedata.normalize("NFKC", str(text or ""))
    s = s.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    return re.sub(r"\s+", " ", s).strip()


def load_override_keys() -> set[str]:
    keys: set[str] = set()
    if not OVERRIDES_PATH.exists():
        return keys
    with open(OVERRIDES_PATH, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            key = normalize(row.get("留言內容", ""))
            if key:
                keys.add(key)
    return keys


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
    existing = load_override_keys()
    before = len(existing)
    new_rows: list[tuple[str, str, str]] = []
    with open(labeled_path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            text = row.get("留言內容", "")
            key = normalize(text)
            if not key or key in existing:
                continue
            existing.add(key)
            new_rows.append((text, row.get("llm分數", ""), row.get("llm判定", "")))
    if new_rows:
        with open(OVERRIDES_PATH, "a", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            for row in new_rows:
                writer.writerow(row)
    return len(new_rows), before + len(new_rows)


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
