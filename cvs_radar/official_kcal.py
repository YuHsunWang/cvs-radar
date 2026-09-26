"""Calories per package from the chains' own product catalogues.

PTT reviews almost never state calories (about 30 of 2,765 posts give a
number), so the figure comes from the chains instead: 7-11's fresh-food
catalogue and FamilyMart's food-safety catalogue both publish one per product.
萊爾富's site refuses scripted requests (HTTP 403), so it has none.
FamilyMart's API also refuses scripts, so it is read through a real browser
window — see `fetch_family_payload`.

Two committed CSVs:

- `official_kcal.csv` — every catalogue row ever seen. Rows are never dropped:
  a delisted product keeps its calories, and delisted products are most of the
  corpus, so coverage grows as new products pass through the catalogue.
- `kcal_matches.csv` — human verdicts on names that are close but not equal
  (``晶華-港式油雞臘味飯`` vs ``港式油雞臘味飯``). Only ``same`` is applied.

A product gets calories only on an exact normalised-name match or a reviewed
``same`` verdict. A wrong number is worse than none, so near misses stay blank.

FamilyMart states calories per serving plus the servings per package; this
module stores the per-package total, because the question a shopper asks is
"how much is this one item", not "how much is a third of it".
"""

from __future__ import annotations

import csv
import json
import os
import re
import tempfile
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import requests

ROOT = Path(__file__).resolve().parent.parent
OFFICIAL_KCAL_PATH = ROOT / "data" / "labels" / "official_kcal.csv"
KCAL_MATCHES_PATH = ROOT / "data" / "labels" / "kcal_matches.csv"

OFFICIAL_FIELDS = ("brand", "official_name", "kcal", "servings", "first_seen", "last_seen")
MATCH_FIELDS = ("product_id", "official_name", "verdict")
VERDICTS = {"same", "different"}

SEVEN_URL = "https://www.7-11.com.tw/freshfoods/read_food_xml.aspx?={category}"
# 0-19 held items on 2026-09-26; 20-29 were empty. The spare ids cost ten
# requests a day and pick up a new category without a code change.
SEVEN_CATEGORIES = range(30)
FAMILY_PAGE = "https://foodsafety.family.com.tw/Web_FFD_2022/"
FAMILY_URL = FAMILY_PAGE + "ws/QueryFsProductListByFilter"
USER_AGENT = "CVS-Radar/1.0 (+https://cvs-radar.vercel.app; once-daily calorie lookup)"

_FAMILY_NOTE = re.compile(r"熱量\s*(\d+(?:\.\d+)?)\s*大卡.*?本包裝含\s*(\d+(?:\.\d+)?)\s*份")
_SEVEN_KCAL = re.compile(r"^\s*(\d+(?:\.\d+)?)")
_BRACKETED = re.compile(r"（[^）]*）|\([^)]*\)")
_DROPPED = re.compile(r"[\s　\-－_・·]")


@dataclass(frozen=True)
class OfficialItem:
    brand: str
    official_name: str
    kcal: int
    servings: int | None = None


def normalize_name(name: str) -> str:
    """Compare names without spacing, dashes or bracketed notes like (植覺生活)."""
    return _DROPPED.sub("", _BRACKETED.sub("", name or ""))


def parse_seven_xml(payload: bytes | str) -> list[OfficialItem]:
    root = ET.fromstring(payload)
    items = []
    for node in root.iter("Item"):
        name = (node.findtext("name") or "").strip()
        match = _SEVEN_KCAL.match(node.findtext("kcal") or "")
        if not name or not match:
            continue
        kcal = round(float(match.group(1)))
        if kcal > 0:
            items.append(OfficialItem("7-11", name, kcal))
    return items


def parse_family_list(payload: dict) -> list[OfficialItem]:
    if payload.get("RESULT_CODE") != "00":
        raise ValueError(f"FamilyMart API error: {payload.get('RESULT_DESC')!r}")
    items = []
    for category in payload.get("LIST") or []:
        for row in category.get("ITEM") or []:
            name = (row.get("PRODNAME") or "").strip()
            match = _FAMILY_NOTE.search(row.get("NOTE") or "")
            if not name or not match:
                continue
            per_serving, servings = float(match.group(1)), float(match.group(2))
            if servings <= 0 or servings != int(servings):
                continue
            kcal = round(per_serving * servings)
            if kcal > 0:
                items.append(OfficialItem("全家", name, kcal, int(servings)))
    return items


