from __future__ import annotations

import asyncio
import csv
from pathlib import Path

import pytest

from cvs_radar.grounding_verdicts import PROMPT_VERSION as GROUNDING_VERSION
from cvs_radar.grounding_verdicts import grounding_fingerprint, load_grounding_verdicts
from cvs_radar.product_categories import CATEGORIES
from scripts.import_grounding_verdicts import import_verdicts
from scripts.jev_labelers import (
    CATEGORY_CRITERIA,
    category_fields,
    grounding_fields,
    label_rows,
)


def test_jev_can_only_answer_categories_the_site_knows() -> None:
    # A key missing here is a category Jev can never pick; an extra key is one the
    # importer would reject and fail the whole nightly run.
    assert set(CATEGORY_CRITERIA) == set(CATEGORIES)
    with pytest.raises(ValueError):
        category_fields("零嘴")


def test_a_torn_grounding_call_rejects_the_rewrite() -> None:
    # A dropped rewrite costs one line; a kept invention is a false claim about a
    # real product. So a coin-flip must not keep it.
    assert grounding_fields(0.49) == {"verdict": "ungrounded"}
    assert grounding_fields(0.5) == {"verdict": "grounded"}


def test_grounding_verdicts_round_trip_through_the_importer(tmp_path: Path) -> None:
    pairs = [("價格偏高", "太貴了"), ("每層都有奶油", "吃起來不會膩")]
    fields = ["fingerprint", "product_name", "field", "rewrite", "source_text",
              "verdict", "model", "prompt_version"]
    rows = [
        {"fingerprint": grounding_fingerprint(rewrite, source), "product_name": "千層",
         "field": "excerpt", "rewrite": rewrite, "source_text": source, "verdict": "",
         "model": "", "prompt_version": GROUNDING_VERSION}
        for rewrite, source in pairs
    ]
    source_path = tmp_path / "pending.csv"
    with open(source_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    async def ask(state: dict[str, str]) -> float:
        assert state["product_name"] == "千層"  # the rubric relies on it
        return 0.9 if state["source_text"] == "太貴了" else 0.1

    labeled = asyncio.run(label_rows("grounding", rows, ask))
    labeled_path = tmp_path / "labeled.csv"
    with open(labeled_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(labeled)

    cache = tmp_path / "verdicts.csv"
    assert import_verdicts(labeled_path, source_path, cache, model_tag="jev") == (2, 0)
    verdicts = load_grounding_verdicts(cache)
    assert verdicts[rows[0]["fingerprint"]] == "grounded"
    assert verdicts[rows[1]["fingerprint"]] == "ungrounded"


def test_one_failed_call_fails_the_whole_batch() -> None:
    async def ask(state: dict[str, str]) -> str:
        raise RuntimeError("529")

    with pytest.raises(RuntimeError):
        asyncio.run(label_rows("category", [{"brand": "全家", "product_name": "x"}], ask))
