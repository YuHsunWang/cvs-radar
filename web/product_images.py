"""Manual image review table; never infer identity or scrape post images."""

from __future__ import annotations

import csv
import hashlib
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


IMAGE_FIELDS = (
    "product_id", "official_id", "source_kind", "source_page_url", "image_url",
    "identity_status", "rights_status", "enabled", "checked_at", "takedown_reason", "rotate",
)
# Clockwise degrees the page turns a photo so its package text reads upright.
ROTATIONS = {"0", "90", "180", "270"}
SOURCE_KINDS = {"official_retailer", "official_brand", "ptt"}
PTT_POST = re.compile(r"https://www\.ptt\.cc/bbs/CVS/M\.\d+\.A\.[0-9A-F]+\.html")
# Our own copy of each reviewed photo (scripts/download_product_images.py), so a
# deleted or hotlink-blocked original cannot blank a card. Served from web/public.
IMAGES_DIR = Path(__file__).resolve().parent / "public" / "images"
LOCAL_SRC = re.compile(r"images/[0-9a-f]{16}\.webp")


def local_image_name(image_url: str) -> str:
    return hashlib.sha256(image_url.encode()).hexdigest()[:16] + ".webp"


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
    if not isinstance(image, dict) or set(image) != {"imageUrl", "localSrc", "sourcePageUrl", "sourceKind", "rotate"}:
        return False
    return (
        isinstance(image["sourceKind"], str) and image["sourceKind"] in SOURCE_KINDS
        and (image["localSrc"] is None or (isinstance(image["localSrc"], str) and bool(LOCAL_SRC.fullmatch(image["localSrc"]))))
        and safe_https_url(image["imageUrl"])
        and safe_https_url(image["sourcePageUrl"])
        and (image["sourceKind"] != "ptt" or bool(PTT_POST.fullmatch(image["sourcePageUrl"])))
        and type(image["rotate"]) is int and str(image["rotate"]) in ROTATIONS
    )


def load_product_images(path: Path, images_dir: Path = IMAGES_DIR) -> dict[str, dict[str, Any]]:
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
            if row["rotate"] not in ROTATIONS:
                raise ValueError(f"invalid product image rotation at line {line}")
            if (
                row["enabled"] != "1" or row["identity_status"] != "verified"
                or row["rights_status"] != "verified" or row["takedown_reason"].strip()
                or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", row["checked_at"])
            ):
                continue
            local = local_image_name(row["image_url"])
            image = {
                "imageUrl": row["image_url"],
                # Not downloaded yet (e.g. approved since the last cron run): the original serves.
                "localSrc": f"images/{local}" if (images_dir / local).is_file() else None,
                "sourcePageUrl": row["source_page_url"],
                "sourceKind": row["source_kind"],
                "rotate": int(row["rotate"]),
            }
            if valid_image(image):
                images[product_id] = image
    return images
