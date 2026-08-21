"""LLM-labelled product categories, cached by fingerprint.

`categorize_product` decides a category by matching a hand-written keyword
whitelist against the product name. That works for the names somebody already
thought of and silently returns 其他 for everything else: the whitelist has no
bare 飯, 麵, 湯, 粥 or 茶, so 泰式打拋豬肉飯, 愛恨蔥蔥麵, 人參糯米雞湯 and
南非國寶茶 all landed in 其他 — 125 of 805 published products (2026-08-18), of
which essentially none were genuinely uncategorisable.

Naming a category from a product name is a judgement call about the long tail,
which is exactly what the other four label layers (product names, excerpts,
comment picks, grounding) already hand to an LLM and cache in a committed CSV.
This module is that layer for categories. Keywords stay as the fallback for
anything not yet labelled, so a rebuild — and CI, which cannot call an LLM —
stays deterministic.

Unlike `product_labels`, the fingerprint does NOT include the rule engine's
guess. The labeller is asked to read the product name and pick from a closed
list; the keyword guess adds nothing it cannot see for itself, and hashing it
into the key would throw away every label the moment somebody edits a keyword
in config.yaml.
"""

from __future__ import annotations

import csv
import hashlib
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

PRODUCT_CATEGORY_LABELS_PATH = "data/labels/product_category_labels.csv"

# Anchored to the repo, not the working directory: web/build_data.py runs with
# its own directory as cwd, and a relative default silently reads no labels
# there — the publish step would fall back to keywords for every product.
DEFAULT_LABELS_PATH = Path(__file__).resolve().parent.parent / PRODUCT_CATEGORY_LABELS_PATH

PROMPT_VERSION = "product-category-v1"

# The closed vocabulary. `web/lib/data.ts` groups these into the seven filter
# chips the site shows; a category outside this list renders as 其他 there, so
# adding one is a frontend change too, not just a labelling decision.
CATEGORIES = (
    "便當",
    "鹹食",
    "泡麵",
    "麵包",
    "甜點",
    "冰品",
    "飲料",
    "乳品",
    "零食",
    "周邊",
    "其他",
)

FIELDNAMES = (
    "fingerprint",
    "brand",
    "product_name",
    "rule_guess",
    "category",
    "model",
    "prompt_version",
)


def _normalize(text: str) -> str:
    s = unicodedata.normalize("NFKC", str(text or ""))
    s = s.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    return re.sub(r"\s+", " ", s).strip()


def product_category_fingerprint(
    brand: str,
    product_name: str,
    *,
    prompt_version: str = PROMPT_VERSION,
) -> str:
    """Build a stable identifier for one product under one brand.

    The brand is part of the key because the same name can be a different thing
    at a different chain, and the prompt version is part of it because a
    rewritten rubric must retire the answers given under the old one.
    """
    payload = "\x1f".join(
        (
            _normalize(brand),
            _normalize(product_name),
            str(prompt_version or ""),
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_product_category_labels(
    path: str | Path = DEFAULT_LABELS_PATH,
) -> dict[str, str]:
    """Load labelled categories keyed by product fingerprint.

    Rows carrying a category outside `CATEGORIES` are dropped rather than
    trusted: an unknown category would reach the frontend as 其他 anyway, and
    falling back to the keyword rule is the more useful answer.
    """
    file_path = Path(path)
    if not file_path.exists():
        return {}

    labels: dict[str, str] = {}
    with open(file_path, encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            fingerprint = str(row.get("fingerprint") or "").strip().lower()
            if not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
                continue
            category = _normalize(row.get("category") or "")
            if category not in CATEGORIES:
                continue
            labels[fingerprint] = category
    return labels


@lru_cache(maxsize=1)
def _cached_labels() -> dict[str, str]:
    return load_product_category_labels()


def resolve_category(
    brand: str,
    product_name: str,
    *,
    labels: dict[str, str] | None = None,
    fallback: str = "",
) -> str:
    """Return the labelled category, or fall back to the keyword rule.

    `fallback` is for callers that already hold a rule-derived category (a
    stored report, say) and want to avoid recomputing it; leave it blank to let
    the keyword engine decide.
    """
    if labels is None:
        labels = _cached_labels()
    fingerprint = product_category_fingerprint(brand, product_name)
    labelled = labels.get(fingerprint)
    if labelled:
        return labelled
    if fallback:
        return fallback
    # Imported here rather than at module scope: the scoring package is the
    # heavier import and only this fallback path needs it.
    from .scoring.identity import categorize_product

    return categorize_product(product_name)