def fetch_family_payload(timeout: float = 30.0) -> dict:
    """Load FamilyMart's catalogue the way its own page does, in a real browser.

    The API answers 403 to scripted clients and to headless Chrome alike; only a
    normal (headed) Chrome window gets through. So this opens one through WSLg,
    loads the public page, lets the page make its own catalogue call once, and
    closes. Decided by the repo owner on 2026-09-26; see docs/ops-pipeline.md.
    """
    from playwright.sync_api import sync_playwright

    # cron has no DISPLAY; WSLg serves :0.
    os.environ.setdefault("DISPLAY", ":0")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        try:
            page = browser.new_page()
            page.goto(FAMILY_PAGE, wait_until="networkidle", timeout=timeout * 1000)
            status, body = page.evaluate(
                """async (url) => {
                    const response = await fetch(url, {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({MEMBER: 'N', FILTER: []}),
                    });
                    return [response.status, await response.text()];
                }""",
                FAMILY_URL,
            )
        finally:
            browser.close()
    if status != 200:
        raise RuntimeError(f"FamilyMart catalogue returned HTTP {status}")
    return json.loads(body)


def fetch_all(delay: float = 1.0, timeout: float = 30.0) -> list[OfficialItem]:
    """Fetch both catalogues; raise if either comes back empty."""
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    seven: list[OfficialItem] = []
    for category in SEVEN_CATEGORIES:
        response = session.get(SEVEN_URL.format(category=category), timeout=timeout)
        response.raise_for_status()
        seven.extend(parse_seven_xml(response.content))
        time.sleep(delay)
    family = parse_family_list(fetch_family_payload(timeout))
    # An empty catalogue means the endpoint changed shape, not that every
    # product vanished; failing here keeps yesterday's cache untouched.
    for brand, items in (("7-11", seven), ("全家", family)):
        if not items:
            raise RuntimeError(f"{brand} catalogue returned no calorie rows")
    return seven + family


def load_official(path: Path = OFFICIAL_KCAL_PATH) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def merge_official(
    existing: list[dict[str, str]], fetched: Iterable[OfficialItem], today: str
) -> list[dict[str, str]]:
    """Add new rows, refresh seen rows, keep rows the catalogue no longer lists."""
    rows = {(row["brand"], row["official_name"]): dict(row) for row in existing}
    for item in fetched:
        key = (item.brand, item.official_name)
        row = rows.get(key) or {"brand": item.brand, "official_name": item.official_name, "first_seen": today}
        row.update(
            kcal=str(item.kcal),
            servings="" if item.servings is None else str(item.servings),
            last_seen=today,
        )
        rows[key] = row
    return [rows[key] for key in sorted(rows)]


def write_official(rows: list[dict[str, str]], path: Path = OFFICIAL_KCAL_PATH) -> None:
    # BOM + CRLF like the other label caches, so Excel opens it and diffs stay stable.
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8-sig", newline="", dir=path.parent, suffix=".tmp", delete=False
    )
    try:
        with handle:
            writer = csv.DictWriter(handle, fieldnames=OFFICIAL_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(handle.name, path)
    except Exception:
        Path(handle.name).unlink(missing_ok=True)
        raise


def load_matches(path: Path = KCAL_MATCHES_PATH) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    matches = {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if row["verdict"] not in VERDICTS:
                raise ValueError(f"invalid kcal match verdict for {row['product_id']}: {row['verdict']!r}")
            matches[row["product_id"]] = row
    return matches


class KcalLookup:
    def __init__(self, official: list[dict[str, str]], matches: dict[str, dict[str, str]]) -> None:
        self._by_name: dict[tuple[str, str], int] = {}
        normalized: dict[tuple[str, str], set[int]] = {}
        for row in official:
            kcal = int(row["kcal"])
            self._by_name[(row["brand"], row["official_name"])] = kcal
            normalized.setdefault((row["brand"], normalize_name(row["official_name"])), set()).add(kcal)
        # Two catalogue rows that normalise to one name with different calories
        # (two sizes of the same dish) cannot be told apart by name: no answer.
        self._exact = {key: next(iter(values)) for key, values in normalized.items() if len(values) == 1}
        self._matches = matches

    def kcal_for(self, brand: str, product_name: str) -> int | None:
        match = self._matches.get(f"{brand}::{product_name}")
        if match is not None:
            if match["verdict"] != "same":
                return None
            return self._by_name.get((brand, match["official_name"]))
        return self._exact.get((brand, normalize_name(product_name)))


def load_lookup() -> KcalLookup:
    return KcalLookup(load_official(), load_matches())
