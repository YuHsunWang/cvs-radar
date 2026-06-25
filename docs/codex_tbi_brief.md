# Codex 任務：tbi 商品識別模糊比對（名稱變體誤分，§11）

> Claude 已拍板。Codex 執行，完成後 Claude 獨立驗證。**先單獨跑測試確認綠燈再 commit（勿串同條指令）。**

## 背景

`cvs_radar/scoring.py` 已有商品名稱正規化與模糊比對邏輯，用於把同一商品的不同文章歸為一組。但 PTT 標題噪音多（如「心得開箱」「2入」「新包裝」），導致同商品被拆成多筆。PRD §11 列為中風險。

現有清理機制：
- `_NOISE_RE`：移除常見評論用語（心得、開箱、推薦…）
- `_OPTIONAL_RE`：移除數量單位（2入、3包、150ml…）
- `_BRACKET_RE`：移除括號內容
- `_same_product()`：SequenceMatcher ≥ 0.86 或 char Jaccard ≥ 0.72，加 `_DISTINCTIVE_TERMS` 保護不同口味不被合併

## 只能改的檔案

- `cvs_radar/scoring.py`
- `tests/test_core.py`
- **不可改其他檔案**

## 任務 A：擴充 `_NOISE_RE`

在 `cvs_radar/scoring.py` 的 `_NOISE_RE` 正則裡加入更多 PTT 標題常見噪音詞：

```
必買, 不推, 超商, 超好吃, 好吃, 難吃, 最新, 聯名, 期間限定, 季節限定,
新口味, 大推, 激推, 雷, 微雷, 不雷, 二訪, 回味, 無限回購
```

注意順序：較長的詞放前面（如 `期間限定` 在 `限定` 前面、`無限回購` 在 `回購` 前面、`超好吃` 在 `好吃` 前面），否則短詞會先被匹配到，導致長詞無法整體移除。已有 `限定` 在 `_OPTIONAL_RE` 裡，確認不衝突。

## 任務 B：同義詞正規化

在 `cvs_radar/scoring.py` 新增：

```python
_SYNONYM_MAP = {
    "蕃薯": "地瓜",
    "番薯": "地瓜",
    "起士": "起司",
    "芝士": "起司",
    "優格": "優酪",
    "吐司": "土司",
}
```

在 `_clean_product_name()` 的最後（`return s or "unknown"` 之前），迭代 `_SYNONYM_MAP` 做字串替換：

```python
for old, new in _SYNONYM_MAP.items():
    s = s.replace(old, new)
```

同時也在 `_clean_product_name_without_alias()` 做同樣處理，保持兩個函式一致。

確認 `_DISTINCTIVE_TERMS` 已包含同義詞的目標值（`起司` 已有；`地瓜` 不在裡面要加上）。

## 任務 C：測試

在 `tests/test_core.py` 的 `ScoringTest` class 新增：

```python
def test_product_normalization_strips_noise_and_units(self) -> None:
    self.assertEqual(
        normalize_product("7-11", "鮪魚飯糰2入"),
        normalize_product("7-11", "鮪魚飯糰"),
    )
    self.assertEqual(
        normalize_product("全家", "新品 XX蛋糕 心得開箱"),
        normalize_product("全家", "XX蛋糕"),
    )

def test_product_synonym_normalization(self) -> None:
    self.assertEqual(
        normalize_product("7-11", "起士蛋糕"),
        normalize_product("7-11", "起司蛋糕"),
    )
    self.assertEqual(
        normalize_product("全家", "蕃薯球"),
        normalize_product("全家", "地瓜球"),
    )

def test_product_grouping_merges_name_with_parenthetical(self) -> None:
    posts = [
        Post(id="p1", brand="7-11", product_name="阜杭豆漿饅頭夾豬排蛋", author="a1", author_score=80),
        Post(id="p2", brand="7-11", product_name="阜杭豆漿饅頭夾豬排蛋(新包裝)", author="a2", author_score=82),
    ]
    reports, _ = run_pipeline(posts)
    self.assertEqual(len(reports), 1)

def test_product_grouping_keeps_different_flavors_separate_with_synonyms(self) -> None:
    posts = [
        Post(id="p1", brand="7-11", product_name="起司蛋糕", author="a1", author_score=80),
        Post(id="p2", brand="7-11", product_name="草莓蛋糕", author="a2", author_score=82),
    ]
    reports, _ = run_pipeline(posts)
    self.assertEqual(len(reports), 2)
```

## 驗收

- 所有既有 58 測試 + 新測試全過
- `_DISTINCTIVE_TERMS` 保護仍有效（不同口味不被合併）
- 同義詞對正確正規化
- 噪音詞從商品名中清除
- 先跑測試確認綠燈再 commit，不要 push
