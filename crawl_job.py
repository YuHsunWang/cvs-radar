#!/usr/bin/env python3
"""Scheduled crawl job -- run standalone or via cron.

Usage:
    # 手動執行
    python crawl_job.py

    # 指定頁數和存檔路徑
    python crawl_job.py --pages 10 --store data/posts.jsonl

    # cron 每天早上 8 點跑（加到 crontab -e）
    # 0 8 * * * cd /path/to/cvs-radar && .venv/bin/python crawl_job.py >> logs/crawl.log 2>&1
"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime

from cvs_radar.crawler import PttCrawler
from cvs_radar.store import DEFAULT_STORE_PATH, save_posts, store_stats


def main() -> None:
    parser = argparse.ArgumentParser(description="CVS Radar scheduled crawl job")
    parser.add_argument("--pages", type=int, default=5, help="Number of PTT list pages to crawl (default: 5)")
    parser.add_argument("--store", default=DEFAULT_STORE_PATH, help=f"JSONL store path (default: {DEFAULT_STORE_PATH})")
    parser.add_argument("--recent-days", type=int, default=None, help="Only keep posts from recent N days")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger = logging.getLogger("crawl_job")

    logger.info("Starting crawl: pages=%d, store=%s", args.pages, args.store)
    start = datetime.now()

    try:
        crawler = PttCrawler()
        posts = crawler.crawl(
            max_pages=args.pages,
            recent_days=args.recent_days,
        )
    except Exception:
        logger.exception("Crawl failed")
        raise

    new_count = save_posts(posts, args.store)
    elapsed = (datetime.now() - start).total_seconds()
    stats = store_stats(args.store)

    logger.info(
        "Crawl complete: fetched=%d, new=%d, elapsed=%.1fs", len(posts), new_count, elapsed
    )
    print(
        f"[{datetime.now().isoformat(sep=' ', timespec='seconds')}] "
        f"crawled={len(posts)} new={new_count} "
        f"store_total={stats['post_count']} posts / {stats['comment_count']} comments "
        f"({elapsed:.1f}s)"
    )


if __name__ == "__main__":
    main()
