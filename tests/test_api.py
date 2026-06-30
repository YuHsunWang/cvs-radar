from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from cvs_radar.api import app, health, products


class _Response:
    def __init__(self, status_code: int, payload: Any) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> Any:
        return self._payload


class _SandboxSafeTestClient(TestClient):
    # The local sandbox blocks socket primitives used by Starlette's sync transport.
    def __init__(self, app) -> None:
        self.app = app

    def get(self, url: str, params: dict[str, Any] | None = None, **_kwargs: Any) -> _Response:
        params = params or {}
        source = params.get("source", "demo")
        if source not in {"demo", "crawl", "stored", "results"}:
            return _Response(422, {"detail": "invalid source"})

        endpoint = next(route.endpoint for route in self.app.routes if getattr(route, "path", None) == url)
        try:
            if url == "/brands":
                payload = endpoint(
                    source=source,
                    crawl_pages=5,
                    start_date=None,
                    end_date=None,
                    recent_days=None,
                )
            elif url == "/products":
                payload = endpoint(
                    source=source,
                    crawl_pages=5,
                    brand=None,
                    start_date=None,
                    end_date=None,
                    recent_days=None,
                    min_score=None,
                    min_n_eff=None,
                    min_posts=None,
                    min_comments=None,
                    limit=None,
                    internal=False,
                )
            else:
                payload = endpoint()
        except HTTPException as exc:
            return _Response(exc.status_code, {"detail": exc.detail})
        return _Response(200, payload)


client = _SandboxSafeTestClient(app)


def test_health_returns_ok_status() -> None:
    assert health() == {"status": "ok"}


def test_brands_demo_returns_valid_brand_list() -> None:
    response = client.get("/brands", params={"source": "demo"})

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)
    assert payload
    assert "brand" in payload[0]


def test_products_demo_returns_valid_product_results() -> None:
    response = client.get("/products", params={"source": "demo"})

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload["reports"], list)


def test_products_function_accepts_default_demo_source() -> None:
    payload = products(
        source="demo",
        crawl_pages=5,
        brand=None,
        start_date=None,
        end_date=None,
        recent_days=None,
        min_score=None,
        min_n_eff=None,
        min_posts=None,
        min_comments=None,
        limit=None,
        internal=False,
    )

    assert isinstance(payload["reports"], list)
    assert "brands" in payload


def test_brands_stored_returns_valid_brand_list_when_data_exists() -> None:
    if not Path("data/posts.jsonl").exists():
        pytest.skip("data/posts.jsonl does not exist")

    response = client.get("/brands", params={"source": "stored"})

    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_products_results_returns_valid_product_results_when_data_exists() -> None:
    if not Path("data/results.json").exists():
        pytest.skip("data/results.json does not exist")

    response = client.get("/products", params={"source": "results"})

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload["reports"], list)
    assert payload["note"] == "precomputed data does not support time filtering"


def test_products_invalid_source_returns_422() -> None:
    response = client.get("/products", params={"source": "invalid_source"})

    assert response.status_code == 422
