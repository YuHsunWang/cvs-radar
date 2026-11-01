"""All enabled images here are synthetic fixtures, never public image evidence."""

import csv
import json
from pathlib import Path

import pytest

import web.build_data as build_data
from web.product_images import IMAGE_FIELDS, load_product_images, safe_https_url, valid_image


def image_row(**changes: str) -> dict[str, str]:
    return {
        "product_id": "全家::測試紅茶100ml單瓶", "official_id": "0904302",
        "source_kind": "official_retailer", "source_page_url": "https://retailer.example/product/0904302",
        "image_url": "https://images.example/test-fixture.png", "identity_status": "verified",
        "rights_status": "verified", "enabled": "1", "checked_at": "2026-11-01",
        "takedown_reason": "", **changes,
    }


def manifest(tmp_path: Path, *rows: dict[str, str]) -> Path:
    path = tmp_path / "images.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=IMAGE_FIELDS, lineterminator="\r\n")
        writer.writeheader()
        writer.writerows(rows)
    return path


@pytest.mark.parametrize("changes", [
    {"identity_status": "unknown"}, {"rights_status": "unknown"},
    {"identity_status": "VERIFIED"}, {"rights_status": "approved"},
    {"identity_status": ""}, {"rights_status": ""},
    {"enabled": "0"}, {"takedown_reason": "Removal requested; private review note"},
    {"source_kind": "unknown"}, {"source_kind": "PTT"}, {"image_url": ""},
    {"source_page_url": ""}, {"checked_at": ""}, {"checked_at": "soon"},
])
def test_review_and_removal_gates_fail_closed(tmp_path: Path, changes: dict[str, str]) -> None:
    assert load_product_images(manifest(tmp_path, image_row(**changes))) == {}


@pytest.mark.parametrize("flag", ["", "true", "false", "yes", "2", "01", " 1", "1 ", "unknown"])
def test_malformed_enabled_is_rejected_even_for_unknown_identity(tmp_path: Path, flag: str) -> None:
    with pytest.raises(ValueError, match="enabled flag"):
        load_product_images(manifest(tmp_path, image_row(enabled=flag, identity_status="unknown")))


@pytest.mark.parametrize("url", [
    "http://images.example/a.png", "//images.example/a.png", "javascript:alert(1)",
    "data:image/png;base64,fixture", "file:///tmp/a.png", "https://user:pass@images.example/a",
    "https://@images.example/a", "https://images.example\\@evil.example/a",
    "https://images.example/\na", "https://images.example/a b", "https://images.example/%0aX",
    "https://images.example/%5cX", "https://images.example:bad/a", "https://images.example:8443/a",
    "https:///missing-host", "https://[broken/a", "https://127.0.0.1/a", "https://localhost/a",
    "https://host.local/a", "https://host.internal/a", "https://%65vil.example/a",
])
def test_unsafe_urls_never_publish_in_either_field(tmp_path: Path, url: str) -> None:
    assert not safe_https_url(url)
    for field in ("image_url", "source_page_url"):
        assert load_product_images(manifest(tmp_path, image_row(**{field: url}))) == {}


@pytest.mark.parametrize("kind", ["official_retailer", "official_brand", "ptt"])
def test_traceability_without_private_review_fields(tmp_path: Path, kind: str) -> None:
    source = "https://www.ptt.cc/bbs/CVS/M.1781407692.A.2B4.html" if kind == "ptt" else "https://brand.example/item"
    row = image_row(source_kind=kind, source_page_url=source)
    images = load_product_images(manifest(tmp_path, row))
    assert images[row["product_id"]] == {
        "imageUrl": row["image_url"], "sourcePageUrl": source, "sourceKind": kind,
    }
    assert valid_image(images[row["product_id"]])
    assert "official_id" not in json.dumps(images)
    assert "checked_at" not in json.dumps(images)


def test_ptt_must_trace_to_a_post_not_an_account(tmp_path: Path) -> None:
    assert load_product_images(manifest(tmp_path, image_row(
        source_kind="ptt", source_page_url="https://www.ptt.cc/bbs/CVS/index.html",
    ))) == {}


@pytest.mark.parametrize("kind", ["official_retailer", "official_brand", "ptt"])
@pytest.mark.parametrize("reverse", [False, True])
def test_duplicate_cannot_bypass_official_selection_or_removal(tmp_path: Path, kind: str, reverse: bool) -> None:
    rows = [image_row(enabled="0", takedown_reason="Retain removal"), image_row(source_kind=kind)]
    if reverse:
        rows.reverse()
    with pytest.raises(ValueError, match="duplicate"):
        load_product_images(manifest(tmp_path, *rows))


def test_manifest_keeps_encoding_and_leading_zero() -> None:
    path = build_data.PRODUCT_IMAGES_PATH
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    assert raw.count(b"\n") == raw.count(b"\r\n")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert "0904302" in {row["official_id"] for row in rows}


def test_projection_uses_final_exact_id_and_never_first_post_image(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    row = image_row()
    path = manifest(tmp_path, row)
    source = tmp_path / "results.json"
    source.write_text(json.dumps({"generated_at": "2026-11-01T00:00:00+08:00"}))
    monkeypatch.setattr(build_data, "ROOT", tmp_path)
    monkeypatch.setattr(build_data, "PRODUCT_IMAGES_PATH", path)
    monkeypatch.setattr(build_data, "load_results", lambda _: ([], []))
    monkeypatch.setattr(build_data, "load_product_overrides", lambda: {})
    # Existing valid payload supplies unrelated fields, never enabled fixture images.
    template = json.loads((Path(__file__).parents[1] / "web/public/data.json").read_text())["products"][0]
    names = ["測試紅茶100ml單瓶", "測試綠茶100ml單瓶", "測試紅茶200ml單瓶", "測試紅茶100ml六入"]
    products = [dict(template, id=f"全家::{name}", brand="全家", productName=name,
                     postUrls=["https://images.example/first-post-image.png"]) for name in names]
    monkeypatch.setattr(build_data, "merge_products", lambda _: [dict(product) for product in products])
    output = tmp_path / "data.json"
    build_data.main(source=source, output=output)
    projected = json.loads(output.read_text())["products"]
    assert projected[0]["image"]["sourceKind"] == "official_retailer"
    assert projected[0]["image"]["imageUrl"] == row["image_url"]
    assert all(product["image"] is None for product in projected[1:])
    # Disabling the official selection must never activate a PTT first image.
    manifest(tmp_path, image_row(enabled="0", takedown_reason="Remove fixture"))
    build_data.main(source=source, output=output)
    assert all(product["image"] is None for product in json.loads(output.read_text())["products"])


@pytest.mark.parametrize("image", [
    {"imageUrl": "https://images.example/test.png"},
    {"imageUrl": "https://images.example/test.png", "sourcePageUrl": "http://brand.example", "sourceKind": "official_brand"},
    {"imageUrl": "https://images.example/test.png", "sourcePageUrl": "https://brand.example", "sourceKind": []},
])
def test_public_write_rejects_untraceable_metadata(tmp_path: Path, image: dict) -> None:
    payload = json.loads((Path(__file__).parents[1] / "web/public/data.json").read_text())
    payload["products"] = [dict(payload["products"][0], image=image)]
    output = tmp_path / "public.json"
    output.write_text("previous")
    with pytest.raises(ValueError, match="image metadata"):
        build_data.write_json_atomic(output, payload)
    assert output.read_text() == "previous"
