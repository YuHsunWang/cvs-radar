# Codex 任務：ij2 可疑帳號偵測強化（樣板化/爆發性 + 維運後台）

> Claude 已拍板。Codex 執行，完成後 Claude 獨立驗證。**先單獨跑測試確認綠燈再 commit（勿串同條指令）。**

## 背景

`cvs_radar/preference.py` 已有 4 個弱訊號特徵（one_sided, single_brand, extreme, repeated_text）用於計算帳號可疑分數。PRD F4.3 P2 要求強化「樣板化」和「爆發性」偵測，F4.6 P1 要求維運後台可檢視明細。

## 任務 A：樣板化偵測升級

修改 `cvs_radar/preference.py`：

1. 將 `_repeated_text_ratio()` 升級（或替換）為 `_template_like_ratio(texts)`：
   - **完全重複**：保留原邏輯（去空白後完全相同）
   - **近似文本**：去標點符號後，用 character-level bigram Jaccard 相似度。兩段文字 Jaccard ≥ 0.8 視為同一模板組。使用 Union-Find 做分組，把所有互相近似的文字歸為同一群。
   - **超短泛用排除**：長度 ≤ 3 個字元的文字（如「推推」「好吃」「讚」）**不計入**樣板判定（這些是正常行為，不應視為可疑）。
   - 最終 ratio = (屬於任何重複/近似群組的留言數) / (符合長度門檻的留言總數)。若符合門檻的留言 < 3 則，回傳 0.0。
2. `_suspicion_features()` 中把 `"repeated_text"` 改為 `"template_like"`，呼叫新函式。

## 任務 B：爆發性偵測（新增）

在 `cvs_radar/preference.py` 新增：

1. `_burst_ratio(brand_timestamps: dict[str, list[datetime]]) -> float`：
   - 輸入：每個品牌對應的留言時間戳列表
   - 對每個品牌，把留言按時間排序，用滑動視窗偵測：任何 `burst_window_hours` 時間窗口內有 ≥ `burst_min_count` 則留言，這些留言都算 burst 留言
   - burst_ratio = burst 留言總數 / 所有留言總數
   - 窗口和門檻從 config 讀取
2. 修改 `build_profiles()`：收集每個帳號對每個品牌的留言時間戳（`comment.posted_at`），傳給 `_burst_ratio()`。注意 `posted_at` 可能是 `None`（跳過這些）。
3. `_suspicion_features()` 加入 `"burst"` 特徵。

## 任務 C：Config 更新

修改 `cvs_radar/config.py` 的 `SUSPICION`：

```python
SUSPICION = {
    "min_activity": 5,
    "weight_floor": 0.1,
    "feature_weights": {
        "one_sided": 0.35,
        "single_brand": 0.20,
        "extreme": 0.20,
        "template_like": 0.10,  # 改名 from repeated_text
        "burst": 0.15,
    },
    "burst_window_hours": 24,
    "burst_min_count": 3,
}
```

## 任務 D：維運後台明細

在 `cvs_radar/reporting.py` 新增：

1. `render_suspicion_detail(profile: AccountProfile, posts: list[Post]) -> str`：
   - 帳號基本資料（總留言數、信度、可疑分）
   - 各品牌互動明細（每品牌留言數、平均情感）
   - 各特徵計算結果和解釋
   - 列出被標記為 template/burst 的具體留言（文字+時間，最多各顯示 10 則）
2. 這個函式由維運者呼叫（不對外暴露）。

## 任務 E：測試

在 `tests/test_core.py`（或新建 `tests/test_suspicion.py`）新增：

1. **burst 偵測**：
   - 同帳號對同品牌在 2 小時內留 5 則 → burst ratio > 0
   - 同帳號留言分散在不同天 → burst ratio = 0
   - posted_at 為 None 的留言被安全跳過
2. **template_like 升級**：
   - 完全相同文字 → ratio 高
   - 近似文字（只差一兩個字）→ ratio 高
   - 完全不同文字 → ratio = 0
   - 超短泛用文字（「推」「讚」）不計入
3. **維運明細**：render_suspicion_detail 輸出含有各特徵名稱
4. **既有 49 測試全過**
5. **回歸**：確認 scoring 中 `credibility` 仍正常運作（原有的 `repeated_text` 改名不會斷掉 scoring 邏輯）

## 驗收（Claude 獨立複驗）

- feature_weights 改名 + 新增不會造成 KeyError
- burst 邏輯正確（滑動視窗、config 可調）
- template_like 改善明顯（近似文本能抓到）
- render_suspicion_detail 可呼叫且輸出可讀
- 全測試通過
- 先驗測試再 commit，不要 push（Claude 驗完再 push）
