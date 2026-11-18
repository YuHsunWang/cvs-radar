#!/usr/bin/env python3
"""Save FamilyMart's official photos of image-less products for review.

Run daily by scripts/ops/rebackfill.sh after the nutrition step. Opens a visible
Chrome window, like fetch_official_nutrition.py: FamilyMart answers 403 to
scripts and headless Chrome. Photos and the candidate list go outside the repo;
product_images.csv is never edited here, so nothing goes live unreviewed.
Already-saved photos are not fetched again.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cvs_radar.official_kcal import FAMILY_PAGE, fetch_family_payload, load_lookup  # noqa: E402

CACHE = Path.home() / ".cache" / "cvs-radar"
IMAGE_DIR = CACHE / "familymart-images"
CANDIDATES = CACHE / "familymart-image-candidates.csv"
IMAGE_URL = "https://foodsafety.family.com.tw/product_img/003004.{}.jpg"


def wanted_cmnos(products: list[dict], decided: set[str], official_name_for, cmno_by_name: dict) -> dict[str, str]:
    """product_id -> CMNO for FamilyMart products with no image and no manifest row."""
    out = {}
    for p in products:
        if p["brand"] != "全家" or p.get("image") or p["id"] in decided:
            continue
        name = official_name_for(p["brand"], p["productName"])
        if name and name in cmno_by_name:
            out[p["id"]] = cmno_by_name[name]
    return out


def download(cmnos: set[str], delay: float = 1.0) -> None:
    from playwright.sync_api import sync_playwright

    os.environ.setdefault("DISPLAY", ":0")
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        try:
            page = browser.new_page()
            for cmno in sorted(cmnos):
                try:
                    resp = page.goto(IMAGE_URL.format(cmno), timeout=30_000)
                    if resp and resp.ok and resp.headers.get("content-type", "").startswith("image/"):
                        (IMAGE_DIR / f"{cmno}.jpg").write_bytes(resp.body())
                    else:
                        print(f"[family-images] {cmno}: HTTP {resp.status if resp else '?'}")
                except Exception as exc:  # one bad photo must not lose the rest
                    print(f"[family-images] {cmno}: {exc.__class__.__name__}")
                time.sleep(delay)
        finally:
            browser.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--delay", type=float, default=1.0, help="seconds between photos")
    args = parser.parse_args()

    products = json.loads((ROOT / "web" / "public" / "data.json").read_text(encoding="utf-8"))["products"]
    with (ROOT / "data" / "labels" / "product_images.csv").open(encoding="utf-8-sig", newline="") as f:
        decided = {row["product_id"] for row in csv.DictReader(f)}
    catalogue = fetch_family_payload()
    cmno_by_name = {
        (item.get("PRODNAME") or "").strip(): item["CMNO"]
        for category in catalogue.get("LIST") or []
        for item in category.get("ITEM") or []
        if item.get("CMNO")
    }
    by_product = wanted_cmnos(products, decided, load_lookup().official_name_for, cmno_by_name)
    todo = {c for c in by_product.values() if not (IMAGE_DIR / f"{c}.jpg").exists()}
    print(f"[family-images] {len(by_product)} image-less products with a CMNO; fetching {len(todo)}")
    if todo:
        download(todo, args.delay)

    CANDIDATES.parent.mkdir(parents=True, exist_ok=True)
    with CANDIDATES.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["product_id", "official_id", "source_page_url", "image_url", "local_file"])
        for pid, cmno in sorted(by_product.items()):
            local = IMAGE_DIR / f"{cmno}.jpg"
            if local.exists():
                w.writerow([pid, cmno, f"{FAMILY_PAGE}product/{cmno}", IMAGE_URL.format(cmno), str(local)])
    print(f"[family-images] -> {CANDIDATES}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
