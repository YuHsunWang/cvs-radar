"""Full nutrition labels from FamilyMart's product pages.

The catalogue call in `official_kcal` returns calories only. Each product's own
page (`/Web_FFD_2022/product/<CMNO>`) carries the rest of the packaging label:
serving size, servings per package and seven nutrients per serving. 7-11's
catalogue has nothing beyond calories, so this covers FamilyMart only.

`official_nutrition.csv` stores per-serving values as printed, keyed by the same
(brand, official_name) as `official_kcal.csv`. Rows are never dropped, like the
calorie cache. Values are multiplied out to the package in `nutrition_for`,
using the servings `official_kcal` already decided on, so the label and the
calorie figure always describe the same unit.
"""

from __future__ import annotations

import csv
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Callable, Iterable

from cvs_radar.official_kcal import FAMILY_PAGE, KcalLookup, load_official

ROOT = Path(__file__).resolve().parent.parent
OFFICIAL_NUTRITION_PATH = ROOT / "data" / "labels" / "official_nutrition.csv"

# Order and names follow the label printed on Taiwanese packaging.
NUTRIENTS = (
    ("protein", "蛋白質", "公克"),
    ("fat", "脂肪", "公克"),
    ("saturatedFat", "飽和脂肪", "公克"),
    ("transFat", "反式脂肪", "公克"),
    ("carbohydrate", "碳水化合物", "公克"),
    ("sugar", "糖", "公克"),
    ("sodium", "鈉", "毫克"),
)
NUTRITION_FIELDS = ("brand", "official_name", "cmno", "serving_g", "kcal", *(key for key, _, _ in NUTRIENTS), "fetched")

_NUMBER = r"\s*(\d+(?:\.\d+)?)\s*"
_KCAL = re.compile(r"每份熱量" + _NUMBER + "大卡")
_SERVING_G = re.compile(r"每份規格" + _NUMBER + "(?:公克|毫升)")
# Lookbehind keeps 脂肪 from matching inside 飽和脂肪/反式脂肪, and 糖 inside 醣.
_PATTERNS = {
    key: re.compile(r"(?<![飽和反式])" + re.escape(label) + _NUMBER + re.escape(unit))
    for key, label, unit in NUTRIENTS
}


def parse_detail_text(text: str) -> dict[str, str] | None:
    """Per-serving values from a product page's visible text; None if any is missing.

    A partial label is dropped rather than shown with gaps: a blank 鈉 row next
    to filled ones reads as "no sodium".
    """
    if "每份營養素" not in text:
        return None
    kcal = _KCAL.search(text)
    values = {key: pattern.search(text) for key, pattern in _PATTERNS.items()}
    if kcal is None or any(match is None for match in values.values()):
        return None
    serving = _SERVING_G.search(text)
    row = {key: match.group(1) for key, match in values.items()}
    row["kcal"] = kcal.group(1)
    row["serving_g"] = serving.group(1) if serving else ""
    return row


def fetch_family_details(
    cmnos: Iterable[str], delay: float = 1.0, timeout: float = 30.0, on_page: Callable[[str, str], None] | None = None
) -> dict[str, str]:
    """Visible text of each product page, read in one real (headed) Chrome window.

    Same constraint as `official_kcal.fetch_family_payload`: FamilyMart answers
    403 to scripts and headless Chrome. Pages that fail to load are skipped.
    """
    from playwright.sync_api import sync_playwright

    os.environ.setdefault("DISPLAY", ":0")
    texts = {}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        try:
            page = browser.new_page()
            for cmno in cmnos:
                try:
                    page.goto(f"{FAMILY_PAGE}product/{cmno}", wait_until="networkidle", timeout=timeout * 1000)
                    page.get_by_text("每份營養素").first.wait_for(timeout=timeout * 1000)
                    # The page shows only 碳水/蛋白質/脂肪 until 查看全部 is opened.
                    expand = page.get_by_text("查看全部").first
                    if expand.is_visible():
                        expand.click()
                        page.wait_for_timeout(500)
                    texts[cmno] = page.inner_text("body")
                    if parse_detail_text(texts[cmno]) is None:
                        # Hidden rows may still be in the DOM; textContent includes them.
                        texts[cmno] = page.text_content("body") or ""
                except Exception as exc:  # one bad page must not lose the rest
                    texts[cmno] = ""
                    print(f"[official-nutrition] {cmno}: {exc.__class__.__name__}")
                if on_page:
                    on_page(cmno, texts[cmno])
                time.sleep(delay)
        finally:
            browser.close()
    return texts


def load_nutrition(path: Path = OFFICIAL_NUTRITION_PATH) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_nutrition(rows: list[dict[str, str]], path: Path = OFFICIAL_NUTRITION_PATH) -> None:
    # BOM + CRLF like the other label caches.
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(rows, key=lambda row: (row["brand"], row["official_name"]))
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8-sig", newline="", dir=path.parent, suffix=".tmp", delete=False
    )
    try:
        with handle:
            writer = csv.DictWriter(handle, fieldnames=NUTRITION_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        os.replace(handle.name, path)
    except Exception:
        Path(handle.name).unlink(missing_ok=True)
        raise


class NutritionLookup:
    def __init__(self, kcal: KcalLookup, official: list[dict[str, str]], nutrition: list[dict[str, str]]) -> None:
        self._kcal = kcal
        self._servings = {(row["brand"], row["official_name"]): row["servings"] for row in official}
        self._rows = {(row["brand"], row["official_name"]): row for row in nutrition}

    def nutrition_for(self, brand: str, product_name: str) -> dict | None:
        official_name = self._kcal.official_name_for(brand, product_name)
        row = self._rows.get((brand, official_name)) if official_name else None
        if row is None:
            return None
        servings = int(self._servings.get((brand, official_name)) or 1)
        return {
            "servingGrams": float(row["serving_g"]) if row["serving_g"] else None,
            "servings": servings,
            "perServing": {"kcal": float(row["kcal"]), **{key: float(row[key]) for key, _, _ in NUTRIENTS}},
        }


def load_nutrition_lookup(kcal: KcalLookup) -> NutritionLookup:
    return NutritionLookup(kcal, load_official(), load_nutrition())
