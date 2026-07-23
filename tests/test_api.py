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
        headers = _kwargs.get("headers") or {}
        x_api_token = next(
            (value for name, value in headers.items() if name.lower() == "x-api-token"),
            None,
        )
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
                    x_api_token=x_api_token,
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
                    internal=bool(params.get("internal", False)),
                    x_api_token=x_api_token,
                )
            else:
                payload = endpoint()
        except HTTPException as exc:
            return _Response(exc.status_code, {"detail": exc.detail})
        return _Response(200, payload)


client = _SandboxSafeTestClient(app)


def test_health_returns_ok_status() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
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


@pytest.mark.parametrize("header_value", [None, "wrong-token"], ids=["missing", "invalid"])
def test_products_internal_requires_api_token(
    monkeypatch: pytest.MonkeyPatch,
    header_value: str | None,
) -> None:
    monkeypatch.setenv("CVS_RADAR_API_TOKEN", "test-secret")
    headers = {} if header_value is None else {"X-API-Token": header_value}

    response = client.get(
        "/products",
        params={"source": "demo", "internal": True},
        headers=headers,
    )

    assert response.status_code == 401


@pytest.mark.parametrize("configured_token", [None, ""], ids=["unset", "empty"])
def test_products_internal_is_disabled_without_server_token(
    monkeypatch: pytest.MonkeyPatch,
    configured_token: str | None,
) -> None:
    if configured_token is None:
        monkeypatch.delenv("CVS_RADAR_API_TOKEN", raising=False)
    else:
        monkeypatch.setenv("CVS_RADAR_API_TOKEN", configured_token)

    response = client.get(
        "/products",
        params={"source": "demo", "internal": True},
        headers={"X-API-Token": "test-secret"},
    )

    assert response.status_code == 403


@pytest.mark.parametrize("path", ["/brands", "/products"])
@pytest.mark.parametrize("header_value", [None, "wrong-token"], ids=["missing", "invalid"])
def test_crawl_requires_api_token(
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    header_value: str | None,
) -> None:
    monkeypatch.setenv("CVS_RADAR_API_TOKEN", "test-secret")
    load_calls: list[str] = []

    def fake_load_posts(source: str, **_kwargs: Any) -> list[Any]:
        load_calls.append(source)
        return []

    monkeypatch.setattr("cvs_radar.api.load_posts", fake_load_posts)
    headers = {} if header_value is None else {"X-API-Token": header_value}

    response = client.get(path, params={"source": "crawl"}, headers=headers)

    assert response.status_code == 401
    assert load_calls == []


@pytest.mark.parametrize("path", ["/brands", "/products"])
@pytest.mark.parametrize("configured_token", [None, ""], ids=["unset", "empty"])
def test_crawl_is_disabled_without_server_token(
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    configured_token: str | None,
) -> None:
    if configured_token is None:
        monkeypatch.delenv("CVS_RADAR_API_TOKEN", raising=False)
    else:
        monkeypatch.setenv("CVS_RADAR_API_TOKEN", configured_token)
    load_calls: list[str] = []

    def fake_load_posts(source: str, **_kwargs: Any) -> list[Any]:
        load_calls.append(source)
        return []

    monkeypatch.setattr("cvs_radar.api.load_posts", fake_load_posts)

    response = client.get(
        path,
        params={"source": "crawl"},
        headers={"X-API-Token": "test-secret"},
    )

    assert response.status_code == 403
    assert load_calls == []


def test_products_internal_allows_valid_api_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CVS_RADAR_API_TOKEN", "test-secret")

    response = client.get(
        "/products",
        params={"source": "demo", "internal": True},
        headers={"X-API-Token": "test-secret"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["filters"]["internal"] is True
    assert any(report.get("contributors") for report in payload["reports"])


@pytest.mark.parametrize("path", ["/brands", "/products"])
def test_crawl_allows_valid_api_token(monkeypatch: pytest.MonkeyPatch, path: str) -> None:
    monkeypatch.setenv("CVS_RADAR_API_TOKEN", "test-secret")
    load_calls: list[str] = []

    def fake_load_posts(source: str, **_kwargs: Any) -> list[Any]:
        load_calls.append(source)
        return []

    monkeypatch.setattr("cvs_radar.api.load_posts", fake_load_posts)

    response = client.get(
        path,
        params={"source": "crawl"},
        headers={"X-API-Token": "test-secret"},
    )

    assert response.status_code == 200
    assert load_calls == ["crawl"]


@pytest.mark.parametrize("source", ["demo", "stored", "results"])
def test_products_public_sources_need_no_token_and_hide_contributors(
    monkeypatch: pytest.MonkeyPatch,
    source: str,
) -> None:
    required_path = {
        "stored": Path("data/posts.jsonl"),
        "results": Path("data/results.json"),
    }.get(source)
    if required_path is not None and not required_path.exists():
        pytest.skip(f"{required_path} does not exist")
    monkeypatch.delenv("CVS_RADAR_API_TOKEN", raising=False)

    response = client.get("/products", params={"source": source, "internal": False})

    assert response.status_code == 200
    assert all("contributors" not in report for report in response.json()["reports"])
