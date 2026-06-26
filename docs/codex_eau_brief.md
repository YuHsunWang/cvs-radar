# Codex 任務：自動預標註 gold 資料（eau）

> Claude 已拍板。Codex 執行，完成後 Claude 獨立驗證。**先單獨跑測試確認綠燈再 commit（勿串同條指令）。**

## 背景

目前 gold 標註資料只有 17 筆（`data/labels/gold_v1.csv`），統計意義不足。目標擴充到 200+ 筆，覆蓋更多情境（正/負/中性、比較句型、多品牌提及、反諷等）。

流程：
1. 從已爬取資料（`data/posts.jsonl`）或 sample data 產生待標註 CSV
2. 用現有 `RuleBasedPredictor` 自動預填標籤欄位
3. 輸出 `data/labels/gold_v2_draft.csv` 供人工復查

## 只能改的檔案

- `cvs_radar/labeling.py` — 新增 `stored` 資料來源
- `scripts/prelabel.py` — 新增自動預標註腳本（新檔）
- `tests/test_labeling_evaluation.py` — 新增預標註測試
- **不可改其他檔案**

## 任務 A：labeling.py 支援 stored 資料源

修改 `_load_posts()` 函式，新增 `stored` source：

```python
def _load_posts(source: str, *, pages: int) -> list[Post]:
    if source == "demo":
        from .sample_data import load_sample
        return load_sample()
    if source == "stored":
        from .store import load_posts as load_stored
        posts = load_stored()
        if not posts:
            raise ValueError("No stored posts found. Run crawl_job.py first.")
        return posts
    if source == "crawl":
        from .crawler import PttCrawler
        return PttCrawler().crawl(max_pages=pages)
    raise ValueError(f"unsupported source: {source}")
```

同時更新 `main()` 的 argparse choices：

```python
parser.add_argument("--source", choices=["demo", "crawl", "stored"], default="demo")
```

## 任務 B：建立 `scripts/prelabel.py`

新增自動預標註腳本，使用既有的 `RuleBasedPredictor` 預填 5 個標籤欄位。

```python
#!/usr/bin/env python3
"""Auto-prelabel a to_label CSV using RuleBasedPredictor.

Usage:
    python scripts/prelabel.py --input data/labels/to_label.csv --output data/labels/gold_v2_draft.csv
    python scripts/prelabel.py --source stored --output data/labels/gold_v2_draft.csv
    python scripts/prelabel.py --source demo --output data/labels/gold_v2_draft.csv
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from cvs_radar.evaluation import (
    RuleBasedPredictor,
    normalize_sentiment,
)
from cvs_radar.labeling import (
    CSV_COLUMNS,
    build_labeling_rows,
    read_labeling_csv,
    write_labeling_csv,
)


# 反向映射：evaluation 輸出的英文標籤 → gold CSV 的中文標籤
SENTIMENT_MAP = {"positive": "正", "negative": "負", "neutral": "中"}
TARGET_MAP = {"own": "本牌", "other": "他牌", "none": "無"}
BOOL_MAP = {True: "是", False: "否"}
FAVORED_MAP = {"own": "本牌", "other": "他牌", "tie": "平手", "unknown": "不明"}


def prelabel_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Fill label columns using RuleBasedPredictor."""
    predictor = RuleBasedPredictor()
    labeled = []
    for row in rows:
        prediction = predictor.predict_row(row)
        row = dict(row)  # copy
        row["sentiment"] = SENTIMENT_MAP.get(prediction.sentiment, "中")
        row["target_brand"] = TARGET_MAP.get(prediction.target_brand, "無")
        row["is_comparative"] = BOOL_MAP.get(prediction.is_comparative, "否")
        row["favored_brand"] = FAVORED_MAP.get(prediction.favored_brand, "不明")
        row["notes"] = "auto-prelabeled"
        labeled.append(row)
    return labeled


def write_labeled_csv(rows: list[dict[str, str]], path: str | Path) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Auto-prelabel comments for gold review")
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--input", help="Path to existing to_label CSV")
    input_group.add_argument("--source", choices=["demo", "stored"], help="Generate rows from data source")
    parser.add_argument("--output", default="data/labels/gold_v2_draft.csv", help="Output path")
    parser.add_argument("--limit", type=int, help="Max rows to process")
    parser.add_argument("--shuffle", action="store_true", help="Shuffle before limiting")
    parser.add_argument("--seed", type=int, default=0, help="Random seed for shuffle")
    args = parser.parse_args()

    if args.input:
        rows = read_labeling_csv(args.input)
    else:
        from cvs_radar.labeling import _load_posts
        posts = _load_posts(args.source, pages=5)
        labeling_rows = build_labeling_rows(
            posts, limit=args.limit, shuffle=args.shuffle, seed=args.seed,
        )
        rows = [row.to_dict() for row in labeling_rows]

    if args.limit and args.input:
        rows = rows[:args.limit]

    labeled = prelabel_rows(rows)
    write_labeled_csv(labeled, args.output)
    print(f"Wrote {len(labeled)} pre-labeled rows to {args.output}")


if __name__ == "__main__":
    main()
```

