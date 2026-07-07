"""CVS Radar package."""

from __future__ import annotations

__version__ = "0.2.0"

from .service import ProductQuery, query_products, list_brands, select_reviews

__all__ = ["ProductQuery", "query_products", "list_brands", "select_reviews"]
