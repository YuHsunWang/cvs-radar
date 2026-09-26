#!/usr/bin/env python3
"""Refresh data/labels/official_kcal.csv from the 7-11 and FamilyMart catalogues.

Run once a day by scripts/ops/rebackfill.sh. On any fetch error it exits
non-zero and leaves the CSV untouched, so the site keeps yesterday's figures.

--candidates OUT writes near-miss names (published product vs catalogue row)
that have no verdict in kcal_matches.csv yet, for a human to review. It does
not fetch; it reads the CSV and web/public/data.json.
"""

from __future__ import annotations

import argparse
import csv
import difflib
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cvs_radar.official_kcal import (  # noqa: E402
    OFFICIAL_KCAL_PATH,
    fetch_all,
    load_lookup,
    load_matches,
    load_official,
    merge_official,
    normalize_name,
    write_official,
)

CANDIDATE_CUTOFF = 0.8


def write_candidates(out: Path) -> int:
    products = json.loads((ROOT / "web" / "public" / "data.json").read_text(encoding="utf-8"))["products"]
    official = load_official()
    reviewed = load_matches()
    lookup = load_lookup()
    names: dict[str, dict[str, str]] = {}
    for row in official:
        names.setdefault(row["brand"], {})[normalize_name(row["official_name"])] = row["official_name"]
    rows = []
    for product in products:
        if product["id"] in reviewed or lookup.kcal_for(product["brand"], product["productName"]) is not None:
            continue
        catalogue = names.get(product["brand"], {})
        close = difflib.get_close_matches(
            normalize_name(product["productName"]), catalogue, n=1, cutoff=CANDIDATE_CUTOFF
        )
        if close:
            rows.append({"product_id": product["id"], "official_name": catalogue[close[0]], "verdict": ""})
    with out.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("product_id", "official_name", "verdict"))
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} unreviewed candidates to {out}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", type=Path, help="write unreviewed near-miss names here and exit")
    parser.add_argument("--delay", type=float, default=1.0, help="seconds between 7-11 requests")
    args = parser.parse_args()
    if args.candidates:
        return write_candidates(args.candidates)

    try:
        fetched = fetch_all(delay=args.delay)
    except Exception as exc:
        print(f"[official-kcal] FAILED, cache unchanged: {exc}", file=sys.stderr)
        return 1
    today = datetime.now(ZoneInfo("Asia/Taipei")).date().isoformat()
    before = load_official()
    rows = merge_official(before, fetched, today)
    write_official(rows)
    print(f"[official-kcal] fetched {len(fetched)} rows; cache {len(before)} -> {len(rows)} -> {OFFICIAL_KCAL_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
