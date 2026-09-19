from __future__ import annotations

import asyncio
import csv
from pathlib import Path

import pytest

from scripts.import_llm_backfill import import_labels
from scripts.label_sentiment_jev import judgment_to_fields, label_rows


def test_irrelevant_comment_gets_no_score_so_it_cannot_move_the_product() -> None:
    # A question like "哪裡買得到" must not count as a neutral vote: the scorer
    # skips rows without a score, so the score has to be empty, not 0.
    fields = judgment_to_fields(relevant=0.2, raw_score=4.0)
    assert fields == {"is_relevant": "false", "llm_label": "中性", "llm_score": ""}


@pytest.mark.parametrize(
    ("raw", "label", "score"),
    [
        (0.0, "負向", -1.0),
        (1.0, "負向", -0.5),
        (2.0, "中性", 0.0),
        (2.1, "中性", 0.05),  # inside the neutral band: a lukewarm lean is not praise
        (3.0, "正向", 0.5),
        (4.0, "正向", 1.0),
    ],
)
def test_score_maps_onto_the_caches_minus_one_to_one_scale(
    raw: float, label: str, score: float
) -> None:
    fields = judgment_to_fields(relevant=0.9, raw_score=raw)
    assert fields["llm_label"] == label
    assert float(fields["llm_score"]) == pytest.approx(score)


def test_labeled_rows_keep_order_and_pass_the_importer(tmp_path: Path) -> None:
    fingerprints = [f"{i:064x}" for i in range(3)]
    rows = [
        {"fingerprint": fp, "comment_text": text, "brand": "全家", "product_name": "布丁",
         "post_title": "t", "tag": "推", "llm_score": "", "llm_label": "",
         "is_relevant": "", "reason": "", "model": "", "prompt_version": "sentiment-v1"}
        for fp, text in zip(fingerprints, ["好吃會回購", "哪裡買", "踩雷"])
    ]
    answers = {"好吃會回購": (0.95, 3.8), "哪裡買": (0.1, 2.0), "踩雷": (0.9, 0.2)}

    async def ask(state: dict[str, str]) -> tuple[float, float]:
        await asyncio.sleep(0.01 if state["comment_text"] == "好吃會回購" else 0)
        return answers[state["comment_text"]]

    labeled = asyncio.run(label_rows(rows, ask, concurrency=2))
    assert [r["fingerprint"] for r in labeled] == fingerprints
    assert [r["llm_label"] for r in labeled] == ["正向", "中性", "負向"]
    assert {r["model"] for r in labeled} == {"jev"}

    out = tmp_path / "labeled.csv"
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(labeled)
    cache = tmp_path / "cache.csv"
    assert import_labels(out, cache) == (3, 0, 0)
    stored = {r["fingerprint"]: r for r in csv.DictReader(open(cache, encoding="utf-8-sig"))}
    assert stored[fingerprints[0]]["model"] == "jev"
    assert stored[fingerprints[1]]["llm_score"] == ""


def test_one_failed_call_fails_the_whole_batch() -> None:
    # A partial file would be imported as if the missing comments had no opinion.
    async def ask(state: dict[str, str]) -> tuple[float, float]:
        raise RuntimeError("429")

    with pytest.raises(RuntimeError):
        asyncio.run(label_rows([{"fingerprint": "a", "comment_text": "x"}], ask))
