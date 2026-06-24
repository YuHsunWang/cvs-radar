# Codex 任務：e9d 情感後端升級 + j1g 評測（合併一輪）

> Claude 已拍板（方案 C：後端可插拔 + gold set 比較；LLM 預設關、有 key 才啟用）。Codex 執行，完成後 Claude 獨立驗證。

## 鐵則
1. 用本專案 `.venv`（uv 建的）；新依賴加進 requirements.txt 並 `uv pip install -p .venv`。
2. **不得捏造 gold 標籤**：gold labels 是人工標註的 ground truth；人工標註與真實 PTT 爬蟲是**使用者那邊的事**（沙箱擋 `ptt.cc`）。你只能用現有已標資料評測、並產「待標 CSV」給使用者。
3. 保持 PRD F3.2：**推噓標籤為情感主訊號**，後端只改善「留言文字」那部分；別讓後端蓋過推噓先驗。
4. 每個主要函式有測試；commit 前先單獨跑測試確認綠燈（勿與 commit 串同條指令）。

## 環境
- repo `/home/user/github-work/YuHsunWang/cvs-radar`。SnowNLP 需 `uv pip install -p .venv snownlp`（加進 requirements.txt）。
- 既有：`cvs_radar/sentiment.py`（可插拔，現 backend="lexicon"=推噓先驗+詞典）、`cvs_radar/evaluation.py`、`cvs_radar/labeling.py`、`data/labels/gold_smoke.csv`(8筆)、`config.py` SENTIMENT。

## 任務
### A. 後端可插拔（e9d）
1. `sentiment.py` 新增 **SnowNLP backend**（離線；對留言文字算情感，融合推噓先驗權重沿用 config `tag_prior_weight`）。
2. 新增 **LLM backend 介面**（可插拔；provider/model/api_key 由 env 或 config 取；**預設關閉，沒 key 自動 fallback 到 lexicon/snownlp，不得報錯**）。不要硬接特定家、不要在沒 key 時呼叫網路。
3. backend 由 `config.SENTIMENT["backend"]` 選（lexicon / snownlp / llm）。
### B. 評測比較（j1g）
4. 用 `evaluation.py` harness 在 `data/labels/gold_smoke.csv`（及任何更大的已標 gold csv 若存在）比較 **lexicon vs snownlp vs (llm 若有 key)** 的**情感極性準確率**。輸出 `outputs/eval/backend_comparison.csv`。**明確標註 gold_smoke 只有 8 筆、統計上不足**。
5. 用 `labeling.py` 從 demo sample 產更大的「待標 CSV」`data/labels/to_label_v1.csv`（給使用者人工標），不要自己填標籤。
### C. 報告 + 測試
6. `CVS_SENTIMENT_UPGRADE_REPORT.md`：各 backend 在現有 gold 的極性準確率、距 §15 目標(≥80%)狀態、**明確說明「達標的代表性驗證需使用者人工標註更大集合 + 真實爬蟲（沙箱擋 ptt.cc）」**。
7. 測試：backend 可切換、無 key 時 LLM 正確 fallback 不報錯、snownlp backend 可跑、評測 harness 可跑、無捏造標籤。既有 39 測試仍須過。

## 驗收（Claude 獨立複驗）
- backend 三選一可切；無 key LLM 不報錯（fallback）。
- 評測有 lexicon vs snownlp 的極性準確率數字（標小樣本 caveat）。
- 產出 to_label CSV 供人標、未自填標籤。
- 全測試通過、未動其他模組行為（推噓先驗仍為主）。
