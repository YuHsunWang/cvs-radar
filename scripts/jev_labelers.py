#!/usr/bin/env python3
"""Label the product-category and grounding deltas with TypeSafe Jev.

    jev_labelers.py category  DELTA --out LABELED
    jev_labelers.py grounding DELTA --out LABELED

Reads the delta the layer's exporter wrote, keeps every source column and the row
order, fills ``category`` (one Jev Choice) or ``verdict`` (one Jev Noul), sets
``model=jev``, and leaves validation to the layer's importer. This file is the
rubric for both layers; it replaced ``scripts/prompts/product-category-labeling.md``
and ``scripts/prompts/grounding-verification.md``, which git history still has.

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

# Category definitions, condensed from the retired Codex prompt. Keys must match
# cvs_radar.product_categories.CATEGORIES exactly.
CATEGORY_CRITERIA = {
    "便當": "一餐的主食：飯類（便當、飯糰、丼、炒飯、粽、咖哩飯）、非泡麵的麵食主餐（義大利麵、拌麵、涼麵、牛肉麵、河粉）、火鍋燉煮（部隊鍋、壽喜燒、薑母鴨）、湯與粥、沙拉或蛋白餐盒。",
    "鹹食": "單品鹹點，不是一整餐：關東煮、雞塊、雞排、大亨堡、熱狗、水餃、煎餃、湯包、肉包、燒賣、茶葉蛋、溏心蛋、甜不辣、毛豆、玉米杯、滷味、雞翅。",
    "泡麵": "加熱水沖泡的速食麵（杯麵、碗麵、袋裝泡麵、來一客、滿漢）。冷藏即食麵碗是便當不是泡麵。",
    "麵包": "麵包與三明治：吐司、貝果、可頌、丹麥、餐包、三明治。",
    "甜點": "非冷凍、非麵包的甜食：蛋糕、布丁、泡芙、麻糬、大福、布朗尼、銅鑼燒、鬆餅、果凍、愛玉、豆花、燒仙草、芝麻糊。",
    "冰品": "冷凍的：霜淇淋、冰淇淋、雪糕、冰棒、冰沙、聖代、剉冰、雪淋霜。",
    "飲料": "喝的東西（不是以牛奶本身為主）：茶、咖啡、拿鐵、奶茶、果汁、汽水、機能飲、豆漿、米漿，也包括酒（啤酒、調酒、highball、梅酒）。CITYCAFE、每日C、純萃喝都是飲料。",
    "乳品": "乳製品本身：鮮乳、保久乳、優格、優酪乳、起司、乳酪。奶茶和拿鐵算飲料。",
    "零食": "包裝零嘴：洋芋片、餅乾、糖果、巧克力、米果、肉乾、堅果、果乾、魷魚絲、脆片。",
    "周邊": "不是食物，是收藏或用品：福袋、公仔、一番賞、吊飾、鑰匙圈、杯墊、托特包、造型包、毯子、玩具、文具、鍋具。借用食物名稱的造型商品也算周邊。",
    "其他": "最後手段，以上都不符合時才選：生鮮食材與雜貨（生雞蛋、水果、地瓜）、調味料（辣椒醬、鵝油）、家用品。",
}
CATEGORY_INSTRUCTIONS = (
    "`product_name` 是台灣超商（`brand`）賣的一個商品。台灣消費者會在哪個分類下找它？"
    "看商品本身，不是店名或聯名品牌，也不是吃的場合。"
    "零食品牌（乖乖、樂事、可樂果、卡迪那、品客）出的口味聯名商品仍是零食，就算名稱像一道菜或一杯酒；"
    "泡麵品牌（味味一品、維力、統一、來一客、滿漢、農心）或名店聯名的杯麵碗麵是泡麵。"
    "在兩個真實分類間猶豫時選比較好的那個，不要選其他。"
)

GROUNDING_INSTRUCTIONS = (
    "`rewrite` 是根據 `source_text`（一則關於超商商品 `product_name` 的心得或留言）改寫的短句。"
    "原文常省略主詞，預設它在講這個商品。"
    "只看過 `source_text` 的讀者，能不能不加自己的知識就寫出 `rewrite`？"
    "同義改寫、把口語收斂成乾淨短句、補上商品名稱或它明顯的部位或口味"
    "（例如原文「好淡」、商品是巧克力布丁 → 「巧克力味太淡」）都可以。"
)
GROUNDING_CRITERIA = {
    "true": "`rewrite` 的每個說法都是 `source_text` 明說或直接隱含的（例如「太貴了」→「價格偏高」、「有夠柴」→「雞胸肉很柴」）。",
    "false": "`rewrite` 說了 `source_text` 沒支持的東西：原文沒有的事實、完全不同的話題、從商品名稱推出來的說法，或大致忠實但多加了一個原文沒有的細節。",
}
# When torn, reject: a dropped rewrite costs one line, a kept invention is a false
# claim about a real product.
GROUNDED_THRESHOLD = 0.5

Ask = Callable[[dict[str, str]], Awaitable[object]]


def category_fields(choice: str) -> dict[str, str]:
    if choice not in CATEGORY_CRITERIA:
        raise ValueError(f"unexpected category {choice!r}")
    return {"category": choice}


def grounding_fields(probability: float) -> dict[str, str]:
    return {"verdict": "grounded" if probability >= GROUNDED_THRESHOLD else "ungrounded"}


LAYERS: dict[str, dict[str, object]] = {
    "category": {
        "state": ("brand", "product_name"),
        "to_fields": category_fields,
    },
    "grounding": {
        "state": ("product_name", "source_text", "rewrite"),
        "to_fields": grounding_fields,
    },
}


async def label_rows(
    layer: str, rows: list[dict[str, str]], ask: Ask, *, concurrency: int = 8
) -> list[dict[str, str]]:
    """Label every row, keeping input order. Any failed call raises."""
    spec = LAYERS[layer]
    gate = asyncio.Semaphore(concurrency)

    async def one(row: dict[str, str]) -> dict[str, str]:
        state = {field: row.get(field, "") for field in spec["state"]}
        async with gate:
            answer = await ask(state)
        return {**row, **spec["to_fields"](answer), "model": MODEL_NAME}

    return list(await asyncio.gather(*(one(row) for row in rows)))


def _question(layer: str) -> object:
    from typesafe_sdk import Choice, Noul

    if layer == "category":
        return Choice(instructions=CATEGORY_INSTRUCTIONS, criteria=CATEGORY_CRITERIA)
    return Noul(instructions=GROUNDING_INSTRUCTIONS, criteria=GROUNDING_CRITERIA)


async def _label_with_jev(
    layer: str, rows: list[dict[str, str]], concurrency: int
) -> list[dict[str, str]]:
    from typesafe_sdk import AsyncTypeSafeClient

    questions = {"q": _question(layer)}
    async with AsyncTypeSafeClient() as client:

        async def ask(state: dict[str, str]) -> object:
            answer = (await client.system_one(state=state, questions=questions)).answers["q"]
            return answer.choice if layer == "category" else answer.noul

        return await label_rows(layer, rows, ask, concurrency=concurrency)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("layer", choices=sorted(LAYERS))
    parser.add_argument("delta", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--concurrency", type=int, default=8)
    args = parser.parse_args()

    csv.field_size_limit(10**7)
    with open(args.delta, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    if not rows:
        sys.exit(f"no rows in {args.delta}")

    labeled = asyncio.run(_label_with_jev(args.layer, rows, args.concurrency))

    temporary = args.out.with_suffix(args.out.suffix + ".tmp")
    with open(temporary, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(labeled)
    temporary.replace(args.out)
    column = "category" if args.layer == "category" else "verdict"
    counts: dict[str, int] = {}
    for row in labeled:
        counts[row[column]] = counts.get(row[column], 0) + 1
    print(f"jev labeled {len(labeled)} {args.layer} rows {counts} -> {args.out}")


if __name__ == "__main__":
    main()
