# CVS Radar — 超商食物評價雷達 (v0)

從 PTT `CVS` 板蒐集超商食物評價,做情感分析與可信度加權,為每個商品產出
**公正分數**與**評價共識**(一致好評 / 評價兩極 …),幫你在超商現場快速避雷。

前端是一支手機優先的 shopper App:把分數、共識與真實心得整理成站在貨架前十秒能看懂的樣子。

本 v0 依 `CVS-Radar-PRD-v0.2.md` 實作。三項關鍵決議已內建:
1. 作者自評分 + 推文 **合併成單一評分**。
2. 可疑帳號 **只做內部降權,對外不公開個別標籤**。
3. 作者與留言依 `cvs_radar.config.SCORING["role_weight"]` 加權,並套用貝氏收斂與信度下限。

## 安裝
```bash
pip install -r requirements.txt
```

## 使用
```bash
python run.py --demo               # 用離線樣本跑(無需網路)
python run.py --demo --internal    # 額外顯示貢獻者與可疑分(維運用)
python run.py --crawl --pages 5    # 實際爬 PTT(需網路)
python run.py --demo --json out.json
python run.py --demo --brand 7-11 --min-score 60 --limit 10
```
> 注意:開發沙箱擋掉 `ptt.cc`,`--crawl` 需在你自己有網路的機器執行。
> `--demo` 使用 `cvs_radar/sample_data.py` 的離線範例貼文(仿真情境、非真實帳號)以驗證分析邏輯。

## 架構
```
PTT → crawler → parser → [Post]
                            │  sentiment(推噓先驗+詞典)
                            ▼
                     preference(帳號偏好 + 可疑分)
                            │  → 信度權重
                            ▼
                     scoring(50/50 合併 + 貝氏收斂 + 每人折一票)
                            │
                            ▼
                     consensus(一致/兩極/資料不足) → reporting(去識別化)
```

| 檔案 | 職責 |
|---|---|
| `cvs_radar/config.py` | 品牌表 + 所有可調參數(PRD §14) |
| `cvs_radar/models.py` | 資料模型 |
| `cvs_radar/crawler.py` | PTT 爬取(速率限制、重試、增量快取) |
| `cvs_radar/parser.py` | 解析文章欄位 + 推文(含邊界情況) |
| `cvs_radar/sentiment.py` | 留言情感(推噓標籤 + 中文詞典,可插拔) |
| `cvs_radar/preference.py` | 帳號品牌偏好 + 可疑訊號 |
| `cvs_radar/scoring.py` | 商品識別 + 公正分數 + 共識分類 |
| `cvs_radar/pipeline.py` | 串接主線 |
| `cvs_radar/reporting.py` | 文字 / JSON 輸出(對外去識別化) |
| `cvs_radar/sample_data.py` | 離線樣本(含 PRD 端到端情境商品) |
| `scoring.py` | 舊路徑相容匯出 |

## 設計重點
- **推噓標籤為情感主訊號**:PTT 短留言反諷多,純文字模型誤判率高;推/噓是作者明確表態,最可靠。詞典只做微調。後端可換 SnowNLP / LLM。
- **貝氏收斂**:低樣本商品不會因一兩則極端留言爆衝;向先驗 μ0 收斂並回報信心度。
- **每人每商品折一票 + 作者自推排除**:避免單一帳號洗版主導。
- **可疑帳號降權而非過濾**:保留資訊、降低操作影響,且可解釋;低於活動量門檻不評分。

## 測試
```bash
python -m unittest discover -s tests
```

測試涵蓋 PTT 欄位解析、分數邊界格式、商品正規化、同帳號折票、作者自推排除、公開 JSON 去識別化。

## 已知限制(詳見 PRD §11)
- 可疑偵測是**啟發式弱訊號**,真實品牌粉與工讀生難以區分 → 故僅內部降權、不公開指控。
- 情感詞典為種子版,反諷/迷因仍會誤判。
- 商品識別 v0 以品牌+正規化名,名稱變體可能誤分(模糊比對列為後續)。

## 後續(v1)
接 Dcard(`Source` 介面已預留)、情感換 LLM、簡易查詢介面 / Web dashboard。
## 更多用法

## CLI

```bash
# 列出目前資料中的品牌
python run.py --demo --list-brands

# 指定日期區間，只用該區間內的貼文/留言重新評分
python run.py --demo --start-date 2026-06-01 --end-date 2026-06-07

# 近 N 天篩選
python run.py --demo --recent-days 14

# 指定品牌後輸出該品牌商品排名，並套用最低分與樣本條件
python run.py --demo --brand 7-11 --min-score 50 --min-n-eff 1 --min-comments 1 --limit 10

# 爬 PTT 後套用同樣條件
python run.py --crawl --pages 5 --recent-days 30 --brand 7-11
```

