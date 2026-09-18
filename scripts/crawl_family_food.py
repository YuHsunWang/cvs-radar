#!/usr/bin/env python3
"""Export FamilyMart's public food-safety catalogue as UTF-8 JSONL."""

import argparse
import json
import logging
from pathlib import Path

from cvs_radar.family_food_crawler import FamilyFoodCrawler


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-page", type=int, default=1)
    parser.add_argument("--max-pages", type=int)
    parser.add_argument("--output", type=Path, default=Path("data/family_food/products.jsonl"))
    parser.add_argument("--request-delay", type=float, default=1.0)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--download-images", action="store_true")
    parser.add_argument("--image-dir", type=Path, default=Path("data/family_food/images"))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    crawler = FamilyFoodCrawler(request_delay=args.request_delay, timeout=args.timeout)
    try:
        products = crawler.crawl(args.start_page, args.max_pages)
    except Exception:
        logging.exception("list crawl failed")
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as output:
        for product in products:
            output.write(json.dumps(product.to_dict(), ensure_ascii=False) + "\n")
            if args.download_images:
                crawler.download_images(product, args.image_dir)
    logging.info("wrote %d products to %s", len(products), args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
