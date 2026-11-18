"""List photo candidates for products that have no image yet.

Opens each product's PTT article, because data/posts.jsonl keeps only the
review field and authors often put photos above or below it. Every non-PTT
link in the article body is listed, including photo pages (postimg.cc) and
short links (myppt.cc); the reviewer opens them.

Writes a review queue only. It never touches data/labels/product_images.csv, so
nothing goes live without a review (owner decision 2026-11-04/11-17: picks
can show the wrong item, be sideways, or be a shared photo).
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

URL_RE = re.compile(r"https?://[^\s\"'<>()（）]+")
CACHE = Path.home() / ".cache" / "cvs-radar"
DEFAULT_OUT = CACHE / "image-candidates.csv"
LINK_CACHE = CACHE / "ptt-article-links.json"


def article_links(text: str) -> list[tuple[str, str]]:
    """Return (url, nearby text) for each non-PTT link in an article body."""
    body = (text or "").rsplit("\n--\n", 1)[0]  # drop the signature
    found = []
    for m in URL_RE.finditer(body):
        url = m.group(0)
        if "ptt.cc" in url or any(url == u for u, _ in found):
            continue
        near = body[max(0, m.start() - 40): m.end() + 40]
        found.append((url, " ".join(near.split())))
    return found


def fetch_body(session, url: str) -> str:
    from bs4 import BeautifulSoup

    from cvs_radar.parser import _body_text_without_pushes

    resp = session.get(url, timeout=10)
    resp.raise_for_status()
    return _body_text_without_pushes(BeautifulSoup(resp.text, "html.parser"))


def todo_products(data_path: Path, manifest_path: Path) -> list[dict]:
    products = json.loads(data_path.read_text(encoding="utf-8"))["products"]
    with manifest_path.open(encoding="utf-8-sig", newline="") as f:
        decided = {row["product_id"] for row in csv.DictReader(f)}
    return [p for p in products if not p.get("image") and p["id"] not in decided]


def collect(todo: list[dict], links_for) -> list[dict]:
    rows = []
    for p in todo:
        for post_url in p.get("postUrls") or []:
            for url, near in links_for(post_url):
                rows.append({"product_id": p["id"], "post_url": post_url,
                             "image_url": url, "nearby_text": near})
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", type=Path, default=Path("web/public/data.json"))
    ap.add_argument("--manifest", type=Path, default=Path("data/labels/product_images.csv"))
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--delay", type=float, default=1.0, help="seconds between PTT requests")
    args = ap.parse_args()

    import requests

    from cvs_radar.config import CRAWL

    session = requests.Session()
    session.headers["User-Agent"] = str(CRAWL["user_agent"])
    session.cookies.set("over18", "1", domain="www.ptt.cc")
    try:
        cache = json.loads(LINK_CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    failed = 0

    def links_for(post_url: str) -> list:
        nonlocal failed
        if post_url not in cache:  # articles rarely change; fetch each once
            try:
                cache[post_url] = article_links(fetch_body(session, post_url))
            except requests.RequestException:
                failed += 1
                return []
            time.sleep(args.delay)
        return cache[post_url]

    rows = collect(todo_products(args.data, args.manifest), links_for)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    LINK_CACHE.parent.mkdir(parents=True, exist_ok=True)
    LINK_CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    with args.out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["product_id", "post_url", "image_url", "nearby_text"])
        w.writeheader()
        w.writerows(rows)
    print(f"image candidates: {len({r['product_id'] for r in rows})} products, "
          f"{len(rows)} links, {failed} articles failed -> {args.out}")


if __name__ == "__main__":
    main()
