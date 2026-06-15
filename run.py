#!/usr/bin/env python3
"""CLI 入口。

範例:
  python run.py --demo                 # 用離線樣本跑(無需網路)
  python run.py --demo --internal      # 額外顯示貢獻者與可疑分排行
  python run.py --crawl --pages 5      # 實際爬 PTT(需網路)
  python run.py --demo --json out.json # 輸出 JSON
"""
from __future__ import annotations

import argparse
import logging

from cvs_radar.pipeline import run_pipeline
from cvs_radar.reporting import render_json, render_suspicion, render_text


def main():
    ap = argparse.ArgumentParser(description="超商食物評價雷達 CVS Radar v0")
    source = ap.add_mutually_exclusive_group()
    source.add_argument("--demo", action="store_true", help="使用離線樣本資料(預設)")
    source.add_argument("--crawl", action="store_true", help="實際爬取 PTT CVS 板")
    ap.add_argument("--pages", type=int, default=5, help="爬取頁數")
    ap.add_argument("--brand", help="只顯示指定品牌")
    ap.add_argument("--min-score", type=float, help="只顯示公正分數大於等於此值的商品")
    ap.add_argument("--limit", type=int, help="最多顯示幾筆商品")
    ap.add_argument("--internal", action="store_true", help="顯示內部明細(貢獻者/可疑分)")
    ap.add_argument("--json", metavar="FILE", help="輸出 JSON 至檔案")
    ap.add_argument("--verbose", action="store_true", help="顯示爬蟲與解析日誌")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s:%(name)s:%(message)s",
    )

    if args.crawl:
        from cvs_radar.crawler import PttCrawler
        print(f"爬取 PTT CVS 板(最多 {args.pages} 頁)…")
        posts = PttCrawler().crawl(max_pages=args.pages)
        print(f"取得 {len(posts)} 篇商品文")
    else:
        from cvs_radar.sample_data import load_sample
        posts = load_sample()

    reports, profiles = run_pipeline(posts)
    if args.brand:
        reports = [r for r in reports if r.brand == args.brand]
    if args.min_score is not None:
        reports = [r for r in reports if r.fair_score is not None and r.fair_score >= args.min_score]
    if args.limit is not None:
        reports = reports[: max(0, args.limit)]

    print(render_text(reports, internal=args.internal))
    if args.internal:
        print("\n" + render_suspicion(profiles))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            f.write(render_json(reports, internal=args.internal))
        print(f"\nJSON 已輸出:{args.json}")


if __name__ == "__main__":
    main()
