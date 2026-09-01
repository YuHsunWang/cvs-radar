"""Compliant crawler for FamilyMart Taiwan's public food-safety catalogue."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BASE_URL = "https://foodsafety.family.com.tw/Web_FFD_2022/"
ALLOWED_HOST = "foodsafety.family.com.tw"
ALLOWED_IMAGE_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}


@dataclass
class NutritionValue:
    """A normalized nutrient measurement while retaining the source label."""

    value: float | None
    unit: str | None
    raw_text: str | None


@dataclass
class FamilyFoodProduct:
    product_id: str
    name: str
    detail_url: str
    image_urls: list[str] = field(default_factory=list)
    serving_size: NutritionValue | None = None
    servings_per_container: NutritionValue | None = None
    calories: NutritionValue | None = None
    protein: NutritionValue | None = None
    fat: NutritionValue | None = None
    saturated_fat: NutritionValue | None = None
    trans_fat: NutritionValue | None = None
    carbohydrates: NutritionValue | None = None
    sugar: NutritionValue | None = None
    sodium: NutritionValue | None = None
    ingredients: str | None = None
    allergens: str | None = None
    crawled_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


NUTRIENT_NAMES = {
    "熱量": "calories", "蛋白質": "protein", "脂肪": "fat", "總脂肪": "fat",
    "飽和脂肪": "saturated_fat", "反式脂肪": "trans_fat",
    "碳水化合物": "carbohydrates", "糖": "sugar", "鈉": "sodium",
}
UNIT_ALIASES = {"公克": "g", "克": "g", "毫克": "mg", "大卡": "kcal", "千卡": "kcal", "份": "serving"}


def parse_measurement(raw: Any, default_unit: str | None = None) -> NutritionValue:
    """Parse a displayed measurement; missing/unparseable values remain ``None``."""
    text = None if raw is None else str(raw).strip()
    if not text or text in {"-", "--", "N/A", "未提供"}:
        return NutritionValue(None, None, text or None)
    normalized = text.replace(",", "").replace("％", "%")
    match = re.search(r"(-?\d+(?:\.\d+)?)\s*(大卡|千卡|kcal|公克|克|g|毫克|mg|份)?", normalized, re.I)
    if not match:
        return NutritionValue(None, None, text)
    unit = match.group(2) or default_unit
    unit = UNIT_ALIASES.get(unit, unit.lower() if unit else None)
    return NutritionValue(float(match.group(1)), unit, text)


def _pairs_from_html(soup: BeautifulSoup) -> dict[str, str]:
    pairs: dict[str, str] = {}
    for row in soup.select("tr"):
        cells = row.find_all(["th", "td"])
        if len(cells) >= 2:
            pairs[cells[0].get_text(" ", strip=True)] = cells[-1].get_text(" ", strip=True)
    for term in soup.find_all("dt"):
        value = term.find_next_sibling("dd")
        if value:
            pairs[term.get_text(" ", strip=True)] = value.get_text(" ", strip=True)
    return pairs


def _allowed_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and parsed.hostname == ALLOWED_HOST and parsed.port in {None, 80, 443}


def _absolute(url: str, base_url: str = BASE_URL) -> str:
    result = urljoin(base_url, url)
    if not _allowed_url(result):
        raise ValueError(f"off-site URL refused: {result}")
    return result


def parse_list_html(html: str, page_url: str) -> tuple[list[dict[str, str]], str | None]:
    soup = BeautifulSoup(html, "html.parser")
    products: list[dict[str, str]] = []
    for anchor in soup.find_all("a", href=True):
        href = str(anchor["href"])
        if not re.search(r"(?:detail|product|foods?)[^?#]*/?\d+|/results/detail", href, re.I):
            continue
        try:
            url = _absolute(href, page_url)
        except ValueError:
            continue
        product_id = str(anchor.get("data-id") or _id_from_url(url) or "")
        name = anchor.get_text(" ", strip=True) or str(anchor.get("title") or "")
        products.append({"product_id": product_id, "name": name, "detail_url": url})
    next_url = None
    candidate = soup.find("a", rel=lambda value: value and "next" in value) or soup.find(
        "a", string=re.compile(r"下一頁|下頁|Next", re.I)
    )
    if candidate and candidate.get("href"):
        next_url = _absolute(str(candidate["href"]), page_url)
    return products, next_url


def _id_from_url(url: str) -> str | None:
    matches = re.findall(r"(?:^|/)(\d+)(?:/)?$", urlparse(url).path)
    return matches[-1] if matches else None


def parse_api_response(payload: Any, base_url: str = BASE_URL) -> tuple[list[dict[str, str]], str | None]:
    """Parse common JSON envelope shapes without depending on presentation CSS."""
    if isinstance(payload, str):
        payload = json.loads(payload)
    if not isinstance(payload, dict):
        raise ValueError("API response must be an object")
    data = payload.get("data", payload)
    if isinstance(data, dict):
        rows = next((data[k] for k in ("items", "products", "results", "list") if isinstance(data.get(k), list)), [])
    elif isinstance(data, list):
        rows = data
    else:
        rows = []
    products = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        pid = row.get("product_id") or row.get("productId") or row.get("id") or row.get("ID")
        href = row.get("detail_url") or row.get("detailUrl") or row.get("url") or row.get("href")
        if pid is None and not href:
            continue
        href = href or f"detail/{pid}"
        products.append({
            "product_id": str(pid or _id_from_url(str(href)) or ""),
            "name": str(row.get("name") or row.get("productName") or row.get("title") or ""),
            "detail_url": _absolute(str(href), base_url),
        })
    next_value = data.get("next") or data.get("nextPageUrl") if isinstance(data, dict) else None
    return products, _absolute(str(next_value), base_url) if next_value else None


def parse_product_html(html: str, detail_url: str, product_id: str | None = None) -> FamilyFoodProduct:
    soup = BeautifulSoup(html, "html.parser")
    pairs = _pairs_from_html(soup)
    heading = soup.find(["h1", "h2"]) or soup.find("meta", attrs={"property": "og:title"})
    name = (heading.get("content") if heading and heading.name == "meta" else heading.get_text(" ", strip=True)) if heading else ""
    images: list[str] = []
    for node in soup.select('img[src], meta[property="og:image"][content]'):
        source = node.get("src") or node.get("content")
        try:
            absolute = _absolute(str(source), detail_url)
        except ValueError:
            continue
        if absolute not in images:
            images.append(absolute)
    product = FamilyFoodProduct(str(product_id or _id_from_url(detail_url) or ""), str(name), detail_url, images)
    for label, raw in pairs.items():
        compact = re.sub(r"\s+", "", label)
        if "每一份量" in compact or "每份" in compact and "含" not in compact:
            product.serving_size = parse_measurement(raw, "g")
        elif "本包裝含" in compact or "每包裝含" in compact:
            product.servings_per_container = parse_measurement(raw, "serving")
        elif "原料" in compact or "成分" in compact:
            product.ingredients = raw or None
        elif "過敏原" in compact:
            product.allergens = raw or None
        else:
            for zh, attr in sorted(NUTRIENT_NAMES.items(), key=lambda item: -len(item[0])):
                if zh in compact:
                    setattr(product, attr, parse_measurement(raw, "kcal" if attr == "calories" else "mg" if attr == "sodium" else "g"))
                    break
    return product


class FamilyFoodCrawler:
    def __init__(self, *, request_delay: float = 1.0, timeout: float = 15.0, retries: int = 2,
                 user_agent: str = "CVS-Radar-FamilyFoodCrawler/1.0 (research; contact repository owner)",
                 session: requests.Session | None = None) -> None:
        if request_delay < 0 or timeout <= 0 or retries < 0:
            raise ValueError("invalid request settings")
        self.request_delay, self.timeout, self.retries = request_delay, timeout, retries
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": user_agent, "Accept": "text/html,application/json"})
        self._last_request_at: float | None = None

    def _get(self, url: str) -> requests.Response:
        url = _absolute(url)
        error: Exception | None = None
        for attempt in range(self.retries + 1):
            if attempt:
                time.sleep(self.request_delay * (2 ** (attempt - 1)))
            if self._last_request_at is not None:
                time.sleep(max(0.0, self.request_delay - (time.monotonic() - self._last_request_at)))
            try:
                response = self.session.get(url, timeout=self.timeout)
                self._last_request_at = time.monotonic()
                response.raise_for_status()
                return response
            except requests.RequestException as exc:
                error = exc
                logger.warning("request failed (%d/%d) %s: %s", attempt + 1, self.retries + 1, url, exc)
        assert error is not None
        raise error

    def crawl(self, start_page: int = 1, max_pages: int | None = None) -> list[FamilyFoodProduct]:
        url = _absolute(f"results/{start_page}")
        products: list[FamilyFoodProduct] = []
        seen: set[str] = set()
        pages = 0
        while max_pages is None or pages < max_pages:
            response = self._get(url)
            try:
                if "json" in response.headers.get("Content-Type", "").lower():
                    items, next_url = parse_api_response(response.json(), url)
                else:
                    items, next_url = parse_list_html(response.text, url)
            except (ValueError, json.JSONDecodeError) as exc:
                raise RuntimeError(f"cannot parse list page {url}: {exc}") from exc
            pages += 1
            if not items:
                break
            new_ids = 0
            for item in items:
                key = item["product_id"] or item["detail_url"]
                if key in seen:
                    continue
                seen.add(key)
                new_ids += 1
                try:
                    detail = self._get(item["detail_url"])
                    product = parse_product_html(detail.text, item["detail_url"], item["product_id"])
                    if not product.name:
                        product.name = item["name"]
                    products.append(product)
                except Exception as exc:
                    logger.error("product parse failed for %s: %s", item["detail_url"], exc)
            if new_ids == 0 or not next_url:
                break
            url = _absolute(next_url)
        return products

    def download_images(self, product: FamilyFoodProduct, image_dir: str | Path,
                        max_bytes: int = 5 * 1024 * 1024) -> list[Path]:
        directory = Path(image_dir)
        directory.mkdir(parents=True, exist_ok=True)
        saved = []
        safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", product.product_id) or "unknown"
        for url in product.image_urls:
            response = self._get(url)
            content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
            if content_type not in ALLOWED_IMAGE_TYPES:
                logger.warning("image rejected due to Content-Type %s: %s", content_type, url)
                continue
            content = response.content
            if len(content) > max_bytes:
                logger.warning("image exceeds %d bytes: %s", max_bytes, url)
                continue
            digest = hashlib.sha256(content).hexdigest()[:16]
            path = directory / f"{safe_id}-{digest}{ALLOWED_IMAGE_TYPES[content_type]}"
            path.write_bytes(content)
            saved.append(path)
        return saved