確保 `scripts/` 目錄存在（新建）。

## 任務 C：用 sample data 驗證

執行以下命令產生預標註結果：

```bash
python scripts/prelabel.py --source demo --output data/labels/gold_v2_draft.csv
```

確認：
- 輸出 CSV 包含所有 sample data 的留言（約 18 筆，扣除空留言）
- 每一列的 5 個標籤欄位都有值（`sentiment`、`target_brand`、`is_comparative`、`favored_brand`、`notes`）
- CSV 欄位順序與 `gold_v1.csv` 一致

## 任務 D：新增測試

在 `tests/test_labeling_evaluation.py` 新增：

```python
def test_prelabel_fills_all_label_columns(self) -> None:
    """prelabel_rows fills sentiment, target_brand, is_comparative, favored_brand, notes."""
    from scripts.prelabel import prelabel_rows

    row = {
        "comment_id": "test#000",
        "source": "PTT",
        "board": "CVS",
        "post_id": "test",
        "post_url": "",
        "post_title": "[商品] 7-11 測試",
        "post_brand": "7-11",
        "product_name": "測試飯糰",
        "price": "50",
        "post_tag": "商品",
        "comment_user": "tester",
        "comment_tag": "推",
        "comment_text": "好吃會回購",
        "comment_posted_at": "",
        "context": "貼文品牌=7-11",
        "sentiment": "",
        "target_brand": "",
        "is_comparative": "",
        "favored_brand": "",
        "notes": "",
    }
    result = prelabel_rows([row])
    self.assertEqual(len(result), 1)
    self.assertIn(result[0]["sentiment"], ("正", "負", "中"))
    self.assertIn(result[0]["target_brand"], ("本牌", "他牌", "無"))
    self.assertIn(result[0]["is_comparative"], ("是", "否"))
    self.assertIn(result[0]["favored_brand"], ("本牌", "他牌", "平手", "不明"))
    self.assertEqual(result[0]["notes"], "auto-prelabeled")

def test_prelabel_positive_comment(self) -> None:
    """Positive push with clear positive text gets sentiment=正."""
    from scripts.prelabel import prelabel_rows

    row = {
        "comment_id": "pos#000",
        "source": "PTT",
        "board": "CVS",
        "post_id": "pos",
        "post_url": "",
        "post_title": "[商品] 全家 好吃雞排",
        "post_brand": "全家",
        "product_name": "好吃雞排",
        "price": "",
        "post_tag": "商品",
        "comment_user": "u1",
        "comment_tag": "推",
        "comment_text": "好吃推薦回購",
        "comment_posted_at": "",
        "context": "貼文品牌=全家",
        "sentiment": "",
        "target_brand": "",
        "is_comparative": "",
        "favored_brand": "",
        "notes": "",
    }
    result = prelabel_rows([row])
    self.assertEqual(result[0]["sentiment"], "正")

def test_labeling_stored_source(self) -> None:
    """labeling _load_posts supports 'stored' source."""
    from cvs_radar.labeling import _load_posts
    # stored source without data should raise
    with self.assertRaises(ValueError):
        _load_posts("stored", pages=5)
```

## 驗收

- 所有既有測試 + 新測試全過
- `python scripts/prelabel.py --source demo --output /tmp/test_draft.csv` 成功產生 CSV
- 輸出 CSV 每列都有 5 個標籤欄位填入值
- `labeling.py --source stored` 在無 data/posts.jsonl 時拋出明確錯誤訊息
- `data/labels/gold_v2_draft.csv` 存在且格式正確
- 先跑測試確認綠燈再 commit，不要 push

## 使用者後續步驟

1. 先跑 `python crawl_job.py --pages 20` 爬取足夠資料
2. 再跑 `python scripts/prelabel.py --source stored --output data/labels/gold_v2_draft.csv`
3. 人工打開 `gold_v2_draft.csv` 復查每列標籤，修正後存為 `gold_v2.csv`
4. 跑 `python -m cvs_radar.evaluation --gold data/labels/gold_v2.csv` 評估準確率
