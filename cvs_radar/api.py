"""FastAPI endpoints for CVS Radar service queries."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date
from typing import Literal

from fastapi import FastAPI, HTTPException, Query

from .app_helpers import build_product_query, load_posts
from .service import (
    ProductQuery,
    ProductQueryResult,
    brand_summaries_from_reports,
    filter_reports,
    list_brands,
    query_products,
)
from .store import load_results

app = FastAPI(title="CVS Radar API", version="0.1.0")

PRECOMPUTED_TIME_FILTER_NOTE = "precomputed data does not support time filtering"


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/brands")
def brands(
    source: Literal["demo", "crawl", "stored", "results"] = "demo",
    crawl_pages: int = Query(5, ge=1, le=50),
    start_date: date | None = None,
    end_date: date | None = None,
    recent_days: int | None = Query(None, ge=0),
) -> list[dict[str, object]]:
    try:
        if source == "results":
            loaded = load_results()
            if loaded is None:
                raise ValueError("precomputed results not found")
            reports, _profiles = loaded
            return [asdict(summary) for summary in brand_summaries_from_reports(reports)]

        posts = load_posts(
            source,
            crawl_pages=crawl_pages,
            start_date=start_date,
            end_date=end_date,
            recent_days=recent_days,
        )
        summaries = list_brands(
            posts,
            start_date=start_date,
            end_date=end_date,
            recent_days=recent_days,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return [asdict(summary) for summary in summaries]


@app.get("/products")
def products(
    source: Literal["demo", "crawl", "stored", "results"] = "demo",
    crawl_pages: int = Query(5, ge=1, le=50),
    brand: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    recent_days: int | None = Query(None, ge=0),
    min_score: float | None = Query(None, ge=0),
    min_n_eff: float | None = Query(None, ge=0),
    min_posts: int | None = Query(None, ge=0),
    min_comments: int | None = Query(None, ge=0),
    limit: int | None = Query(None, ge=0),
    internal: bool = False,
) -> dict[str, object]:
    try:
        query = build_product_query(
            brand=brand,
            start_date=start_date,
            end_date=end_date,
            recent_days=recent_days,
            min_score=min_score,
            min_n_eff=min_n_eff,
            min_posts=min_posts,
            min_comments=min_comments,
            limit=limit,
            internal=internal,
        )
        if source == "results":
            loaded = load_results()
            if loaded is None:
                raise ValueError("precomputed results not found")
            reports, _profiles = loaded
            result = _query_precomputed_reports(reports, query).to_dict()
            result["note"] = PRECOMPUTED_TIME_FILTER_NOTE
            return result

        posts = load_posts(
            source,
            crawl_pages=crawl_pages,
            start_date=start_date,
            end_date=end_date,
            recent_days=recent_days,
        )
        return query_products(posts, query).to_dict()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _query_precomputed_reports(reports, query: ProductQuery) -> ProductQueryResult:
    filtered = filter_reports(
        reports,
        brand=query.brand,
        min_score=query.min_score,
        min_n_eff=query.min_n_eff,
        min_posts=query.min_posts,
        min_comments=query.min_comments,
        limit=query.limit,
    )
    return ProductQueryResult(
        filters={
            "brand": query.brand,
            "start_date": str(query.start_date) if query.start_date else None,
            "end_date": str(query.end_date) if query.end_date else None,
            "recent_days": query.recent_days,
            "min_score": query.min_score,
            "min_n_eff": query.min_n_eff,
            "min_posts": query.min_posts,
            "min_comments": query.min_comments,
            "limit": query.limit,
            "internal": query.internal,
            "note": PRECOMPUTED_TIME_FILTER_NOTE,
        },
        brands=brand_summaries_from_reports(reports),
        reports=filtered,
    )
