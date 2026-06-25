# Codex 任務：ij2 維運後台 F4.6（帳號信度維運 Streamlit 頁面）

> Claude 已拍板。Codex 執行，完成後 Claude 獨立驗證。**先單獨跑測試確認綠燈再 commit（勿串同條指令）。**

## 背景

`cvs-radar-ij2` 的偵測邏輯（樣板化/爆發性特徵 F4.3）已在前次 commit (`0808df7`) 完成。本次任務是 F4.6：維運後台，讓資料維運者在 Streamlit 介面上檢視帳號可疑訊號明細與各特徵貢獻，供人工覆核。

## 已有的基礎

- `cvs_radar/preference.py`：`build_profiles(posts)` → `dict[str, AccountProfile]`，每個 profile 含 `suspicion_score`, `suspicion_features`, `credibility`, `brand_stats`, `lean_brand`, `total_comments`
- `cvs_radar/reporting.py`：
  - `render_suspicion(profiles)` → 全帳號摘要文字
  - `render_suspicion_detail(profile, posts)` → 單一帳號明細文字（含品牌互動、特徵明細、template/burst 標記留言）
- `cvs_radar/pipeline.py`：`run_pipeline(posts)` → `(list[ProductReport], dict[str, AccountProfile])`
- `app.py`：目前只有商品排名，無 tabs

## 只能改的檔案

- `app.py`
- **不可改其他檔案**

## 任務 A：加入 tabs

修改 `app.py` 的 `main()` 函式：

1. 保留現有的 sidebar（資料來源、時間選擇、進階篩選），這些控制 data loading，兩個 tab 共用
2. 在 data loading 後加入 `tab1, tab2 = st.tabs(["商品排名", "帳號信度維運"])`
3. 把現有的品牌 selectbox + query + render 移到 `with tab1:` 區塊內
4. 新增 `with tab2:` 區塊放維運後台

## 任務 B：維運後台 tab 內容

在 tab2 區塊內實作以下功能。需要 profiles 資料，做法：在 tab2 區塊裡呼叫 `run_pipeline()` 取得 `(reports, profiles)`。

### B1：帳號概覽表

```python
from cvs_radar.pipeline import run_pipeline

# 在 tab2 裡：
reports, profiles = run_pipeline(
    posts,
    start_date=controls["start_date"],
    end_date=controls["end_date"],
    recent_days=controls["recent_days"],
)

# 只顯示有特徵（達活動量門檻）的帳號
active_profiles = [
    p for p in sorted(profiles.values(), key=lambda x: -x.suspicion_score)
    if p.suspicion_features
]
```

- 用 `st.slider("最低可疑分", 0.0, 1.0, 0.0, 0.01)` 讓維運者過濾
- 用 `st.dataframe()` 顯示表格，欄位：帳號, 留言數, 傾向品牌, 可疑分, 信度

### B2：帳號明細檢視

- 用 `st.selectbox("選擇帳號", ...)` 讓維運者選帳號
- 選定後顯示：
  1. **Metrics 列**：用 `st.columns(4)` + `st.metric()` 顯示 total_comments, credibility, suspicion_score, lean_brand
  2. **品牌互動**：用 `st.dataframe()` 或逐行列出每品牌的留言數和平均情感
  3. **特徵明細**：列出 5 個特徵（one_sided, single_brand, extreme, template_like, burst）的值和說明文字
  4. **被標記留言**：呼叫 `render_suspicion_detail(profile, posts)` 取得文字，用 `st.text()` 或 `st.code()` 顯示

### B2 的特徵說明文字參考

```python
explanations = {
    "one_sided": "偏向單一品牌正面、競品負面的程度",
    "single_brand": "留言集中在單一品牌的程度",
    "extreme": "極端情感留言比例",
    "template_like": "完全重複或近似樣板留言比例",
    "burst": "同品牌短時間爆發留言比例",
}
```

## 任務 C：import 整理

在 `app.py` 頂部新增需要的 import：

```python
from cvs_radar.pipeline import run_pipeline
from cvs_radar.reporting import render_suspicion_detail
```

## 驗收

- 所有既有 58 測試全過（`cd /home/user/github-work/YuHsunWang/cvs-radar && .venv/bin/python -m pytest tests/ -q`）
- 商品排名 tab 行為完全不變
- 維運後台 tab 能顯示帳號表 + 明細
- 不修改 app.py 以外的檔案
- 先跑測試確認綠燈再 commit，不要 push
