"""Manual image review table; never infer identity or scrape post images."""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


IMAGE_FIELDS = (
    "product_id", "official_id", "source_kind", "source_page_url", "image_url",
    "identity_status", "rights_status", "enabled", "checked_at", "takedown_reason",
)
SOURCE_KINDS = {"official_retailer", "official_brand", "ptt"}
PTT_POST = re.compile(r"https://www\.ptt\.cc/bbs/CVS/M\.\d+\.A\.[0-9A-F]+\.html")


def safe_https_url(value: Any) -> bool:
    if not isinstance(value, str) or not value.startswith("https://"):
        return False
    if any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value):
        return False
    if "\\" in value or re.search(r"%(?:0[0-9a-f]|1[0-9a-f]|7f|5c)", value, re.I):
        return False
    try:
        url = urlsplit(value)
        # Deliberately accept only ordinary DNS hosts and the default HTTPS port.
        host = url.hostname or ""
        return (
            url.scheme == "https" and url.username is None and url.password is None
            and url.port in (None, 443)
            and bool(re.fullmatch(
                r"(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+"
                r"[a-zA-Z]{2,63}", host
            ))
            and not host.lower().endswith((".localhost", ".local", ".internal"))
        )
    except ValueError:
        return False


def valid_image(image: Any) -> bool:
    if image is None:
        return True
    if not isinstance(image, dict) or set(image) != {"imageUrl", "sourcePageUrl", "sourceKind"}:
        return False
    return (
        isinstance(image["sourceKind"], str) and image["sourceKind"] in SOURCE_KINDS
        and safe_https_url(image["imageUrl"])
        and safe_https_url(image["sourcePageUrl"])
        and (image["sourceKind"] != "ptt" or bool(PTT_POST.fullmatch(image["sourcePageUrl"])))
    )


def load_product_images(path: Path) -> dict[str, dict[str, str]]:
    """One retained row per exact product ID, including disabled/removal rows.

    Duplicate IDs abort the build regardless of row order or source. Operators
    review official sources first; there is no automatic PTT fallback.
    """
    images = {}
    seen = set()
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != list(IMAGE_FIELDS):
            raise ValueError("invalid product image manifest columns")
        for line, row in enumerate(reader, start=2):
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"invalid product image row at line {line}")
            product_id = row["product_id"]
            if not product_id or product_id != product_id.strip():
                raise ValueError(f"invalid product image ID at line {line}")
            if product_id in seen:
                raise ValueError(f"duplicate product image ID at line {line}")
            seen.add(product_id)
            if row["enabled"] not in {"0", "1"}:
                raise ValueError(f"invalid product image enabled flag at line {line}")
            if (
                row["enabled"] != "1" or row["identity_status"] != "verified"
                or row["rights_status"] != "verified" or row["takedown_reason"].strip()
                or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", row["checked_at"])
            ):
                continue
            image = {
                "imageUrl": row["image_url"],
                "sourcePageUrl": row["source_page_url"],
                "sourceKind": row["source_kind"],
            }
            if valid_image(image):
                images[product_id] = image
    return images
