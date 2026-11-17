"""List photo candidates for products that have no image yet.

Writes a review queue only. It never touches data/labels/product_images.csv, so
nothing goes live without a human check (owner decision 2026-11-04/11-17: picks
can show the wrong item, be sideways, or be a shared photo).
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

URL_RE = re.compile(r"https?://[^\s\"'<>()（）]+")
IMAGE_EXT_RE = re.compile(r"\.(?:jpe?g|png|webp|gif)$", re.IGNORECASE)
IMAGE_HOSTS = ("imgur.com/",)
DEFAULT_OUT = Path.home() / ".cache" / "cvs-radar" / "image-candidates.csv"


def image_urls(text: str) -> list[tuple[str, str]]:
    """Return (url, nearby text) for each image link in a post body, in order."""
    found = []
    for m in URL_RE.finditer(text or ""):
        url = m.group(0)
        if not (IMAGE_EXT_RE.search(url) or any(h in url for h in IMAGE_HOSTS)):
            continue
        near = text[max(0, m.start() - 40): m.end() + 40]
        found.append((url, " ".join(near.split())))
    return found


def collect(posts_path: Path, data_path: Path, manifest_path: Path) -> list[dict]:
    products = json.loads(data_path.read_text(encoding="utf-8"))["products"]
    with manifest_path.open(encoding="utf-8-sig", newline="") as f:
        decided = {row["product_id"] for row in csv.DictReader(f)}
    todo = [p for p in products if not p.get("image") and p["id"] not in decided]
    wanted = {url for p in todo for url in p.get("postUrls") or []}

    bodies = {}
    with posts_path.open(encoding="utf-8") as f:
        for line in f:
            post = json.loads(line)
            if post.get("url") in wanted:
                bodies[post["url"]] = post.get("review_text") or ""

    rows = []
    for p in todo:
        for post_url in p.get("postUrls") or []:
            for url, near in image_urls(bodies.get(post_url, "")):
                rows.append({"product_id": p["id"], "post_url": post_url,
                             "image_url": url, "nearby_text": near})
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--posts", type=Path, default=Path("data/posts.jsonl"))
    ap.add_argument("--data", type=Path, default=Path("web/public/data.json"))
    ap.add_argument("--manifest", type=Path, default=Path("data/labels/product_images.csv"))
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    rows = collect(args.posts, args.data, args.manifest)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["product_id", "post_url", "image_url", "nearby_text"])
        w.writeheader()
        w.writerows(rows)
    print(f"image candidates: {len({r['product_id'] for r in rows})} products, "
          f"{len(rows)} photos -> {args.out}")


if __name__ == "__main__":
    main()
