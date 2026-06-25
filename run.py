#!/usr/bin/env python3
"""Command line entry point for CVS Radar."""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from cvs_radar.pipeline import run_pipeline
from cvs_radar.reporting import render_json, render_suspicion, render_text
from cvs_radar.service import BrandSummary, filter_reports, list_brands
from cvs_radar.filters import build_time_window


def main() -> None:
    parser = argparse.ArgumentParser(description="CVS Radar product scoring")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--demo", action="store_true", help="Use bundled sample data")
    source.add_argument("--crawl", action="store_true", help="Crawl PTT CVS")
    source.add_argument("--stored", action="store_true", help="Use stored crawl data from JSONL")
    source.add_argument("--results", action="store_true", help="Use precomputed results (fastest)")

    parser.add_argument("--pages", type=_non_negative_int, default=5, help="PTT list pages to crawl")
    parser.add_argument("--start-date", help="Filter posts/comments from this date or datetime, e.g. 2026-06-01")
    parser.add_argument("--end-date", help="Filter posts/comments through this date or datetime, e.g. 2026-06-15")
    parser.add_argument("--recent-days", type=_non_negative_int, help="Filter posts/comments from the last N days")
    parser.add_argument("--list-brands", action="store_true", help="List brands available in the selected data")
    parser.add_argument("--brand", help="Only show this brand")
    parser.add_argument("--min-score", type=_non_negative_float, help="Only keep products with fair_score >= this value")
    parser.add_argument("--min-n-eff", type=_non_negative_float, help="Only keep products with n_eff >= this value")
    parser.add_argument("--min-posts", type=_non_negative_int, help="Only keep products with at least this many posts")
    parser.add_argument("--min-comments", type=_non_negative_int, help="Only keep products with at least this many comments")
    parser.add_argument("--limit", type=_non_negative_int, help="Maximum number of ranked products to show")
    parser.add_argument("--internal", action="store_true", help="Include internal contributor/suspicion details")
    parser.add_argument("--json", metavar="FILE", help="Write JSON output to this file")
    parser.add_argument("--verbose", action="store_true", help="Enable crawler debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s:%(name)s:%(message)s",
    )

    effective_now = datetime.now() if args.recent_days is not None else None

    try:
        build_time_window(
            start_date=args.start_date,
            end_date=args.end_date,
            recent_days=args.recent_days,
            now=effective_now,
        )
    except ValueError as exc:
        parser.error(str(exc))

    posts = None
    reports = None
    profiles = None
    if args.results:
        from cvs_radar.store import load_results

        loaded = load_results()
        if loaded is None:
            parser.error("No precomputed results found. Run crawl_job.py first.")
        reports, profiles = loaded
    else:
        posts = _load_posts(args, now=effective_now)

    if args.list_brands:
        if reports is not None:
            summaries = _brand_summaries_from_reports(reports)
        else:
            summaries = list_brands(
                posts,
                start_date=args.start_date,
                end_date=args.end_date,
                recent_days=args.recent_days,
                now=effective_now,
            )
        print(_render_brand_summaries(summaries))
        if args.json:
            _write_text_file(args.json, json.dumps([asdict(item) for item in summaries], ensure_ascii=False, indent=2))
            print(f"\nJSON written to {args.json}")
        return

    if reports is None:
        reports, profiles = run_pipeline(
            posts,
            start_date=args.start_date,
            end_date=args.end_date,
            recent_days=args.recent_days,
            now=effective_now,
        )
    reports = filter_reports(
        reports,
        brand=args.brand,
        min_score=args.min_score,
        min_n_eff=args.min_n_eff,
        min_posts=args.min_posts,
        min_comments=args.min_comments,
        limit=args.limit,
    )

    print(render_text(reports, internal=args.internal))
    if args.internal:
        print("\n" + render_suspicion(profiles))
    if args.json:
        _write_text_file(args.json, render_json(reports, internal=args.internal))
        print(f"\nJSON written to {args.json}")


def _load_posts(args: argparse.Namespace, *, now: datetime | None = None):
    if args.stored:
        from cvs_radar.store import load_posts as load_stored

        posts = load_stored()
        print(f"Loaded {len(posts)} posts from store")
        return posts

    if args.crawl:
        from cvs_radar.crawler import PttCrawler

        print(f"Crawling PTT CVS, pages={args.pages}")
        posts = PttCrawler().crawl(
            max_pages=args.pages,
            start_date=args.start_date,
            end_date=args.end_date,
            recent_days=args.recent_days,
            now=now,
        )
        print(f"Loaded {len(posts)} posts")
        return posts

    from cvs_radar.sample_data import load_sample

    return load_sample()


def _render_brand_summaries(summaries) -> str:
    if not summaries:
        return "No brands found in selected data."
    lines = ["Brands in selected data:"]
    lines.extend(
        f"- {item.brand}: products={item.product_count}, posts={item.post_count}, comments={item.comment_count}"
        for item in summaries
    )
    return "\n".join(lines)


def _brand_summaries_from_reports(reports) -> list[BrandSummary]:
    rows = {}
    for report in reports:
        row = rows.setdefault(
            report.brand,
            {"products": 0, "post_count": 0, "comment_count": 0},
        )
        row["products"] += 1
        row["post_count"] += report.n_posts
        row["comment_count"] += report.n_comments
    summaries = [
        BrandSummary(
            brand=brand,
            product_count=values["products"],
            post_count=values["post_count"],
            comment_count=values["comment_count"],
        )
        for brand, values in rows.items()
    ]
    summaries.sort(key=lambda item: (-item.product_count, -item.post_count, item.brand))
    return summaries


def _non_negative_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid integer value: {value!r}") from None
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return parsed


def _non_negative_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid number value: {value!r}") from None
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return parsed


def _write_text_file(path: str, content: str) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()
