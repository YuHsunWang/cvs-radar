from __future__ import annotations

import csv
from pathlib import Path

import pytest

from cvs_radar.product_categories import (
    CATEGORIES,
    DEFAULT_LABELS_PATH,
    FIELDNAMES,
    PROMPT_VERSION,
    load_product_category_labels,
    product_category_fingerprint,
    resolve_category,
)
from scripts import import_product_categories as importer_module
from scripts.import_product_categories import import_labels


@pytest.fixture(autouse=True)
def _never_write_into_the_repo(tmp_path, monkeypatch):
    """Keep the importer's default target away from the committed cache.

    `import_labels` writes to data/labels/product_category_labels.csv by default.
    A test that forgets to pass `labels_path` would rewrite the real cache with
    fixture rows — the same trap tests/test_label_importers.py guards against.
    """
    monkeypatch.setattr(importer_module, "DEFAULT_LABELS_PATH", tmp_path / "labels.csv")


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def _row(brand: str, name: str, category: str = "", **extra: str) -> dict[str, str]:
    row = {
        "fingerprint": product_category_fingerprint(brand, name),
        "brand": brand,
        "product_name": name,
        "rule_guess": "其他",
        "category": category,
        "model": "codex" if category else "",
        "prompt_version": PROMPT_VERSION,
    }
    row.update(extra)
    return row


def test_fingerprint_separates_brands_but_not_spacing() -> None:
    seven = product_category_fingerprint("7-11", "泰式打拋豬肉飯")
    family = product_category_fingerprint("全家", "泰式打拋豬肉飯")
    spaced = product_category_fingerprint("7-11", " 泰式打拋豬肉飯 ")

    # The same name is a different product at a different chain, so one answer
    # must not silently cover both.
    assert seven != family
    assert seven == spaced


def test_fingerprint_retires_answers_when_the_rubric_changes() -> None:
    current = product_category_fingerprint("7-11", "人參糯米雞湯")
    rewritten = product_category_fingerprint(
        "7-11", "人參糯米雞湯", prompt_version="product-category-v2"
    )

    assert current != rewritten


def test_label_decides_the_category_and_keywords_only_fill_the_gap() -> None:
    labels = {product_category_fingerprint("7-11", "泰式打拋豬肉飯"): "便當"}

    # Labelled: the keyword whitelist has no bare 飯 and would answer 其他.
    assert resolve_category("7-11", "泰式打拋豬肉飯", labels=labels) == "便當"
    # Unlabelled: the rules still answer, so a rebuild without new labels works.
    assert resolve_category("7-11", "草莓霜淇淋", labels={}) == "冰品"
    assert resolve_category("7-11", "人參糯米雞湯", labels={}) == "其他"


def test_a_category_outside_the_vocabulary_is_dropped_rather_than_published(
    tmp_path: Path,
) -> None:
    path = tmp_path / "labels.csv"
    _write_csv(path, [_row("全家", "南非國寶茶", "茶飲")])

    labels = load_product_category_labels(path)

    # 茶飲 is not a category the frontend can render — it would reach the site as
    # 其他 anyway, and the keyword rule is the more useful answer.
    assert labels == {}


def test_the_committed_cache_is_found_from_any_working_directory(
    tmp_path, monkeypatch
) -> None:
    """web/build_data.py runs with web/ as its cwd.

    A relative default path resolves to web/data/labels/… there, which does not
    exist: every product silently falls back to the keyword rule and the whole
    layer becomes a no-op at exactly the step that publishes.
    """
    monkeypatch.chdir(tmp_path)

    assert DEFAULT_LABELS_PATH.is_absolute()
    assert load_product_category_labels()


def test_every_committed_row_recomputes_its_own_fingerprint() -> None:
    """A hand-edited name would key an answer to a product nobody looks up."""
    with open(DEFAULT_LABELS_PATH, encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert rows
    for line_number, row in enumerate(rows, start=2):
        recomputed = product_category_fingerprint(
            row["brand"], row["product_name"], prompt_version=row["prompt_version"]
        )
        assert row["fingerprint"] == recomputed, f"row {line_number}: stale fingerprint"
        assert row["category"] in CATEGORIES, f"row {line_number}: {row['category']!r}"


def test_import_stores_a_labelled_row(tmp_path: Path) -> None:
    source = tmp_path / "delta.csv"
    labeled = tmp_path / "labeled.csv"
    cache = tmp_path / "labels.csv"
    _write_csv(source, [_row("全家", "愛恨蔥蔥麵")])
    _write_csv(labeled, [_row("全家", "愛恨蔥蔥麵", "便當")])

    added, replaced, skipped = import_labels(labeled, source, cache)

    assert (added, replaced, skipped) == (1, 0, 0)
    assert load_product_category_labels(cache) == {
        product_category_fingerprint("全家", "愛恨蔥蔥麵"): "便當"
    }
    # BOM + CRLF, matching the four label caches already in data/labels/.
    assert cache.read_bytes().startswith(b"\xef\xbb\xbf")
    assert b"\r\n" in cache.read_bytes()


def test_import_rejects_a_category_the_frontend_cannot_render(tmp_path: Path) -> None:
    source = tmp_path / "delta.csv"
    labeled = tmp_path / "labeled.csv"
    _write_csv(source, [_row("全家", "南非國寶茶")])
    _write_csv(labeled, [_row("全家", "南非國寶茶", "茶飲")])

    with pytest.raises(ValueError, match="unknown category"):
        import_labels(labeled, source, tmp_path / "labels.csv")


def test_import_rejects_a_run_that_renamed_the_product_it_was_given(
    tmp_path: Path,
) -> None:
    source = tmp_path / "delta.csv"
    labeled = tmp_path / "labeled.csv"
    _write_csv(source, [_row("全家", "愛恨蔥蔥麵")])
    renamed = _row("全家", "愛恨蔥蔥麵", "便當")
    renamed["product_name"] = "愛恨蔥麵"
    _write_csv(labeled, [renamed])

    # The fingerprint no longer describes the row it is stored under, so the
    # label would attach to a product that was never labelled.
    with pytest.raises(ValueError, match="immutable field"):
        import_labels(labeled, source, tmp_path / "labels.csv")


def test_import_rejects_a_run_that_quietly_dropped_the_hard_rows(tmp_path: Path) -> None:
    source = tmp_path / "delta.csv"
    labeled = tmp_path / "labeled.csv"
    _write_csv(source, [_row("全家", "愛恨蔥蔥麵"), _row("全家", "馬尚煮")])
    _write_csv(labeled, [_row("全家", "愛恨蔥蔥麵", "便當")])

    with pytest.raises(ValueError, match="dropped 1 source fingerprint"):
        import_labels(labeled, source, tmp_path / "labels.csv")
