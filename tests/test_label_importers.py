from __future__ import annotations

import csv
import subprocess
from pathlib import Path

import pytest

from cvs_radar.product_labels import PROMPT_VERSION, product_name_fingerprint_v2
from cvs_radar.excerpt_labels import (
    PROMPT_VERSION as EXCERPT_PROMPT_VERSION,
    excerpt_fingerprint_v2,
)
from scripts.import_excerpts import import_labels as import_excerpts
from scripts.import_product_names import import_labels as import_product_names
from scripts.migrate_sentiment_overrides import analyze as analyze_sentiment_migration
from scripts import relabel_delta


PRODUCT_FIELDS = (
    "fingerprint",
    "item_index",
    "brand",
    "title",
    "raw_name",
    "rule_guess",
    "product_name",
    "price",
    "model",
    "prompt_version",
)


def _write_csv(path: Path, rows: list[dict[str, str]], fields=PRODUCT_FIELDS) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _product_row(raw_name: str, product_name: str = "") -> dict[str, str]:
    row = {
        "item_index": "0",
        "brand": "全家",
        "title": f"[商品] {raw_name}",
        "raw_name": raw_name,
        "rule_guess": f"{raw_name}#49",
        "product_name": product_name,
        "price": "49" if product_name else "",
        "model": "codex" if product_name else "",
        "prompt_version": PROMPT_VERSION,
    }
    row["fingerprint"] = product_name_fingerprint_v2(
        row["brand"],
        row["title"],
        row["raw_name"],
        rule_guess=row["rule_guess"],
        prompt_version=row["prompt_version"],
    )
    return row


def test_product_import_rejects_swapped_fingerprints_before_cache_write(tmp_path: Path) -> None:
    source_rows = [_product_row("草莓蛋糕"), _product_row("抹茶布丁")]
    labeled_rows = [dict(row) for row in source_rows]
    labeled_rows[0].update(product_name="草莓蛋糕", price="49", model="codex")
    labeled_rows[1].update(product_name="抹茶布丁", price="49", model="codex")
    labeled_rows[0]["fingerprint"], labeled_rows[1]["fingerprint"] = (
        labeled_rows[1]["fingerprint"],
        labeled_rows[0]["fingerprint"],
    )
    source = tmp_path / "source.csv"
    labeled = tmp_path / "labeled.csv"
    cache = tmp_path / "cache.csv"
    _write_csv(source, source_rows)
    _write_csv(labeled, labeled_rows)

    with pytest.raises(ValueError, match="immutable field"):
        import_product_names(labeled, source, cache)

    assert not cache.exists()


def test_product_import_rejects_duplicate_item_index(tmp_path: Path) -> None:
    source_row = _product_row("草莓蛋糕/抹茶布丁")
    labeled_rows = [dict(source_row), dict(source_row)]
    labeled_rows[0].update(product_name="草莓蛋糕", price="49", model="codex")
    labeled_rows[1].update(product_name="抹茶布丁", price="55", model="codex")
    source = tmp_path / "source.csv"
    labeled = tmp_path / "labeled.csv"
    cache = tmp_path / "cache.csv"
    _write_csv(source, [source_row])
    _write_csv(labeled, labeled_rows)

    with pytest.raises(ValueError, match="duplicate fingerprint/item_index"):
        import_product_names(labeled, source, cache)

    assert not cache.exists()


EXCERPT_FIELDS = (
    "fingerprint",
    "post_id",
    "brand",
    "product_name",
    "other_products",
    "review_text",
    "excerpt",
    "model",
    "prompt_version",
)


def _excerpt_row(review_text: str, excerpt: str) -> dict[str, str]:
    row = {
        "post_id": "M.1",
        "brand": "全家",
        "product_name": "草莓蛋糕",
        "other_products": "抹茶布丁",
        "review_text": review_text,
        "excerpt": excerpt,
        "model": "codex" if excerpt else "",
        "prompt_version": EXCERPT_PROMPT_VERSION,
    }
    row["fingerprint"] = excerpt_fingerprint_v2(
        row["post_id"],
        row["product_name"],
        row["review_text"],
        brand=row["brand"],
        other_products=row["other_products"],
        prompt_version=row["prompt_version"],
    )
    return row