## 服務層 API

前端或 HTTP handler 可直接呼叫 `cvs_radar.service`：

```python
from cvs_radar.sample_data import load_sample
from cvs_radar.service import ProductQuery, list_brands, query_products, select_reviews

posts = load_sample()
selected = select_reviews(posts, start_date="2026-06-01", end_date="2026-06-07")
brands = list_brands(posts)
result = query_products(posts, ProductQuery(brand="7-11", min_score=50, recent_days=30))
payload = result.to_dict()
```

時間篩選會同時約束貼文與留言；若舊貼文下有落在區間內的新留言，系統會保留商品脈絡與該留言，但不使用舊貼文作者評分。

## Streamlit shopper App（手機優先）

安裝依賴並啟動：

```bash
pip install -r requirements.txt
streamlit run app.py
# 若 streamlit 指令不在 PATH，可改用：
python -m streamlit run app.py
```

介面是為「站在超商貨架前快速挑選」設計的手機單欄版面。資料一律用本地預算結果（`data/results.json`），不連網，也沒有資料來源選單。公開版的 `data/results.json` 已去識別化，僅保留商品層級的公正分數與共識，不含任何帳號或逐帳號剖繪。

列表上方常駐這些篩選：

- 搜尋框：直接打商品名或品牌，即時縮小清單。
- 分類、品牌 chips：一點就切換（品牌順序 7-11 / 全家 / 萊爾富 / OK / 其他）。
- 發文區間 chips：全部 / 近 7 天 / 近 30 天 / 近 90 天 / 近半年。
- 更多條件：最低分、最低有效樣本、最少貼文與留言收在這顆按鈕裡。

每一列用顏色標出綜合分數（綠 / 黃 / 紅）、實際正向比例，以及這則判斷是幾則留言算來的。點任一列，該商品的單品判斷（喜歡的點、要留意的點、聲量、原PO心得節錄、討論連結）就地展開。UI 只負責輸入與呈現，查詢與排名走 `cvs_radar.service`；預算結果的載入用 `st.cache_data` 快取，避免每次互動重讀。

## FastAPI JSON 端點

啟動 API：

```bash
uvicorn cvs_radar.api:app --reload
# 若 uvicorn 指令不在 PATH，可改用：
python -m uvicorn cvs_radar.api:app --reload
```

常用端點：

```bash
curl "http://127.0.0.1:8000/health"
curl "http://127.0.0.1:8000/brands?source=demo&recent_days=30"
curl "http://127.0.0.1:8000/products?source=demo&brand=7-11&min_score=50&limit=10"
```

API 預設使用 demo 離線資料；只有明確傳入 `source=crawl` 時才會嘗試連線抓取。

## 人工標註與離線評測

這套流程用來建立 gold labels，之後比較現有規則與 LLM/fine-tune 模型。預設只使用 `cvs_radar.sample_data`，不需要網路或 API key。

### 1. 產生待標 CSV

```bash
python -m cvs_radar.labeling --source demo --output data/labels/to_label.csv --limit 50
```

欄位包含留言文字、貼文品牌、商品、tag、context，以及空白標註欄：
`sentiment`, `target_brand`, `is_comparative`, `favored_brand`, `notes`。

若未來要改用 crawl 來源：

```bash
python -m cvs_radar.labeling --source crawl --pages 5 --output data/labels/to_label.csv
```

### 2. 人工標註

請依照 `docs/labeling_guideline.md` 填寫：

- `sentiment`: `正` / `負` / `中性`
- `target_brand`: `本牌` / `他牌:<品牌>` / `無`
- `is_comparative`: `是` / `否`
- `favored_brand`: `本牌` / `他牌` / `平手` / `不明`

### 3. 跑規則 baseline 評測

repo 內建 smoke gold：

```bash
python -m cvs_radar.evaluation --gold data/labels/gold_smoke.csv
python -m cvs_radar.evaluation --gold data/labels/gold_smoke.csv --json data/labels/rules_report.json
```

評測會輸出：

- `sentiment_polarity`: 情感三分類 accuracy / macro precision / macro recall / macro F1
- `comparative_detection`: 是否比較句的 binary accuracy / precision / recall / F1
- `competitor_preference_detection`: 是否判為他牌勝出的 binary metrics
- `favored_direction`: 僅在 gold 比較句上評估 `本牌` / `他牌` / `平手` / `不明`
- `target_brand`: `本牌` / `他牌` / `無` 的輔助評估

`cvs_radar.evaluation.Predictor` 是預留介面；目前可用 `RuleBasedPredictor`，之後可接 LLM predictor，但規則 baseline 不依賴網路。
