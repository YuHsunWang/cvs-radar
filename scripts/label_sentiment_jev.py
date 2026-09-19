#!/usr/bin/env python3
"""Label an exported sentiment delta with TypeSafe Jev.

Reads the CSV written by ``export_llm_backfill.py`` and writes the same columns
with ``is_relevant``/``llm_label``/``llm_score``/``model`` filled, ready for
``import_llm_backfill.py``. Each comment gets two Jev questions in one request:
a Noul (does it evaluate the product at all) and a five-level Score (how positive).

This file is the sentiment rubric. It replaced the Codex heredoc prompt that used
to live in ``scripts/ops/rebackfill.sh``. Labels written here carry
``model=jev``; the fingerprint's prompt version is unchanged on purpose, so the
existing Codex labels stay valid and only new comments are judged by Jev.

Needs ``TYPESAFE_API_KEY`` and ``pip install typesafe-sdk``. Any API failure
exits non-zero before the output file is written.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path

MODEL_NAME = "jev"
STATE_FIELDS = ("brand", "product_name", "post_title", "tag", "comment_text")
# Score levels, low to high. Level 2 is neutral, so (score - 2) / 2 maps onto [-1, 1].
SENTIMENT_LEVELS = [
    "很負面：難吃、踩雷、明確勸退、不會再買",
    "有點負面：小抱怨，例如太貴、太甜、份量少、普通偏失望",
    "中性：沒有明確態度，或正負混雜沒有結論，或只是陳述資訊",
    "有點正面：還不錯、可以一試、小稱讚",
    "很正面：超好吃、大推、會回購、必買",
]
RELEVANT_THRESHOLD = 0.5
NEUTRAL_BAND = 0.1

# (relevant probability, raw Score on 0..len(SENTIMENT_LEVELS)-1)
Ask = Callable[[dict[str, str]], Awaitable[tuple[float, float]]]


def build_questions() -> dict[str, object]:
    """Build the Jev questions (imports the SDK lazily so tests don't need it)."""
    from typesafe_sdk import Noul, Score

    return {
        "relevant": Noul(
            instructions=(
                "`comment_text` 是 PTT 超商版一則推文，貼文在介紹 `product_name`（`brand`）。"
                "這則推文有沒有對這個商品表達任何評價？"
            ),
            criteria={
                "true": "有評價：味道、品質、口感、份量、價格划不划算、會不會回購、跟別家比較的結論，就算很弱或正負混雜也算。",
                "false": "沒評價：純發問、問哪裡買或有沒有貨、兌換或物流、tag 朋友、離題、只講自己狀態、空白。",
            },
        ),
        "sentiment": Score(
            instructions=(
                "`comment_text` 是 PTT 超商版一則推文（`tag` 是推/噓/→），貼文在介紹 `product_name`（`brand`）。"
                "這則推文對這個商品的態度有多正面？反諷要看真正意思（例如「佛心到我不敢買」是嫌貴）；"
                "「雷」「踩雷」是負面，「回購」「必買」是正面；比較句看對這個商品的結論。"
            ),
            criteria=SENTIMENT_LEVELS,
        ),
    }


def judgment_to_fields(relevant: float, raw_score: float) -> dict[str, str]:
    """Turn Jev's answers into the importer's columns.

    Irrelevant comments carry no score and are labelled 中性, as the Codex rubric
    did, so the scorer ignores them instead of counting them as neutral votes.
    """
    if relevant < RELEVANT_THRESHOLD:
        return {"is_relevant": "false", "llm_label": "中性", "llm_score": ""}
    top = len(SENTIMENT_LEVELS) - 1
    score = round((raw_score - top / 2) / (top / 2), 4)
    score = max(-1.0, min(1.0, score))
    if score > NEUTRAL_BAND:
        label = "正向"
    elif score < -NEUTRAL_BAND:
        label = "負向"
    else:
        label = "中性"
    return {"is_relevant": "true", "llm_label": label, "llm_score": str(score)}


async def label_rows(
    rows: list[dict[str, str]], ask: Ask, *, concurrency: int = 8
) -> list[dict[str, str]]:
    """Label every row, keeping input order. Any failed call raises."""
    gate = asyncio.Semaphore(concurrency)

    async def one(row: dict[str, str]) -> dict[str, str]:
        state = {field: row.get(field, "") for field in STATE_FIELDS}
        async with gate:
            relevant, raw_score = await ask(state)
        return {**row, **judgment_to_fields(relevant, raw_score), "model": MODEL_NAME}

    return list(await asyncio.gather(*(one(row) for row in rows)))


async def _label_with_jev(rows: list[dict[str, str]], concurrency: int) -> list[dict[str, str]]:
    from typesafe_sdk import AsyncTypeSafeClient

    questions = build_questions()
    async with AsyncTypeSafeClient() as client:

        async def ask(state: dict[str, str]) -> tuple[float, float]:
            response = await client.system_one(state=state, questions=questions)
            answers = response.answers
            return answers["relevant"].noul, answers["sentiment"].score

        return await label_rows(rows, ask, concurrency=concurrency)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("delta", type=Path, help="CSV from export_llm_backfill.py")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--concurrency", type=int, default=8)
    args = parser.parse_args()

    with open(args.delta, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    if not rows:
        sys.exit(f"no rows in {args.delta}")

    labeled = asyncio.run(_label_with_jev(rows, args.concurrency))

    temporary = args.out.with_suffix(args.out.suffix + ".tmp")
    with open(temporary, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(labeled)
    temporary.replace(args.out)
    counts = {label: sum(r["llm_label"] == label for r in labeled) for label in ("正向", "中性", "負向")}
    irrelevant = sum(r["is_relevant"] == "false" for r in labeled)
    print(f"jev labeled {len(labeled)} rows {counts} irrelevant={irrelevant} -> {args.out}")


if __name__ == "__main__":
    main()
