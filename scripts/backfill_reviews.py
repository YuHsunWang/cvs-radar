#!/usr/bin/env python3
"""Refetch stored PTT articles whose author review text was not parsed."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from cvs_radar.backfill import backfill_missing_reviews, read_jsonl, write_jsonl_atomic
from cvs_radar.crawler import PttCrawler
from cvs_radar.store import DEFAULT_STORE_PATH


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", default=DEFAULT_STORE_PATH)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--delay", type=float, default=0.5)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    path = Path(args.store)
    rows = read_jsonl(path)
    if not rows:
        raise FileNotFoundError(f"no stored posts found at {path}")

    crawler = PttCrawler(request_delay_sec=args.delay)
    updated_rows, attempted, updated = backfill_missing_reviews(
        rows,
        crawler._get,  # noqa: SLF001 - reuse crawler retry, cookie, host and timeout policy
        limit=args.limit,
    )
    if updated:
        write_jsonl_atomic(updated_rows, path)
    print(f"review backfill attempted={attempted} updated={updated} total={len(rows)}")


if __name__ == "__main__":
    main()
