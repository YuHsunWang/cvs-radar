# PTT 爬蟲規劃與執行（CVS Radar）

> 2026-06-23。爬蟲模組 `cvs_radar/crawler.py` 已實作（PRD F1），本檔規劃**如何執行**與資料→標註→評測迴圈。
> ⚠️ 開發沙箱擋 `ptt.cc`，**爬蟲只能在你有網路的機器跑**。

## 爬蟲現況（已具備，不用重寫）
- F1.1 從 `bbs/CVS/index.html` 往回翻頁，支援 `max_pages` / 日期區間 / `recent_days`
- F1.4 禮貌爬取：`request_delay_sec`（預設 1s）、`timeout`、失敗**指數退避重試**
- F1.5 增量：`seen_urls` 快取（`.cvs_radar_seen.json`），重跑只抓新文
- **over18 cookie 已設**（`over18=1`），不會卡 PTT 年齡牆
- 自訂 User-Agent

## 執行步驟（在你有網路的機器）
```bash
cd cvs-radar
python -m venv .venv && .venv/bin/pip install -r requirements.txt   # 或既有環境
# 1) 直接爬 + 看結果
python run.py --crawl --pages 30 --json out.json
# 2) 只要近 N 天 / 指定區間
python run.py --crawl --pages 50 --recent-days 30
python run.py --crawl --pages 50 --start-date 2026-05-01 --end-date 2026-06-01
# 3) 爬完直接產「待標 CSV」給人工標（擴大 gold）
python -m cvs_radar.labeling --source crawl --pages 30 --output data/labels/to_label_v2.csv
```
標完把 `to_label_v2.csv` 放回 `data/labels/`，再用評測 harness 比 lexicon/SnowNLP（同 gold_v1 流程）。

## 建議
- **資料量目標**：標到 ~100–300 則留言，極性準確率才算統計穩健（現在 gold_v1 只有 17 則）。
- **禮貌**：delay 維持 ≥1s；大量爬分批、別一次幾百頁；尊重 PTT。
- 增量快取讓你可每天小量累積，不重抓。

## 重複 / 多段留言：目前處理方式
- **重複留言（同帳號多則）**：`scoring.per_user_cap=True` → 同帳號在同商品的多則留言**取平均、折成一票**，避免洗版主導。
- **作者自推**：`exclude_self_push` 排除。
- **代表性留言**：`_dedupe_ranked_comments` 去重後才呈現。
- **多段留言（同帳號連續多行）**：每行是獨立 Comment，但同帳號 → 一樣被 per_user_cap 折成一票（平均）。
- ⚠️ **限制（改進點）**：多段是「每行各自算情感分再平均」，**不是把多段文字接起來再算**。若一句話跨行才完整（否定詞/語氣在下一行），單行情感可能誤判。改進＝parser 層把同帳號連續 push 合併成單一 Comment 再算情感（見 beads issue）。
