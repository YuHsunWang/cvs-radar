"""Keep our own copy of every reviewed product photo in web/public/images.

The site used to hotlink each photo from imgur or the retailer, so a deleted or
hotlink-blocked original blanked the card. This saves each enabled photo in
data/labels/product_images.csv once, as a 640px WebP, and deletes saved copies
no enabled row points at any more (a takedown must take our copy down too).
A photo that fails to download keeps being served from its original URL.

Needs Pillow, so it runs on the cron machine, not in CI.
"""

from __future__ import annotations

import argparse
import io
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from web.product_images import IMAGES_DIR, load_product_images, local_image_name  # noqa: E402

MAX_BYTES = 20_000_000
SIZE = 640  # two pixels per CSS pixel on the 320px-wide card


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        # imgur answers a deleted image with a redirect to its "removed" placeholder.
        if "removed" in response.url:
            raise ValueError("original was removed")
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("image too large")
    return data


def to_webp(data: bytes) -> bytes:
    from PIL import Image, ImageOps

    image = Image.open(io.BytesIO(data))
    # Browsers honour EXIF orientation and each row's `rotate` was judged on that
    # view; WebP drops EXIF, so bake the orientation in first.
    image = ImageOps.exif_transpose(image)
    if image.mode not in ("RGB", "RGBA"):
        image = image.convert("RGBA" if "A" in image.getbands() or "transparency" in image.info else "RGB")
    image.thumbnail((SIZE, SIZE))
    out = io.BytesIO()
    image.save(out, "WEBP", quality=78, method=6)
    return out.getvalue()


def save(url: str, dest: Path) -> str | None:
    try:
        webp = to_webp(fetch(url))
    except Exception as error:  # one bad photo must not stop the rest
        return f"{url}: {type(error).__name__} {error}"
    tmp = dest.with_suffix(".tmp")
    tmp.write_bytes(webp)
    tmp.replace(dest)
    return None


def main() -> int:
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    wanted = {local_image_name(image["imageUrl"]): image["imageUrl"]
              for image in load_product_images(ROOT / "data" / "labels" / "product_images.csv").values()}
    removed = [path for path in IMAGES_DIR.glob("*.webp") if path.name not in wanted]
    for path in removed:
        path.unlink()
    todo = [(url, IMAGES_DIR / name) for name, url in wanted.items() if not (IMAGES_DIR / name).is_file()]
    with ThreadPoolExecutor(8) as pool:
        errors = [error for error in pool.map(lambda job: save(*job), todo) if error]
    for error in errors:
        print(f"[images] FAILED {error}", file=sys.stderr)
    print(f"[images] saved={len(todo) - len(errors)} failed={len(errors)} removed={len(removed)} total={len(wanted)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
