"""LLM-labelled product names, cached by fingerprint.

The 商品名稱 field is free text: posters mix the real name with prices, coupon
names, gift thresholds and asides ("廣達香肉鬆飯糰/ 一起結帳不確定價格"). Deciding
what the product actually is, and which of several products a line refers to, is a
judgement call — the kind of thing rules keep losing to. This module lets an LLM
make that judgement once per distinct raw field and stores the answer, exactly the
way `sentiment.py` caches per-comment labels.

Downstream stays deterministic: the cache is a committed CSV, so a rebuild (and CI,
which cannot call an LLM) reads labels instead of re-deciding them. Rules remain the
fallback for anything not yet labelled.
"""

from __future__ import annotations

import csv
import hashlib
import re
import unicodedata
from pathlib import Path

PRODUCT_NAME_LABELS_PATH = "data/labels/product_name_labels.csv"

PROMPT_VERSION = "product-name-v1"

FIELDNAMES = (
    "fingerprint",
    "item_index",
    "brand",
    "title",
    "raw_name",
    "product_name",
    "price",
    "model",
    "prompt_version",
)


def _normalize_raw_name(text: str) -> str:
    s = unicodedata.normalize("NFKC", str(text or ""))
    s = s.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    s = re.sub(r"\s+", " ", s).strip()
    # The extractor drops the field's leading colon before doing anything else;
    # normalising it here too means posts that differ only by "：x" vs "： x"
    # share one label instead of each paying for its own.
    return re.sub(r"^[：:]+\s*", "", s).strip()


def product_name_fingerprint(brand: str, title: str, raw_name: str) -> str:
    """Build a stable identifier for one raw 商品名稱 field under one brand.

    Whitespace and full/half-width differences are normalised away so that two
    posts writing the same field slightly differently share a label.

    The post title is part of the key because the field alone does not identify
    the product. When a poster leaves 商品名稱 as bare noise ("：49"), every such
    post hashes identically, and one label then overwrites the rest — which merged
    這不是滷肉飯, 法朋蛋黃酥霜淇淋 and 維力炸醬拌麵堡 into 飛燕煉乳炸銀絲卷. The
    title is what the labeller reads to resolve those fields, so it belongs in the
    key that stores the answer.
    """
    normalized_brand = unicodedata.normalize("NFKC", str(brand or "")).strip()
    payload = "\x1f".join(
        (
            normalized_brand,
            _normalize_raw_name(title),
            _normalize_raw_name(raw_name),
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def product_name_fingerprint_v2(
    brand: str,
    title: str,
    raw_name: str,
    *,
    rule_guess: str = "",
    prompt_version: str = PROMPT_VERSION,
) -> str:
    """Fingerprint a raw 商品名稱 field over everything the labeller is shown.

    The exported row carries the rule engine's guess, and the labeller reads it —
    so a change to the extraction rules changes the question without changing the
    old key, leaving an answer that was given about a different guess. The prompt
    version is included for the same reason: a rewritten rubric must retire the
    answers produced under the old one.
    """
    payload = "\x1f".join(
        (
            unicodedata.normalize("NFKC", str(brand or "")).strip(),
            _normalize_raw_name(title),
            _normalize_raw_name(raw_name),
            _normalize_raw_name(rule_guess),
            str(prompt_version or ""),
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def format_rule_guess(items: list[tuple[str, int | None]]) -> str:
    """Render a rule-engine result the way the exported row shows it."""
    return " | ".join(f"{name}#{price if price is not None else ''}" for name, price in items)


def load_product_name_labels(
    path: str | Path = PRODUCT_NAME_LABELS_PATH,
) -> dict[str, list[tuple[str, int | None]]]:
    """Load labelled (name, price) items keyed by raw-field fingerprint.

    Rows sharing a fingerprint are one multi-product post; `item_index` keeps their
    order stable. A row whose product_name is blank marks the field as carrying no
    usable name, which is recorded as an empty item list so the caller can fall
    back to the post title rather than re-running the rules.
    """
    file_path = Path(path)
    if not file_path.exists():
        return {}

    collected: dict[str, list[tuple[int, str, int | None]]] = {}
    for row in _read_rows(file_path):
        fingerprint = str(row.get("fingerprint") or "").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
            continue
        name = _normalize_raw_name(row.get("product_name") or "")
        try:
            index = int(str(row.get("item_index") or "0").strip())
        except ValueError:
            continue
        collected.setdefault(fingerprint, [])
        if not name:
            continue
        collected[fingerprint].append((index, name, _parse_price(row.get("price"))))

    return {
        fingerprint: [(name, price) for _, name, price in sorted(items)]
        for fingerprint, items in collected.items()
    }


def _read_rows(file_path: Path) -> list[dict[str, str]]:
    with open(file_path, encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _parse_price(raw: str | None) -> int | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None
