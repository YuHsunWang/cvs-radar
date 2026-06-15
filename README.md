# CVS Radar — 超商食物評價雷達 (v0)

從 PTT `CVS` 板蒐集超商食物評價,做情感分析與可信度加權,為每個商品產出
**公正分數**與**評價共識**(一致好評 / 評價兩極 …),幫你在超商現場快速避雷。

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
> `--demo` 的樣本含一篇真實 PTT 文(阜杭豆漿饅頭夾豬排蛋)以驗證分析邏輯。

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
python -m compileall .
```

測試涵蓋 PTT 欄位解析、分數邊界格式、商品正規化、同帳號折票、作者自推排除、公開 JSON 去識別化。

## 已知限制(詳見 PRD §11)
- 可疑偵測是**啟發式弱訊號**,真實品牌粉與工讀生難以區分 → 故僅內部降權、不公開指控。
- 情感詞典為種子版,反諷/迷因仍會誤判。
- 商品識別 v0 以品牌+正規化名,名稱變體可能誤分(模糊比對列為後續)。

## 後續(v1)
接 Dcard(`Source` 介面已預留)、情感換 LLM、簡易查詢介面 / Web dashboard。
