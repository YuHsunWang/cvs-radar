#!/usr/bin/env python3
"""Fill data/labels/official_nutrition.csv from FamilyMart product pages.

Run by hand (opens a visible Chrome window, see cvs_radar/official_nutrition.py).
Only products the site actually shows with FamilyMart calories are visited.
Cached rows are skipped unless the catalogue now gives that name a different
CMNO (a relaunched product) or --refresh is passed, which revisits everything
to pick up reformulations the page changed in place.
The CSV is saved after every page, so an interrupted run keeps its progress.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cvs_radar.official_kcal import fetch_family_payload, load_lookup  # noqa: E402
from cvs_radar.official_nutrition import (  # noqa: E402
    OFFICIAL_NUTRITION_PATH,
    fetch_family_details,
    load_nutrition,
    parse_detail_text,
    write_nutrition,
)

DATA_JSON = ROOT / "web" / "public" / "data.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--delay", type=float, default=1.0, help="seconds between product pages")
    parser.add_argument("--limit", type=int, help="visit at most this many pages (for a trial run)")
    parser.add_argument("--refresh", action="store_true", help="revisit cached products too")
    args = parser.parse_args()

    lookup = load_lookup()
    products = json.loads(DATA_JSON.read_text(encoding="utf-8"))["products"]
    wanted = {
        name
        for product in products
        if product["brand"] == "全家"
        and (name := lookup.official_name_for(product["brand"], product["productName"]))
    }
    # Rows written before serving units were recorded are refetched, not kept.
    rows = {row["official_name"]: row for row in load_nutrition() if row["brand"] == "全家" and "serving_size" in row}
    others = [row for row in load_nutrition() if row["brand"] != "全家"]

    catalogue = fetch_family_payload()
    cmno_by_name = {
        (item.get("PRODNAME") or "").strip(): item["CMNO"]
        for category in catalogue.get("LIST") or []
        for item in category.get("ITEM") or []
        if item.get("CMNO")
    }
    todo = {
        cmno_by_name[name]: name
        for name in sorted(wanted)
        if name in cmno_by_name
        and (args.refresh or name not in rows or rows[name]["cmno"] != cmno_by_name[name])
    }
    if args.limit:
        todo = dict(list(todo.items())[: args.limit])
    print(f"[official-nutrition] {len(wanted)} products shown; {len(rows)} cached; visiting {len(todo)}")

    today = datetime.now(ZoneInfo("Asia/Taipei")).date().isoformat()
    misses = []

    def save(cmno: str, text: str) -> None:
        parsed = parse_detail_text(text)
        if parsed is None:
            misses.append(cmno)
            return
        name = todo[cmno]
        rows[name] = {"brand": "全家", "official_name": name, "cmno": cmno, **parsed, "fetched": today}
        write_nutrition(others + list(rows.values()))

    fetch_family_details(todo, delay=args.delay, on_page=save)
    print(f"[official-nutrition] saved {len(todo) - len(misses)}; no full label on {len(misses)}: {' '.join(misses)}")
    print(f"[official-nutrition] -> {OFFICIAL_NUTRITION_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