def test_excerpt_import_rejects_hallucinated_quote_before_cache_write(tmp_path: Path) -> None:
    source_row = _excerpt_row("蛋糕酸甜，奶油很輕盈。", "")
    labeled_row = dict(source_row, excerpt="作者說一定會回購。", model="codex")
    source = tmp_path / "source.csv"
    labeled = tmp_path / "labeled.csv"
    cache = tmp_path / "cache.csv"
    _write_csv(source, [source_row], EXCERPT_FIELDS)
    _write_csv(labeled, [labeled_row], EXCERPT_FIELDS)

    with pytest.raises(ValueError, match="exact slice of review_text"):
        import_excerpts(labeled, source, cache)

    assert not cache.exists()


def test_excerpt_import_enforces_prompt_limit_of_90_characters(tmp_path: Path) -> None:
    review = "酸" * 91
    source_row = _excerpt_row(review, "")
    labeled_row = dict(source_row, excerpt=review, model="codex")
    source = tmp_path / "source.csv"
    labeled = tmp_path / "labeled.csv"
    cache = tmp_path / "cache.csv"
    _write_csv(source, [source_row], EXCERPT_FIELDS)
    _write_csv(labeled, [labeled_row], EXCERPT_FIELDS)

    with pytest.raises(ValueError, match="longer than 90"):
        import_excerpts(labeled, source, cache)

    assert not cache.exists()


@pytest.mark.parametrize(
    ("failed_script", "expected_calls"),
    [
        ("label_product_names.sh", ["label_product_names.sh"]),
        (
            "label_excerpts.sh",
            ["label_product_names.sh", "label_excerpts.sh"],
        ),
        (
            "label_comment_picks.sh",
            [
                "label_product_names.sh",
                "label_excerpts.sh",
                "label_comment_picks.sh",
            ],
        ),
    ],
)
def test_required_label_failure_stops_before_later_layers(
    tmp_path: Path,
    failed_script: str,
    expected_calls: list[str],
) -> None:
    call_log = tmp_path / "calls"
    for name in (
        "label_product_names.sh",
        "label_excerpts.sh",
        "label_comment_picks.sh",
    ):
        status = 1 if name == failed_script else 0
        (tmp_path / name).write_text(
            f"#!/usr/bin/env bash\nprintf '%s\\n' {name} >> {call_log}\nexit {status}\n",
            encoding="utf-8",
        )

    result = subprocess.run(
        ["bash", "scripts/ops/run_required_label_layers.sh"],
        env={"SCRIPTS_DIR": str(tmp_path), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert call_log.read_text(encoding="utf-8").splitlines() == expected_calls


def test_rebackfill_requires_all_label_layers_before_recompute() -> None:
    script = Path("scripts/ops/rebackfill.sh").read_text(encoding="utf-8")

    gate = script.index(
        'bash scripts/ops/run_required_label_layers.sh || die "required semantic labeling"'
    )
    recompute = script.index('log "recompute results from posts + labels"')
    assert gate < recompute
    assert "publishing on" not in script


def test_legacy_relabel_merge_rejects_runtime_normalized_score_collision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "sentiment_overrides.csv"
    labeled = tmp_path / "labeled.csv"
    _write_csv(
        cache,
        [{"留言內容": "好吃", "llm分數": "0.8", "llm判定": "正向"}],
        ("留言內容", "llm分數", "llm判定"),
    )
    _write_csv(
        labeled,
        [{"留言內容": "好吃!!", "llm分數": "0.6", "llm判定": "正向"}],
        ("留言內容", "llm分數", "llm判定"),
    )
    before = cache.read_bytes()
    monkeypatch.setattr(relabel_delta, "OVERRIDES_PATH", cache)

    with pytest.raises(ValueError, match="conflicting normalized key '好吃'"):
        relabel_delta.merge(labeled)

    assert cache.read_bytes() == before


def test_sentiment_migration_preserves_last_row_runtime_winner(tmp_path: Path) -> None:
    cache = tmp_path / "sentiment_overrides.csv"
    _write_csv(
        cache,
        [
            {"留言內容": "好吃", "llm分數": "0.8", "llm判定": "正向"},
            {"留言內容": "好吃!", "llm分數": "0.8", "llm判定": "正向"},
            {"留言內容": "好吃。", "llm分數": "0.6", "llm判定": "正向"},
        ],
        ("留言內容", "llm分數", "llm判定"),
    )

    rows, collisions, conflicts = analyze_sentiment_migration(cache)

    assert rows == [("好吃", "0.6", "正向")]
    assert collisions == 2
    assert conflicts == 1
