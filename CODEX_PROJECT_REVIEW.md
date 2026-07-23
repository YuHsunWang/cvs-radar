# CVS Radar 全專案程式碼審查

審查日期：2026-07-23  
審查模式：唯讀；排除 `.git`、虛擬環境、`node_modules`、快取、`.next`、`web/out`、`web/.vercel`、build/dist/temp 與 `legacy/`。本報告是唯一新增檔案。

## 1. Executive Summary

### 架構摘要（Phase 1）

CVS Radar 是一條「公開 PTT CVS 文章 → 商品級購買參考 → 靜態網站」資料鏈。主要入口為 CLI `run.py:19-113`、排程 `crawl_job.py:36-120`、以及可選的 FastAPI `cvs_radar/api.py:27-115`。`PttCrawler` 先抓列表及文章並套同源 URL 限制（`cvs_radar/crawler.py:44-98,116-122`），`parser.py` 轉為 `Post`/`Comment`（`cvs_radar/parser.py:87-126`），`store.py` 以 JSONL 保存 raw posts（`cvs_radar/store.py:98-135`）。

管線由 `cvs_radar/pipeline.py:14-34` 串接時間篩選、商品正規化/拆分、情緒標註、人工覆寫、帳號可信度輪廓及商品評分，結果寫入 `data/results.json`（`cvs_radar/store.py:260-276`）。`web/build_data.py:143-166` 再投影為不含帳號欄位的 `web/public/data.json`，Next.js build 時讀入整包資料（`web/app/page.tsx:6-12`），之後搜尋、品牌/分類/日期篩選、排序與展開都在瀏覽器執行（`web/components/ProductExplorer.tsx:38-64`）。GitHub Pages 以 static export 部署（`.github/workflows/pages.yml:35-59`）；Vercel 設定依賴控制台中的 `web/` Root Directory（`README.md:151-153`），repo 內無 `vercel.json`。

責任邊界整體可辨識，但 `cvs_radar/scoring.py` 達 1,980 行，集商品抽取、正規化、分類、競品歸因、業配偵測、計分與摘要選句於一檔；設定又同時存在 `config.yaml:1-375` 與 `cvs_radar/config.py:12-193` 的預設副本。新增商店、資料來源或規則時會同時碰 parser、scoring、config、store schema、web enum 與文件，耦合偏高。

### 整體判斷

目前專案已有相當完整的端到端雛形：資料來源可追溯、crawler 有 timeout/retry/delay 與 SSRF 同源防線、評分有低樣本抑制與一人一票概念、公開前端 payload 的確不含 identity keys，且測試/靜態檢查目前全過。唯讀驗證輸出為：Python `167 passed, 17 subtests passed`（3 個第三方 deprecation warnings）、Vitest `20 passed`、Ruff `All checks passed!`、`tsc --noEmit --incremental false` exit 0。

但目前不能把「測試綠」等同於產品正確：測試把錯誤的 fair-score 前端契約固定下來，沒有檢查公開 repo 中的 contributor 帳號、商品 ID 唯一性或完整發布鏈。最嚴重的是 tracked 的 `data/results.json` 仍含 11,719 筆 contributor 紀錄、3,443 個唯一 PTT 帳號，並附 role/score/weight；`profiles=[]` 並不足以去識別。這與 `README.md:69-74`、`docs/DECISIONS.md:7-10` 的隱私承諾直接衝突。

### Top problems

1. **公開 repo 發布個人評分檔案，違反自訂 Privacy by Design**：問題非帳號名稱外洩（PTT 本就公開），而是 committed `results.json` 帶有系統對 3,443 個具名帳號算出的 `score/weight` 衍生評分；清理腳本與 privacy test 只清/驗 profiles，漏了 contributors，與 README/DECISIONS Q2 的承諾直接衝突（Issue 1）。
2. **核心推薦分數被前端完全忽略**：校準後的 `recommendationScore` 只被當成 null gate，顯示及四種排序實際使用 `fairScore`（Issue 2）。
3. **當前公開資料已有兩組 ID 碰撞**：造成重複商品、React key 衝突與共用展開狀態（Issue 3）。
4. **品牌與時間處理會實際算錯或崩潰**：`OK` 子字串誤判，以及 naive/aware datetime 混用（Issues 4、5）。
5. **資料更新的耐久性不足**：JSONL 任一壞行可阻斷全量重算；正式更新又依賴 repo 外的作者本機管線（Issues 6、9）。

### 值得保留的強項

- crawler 對文章及分頁 URL 皆做同源/路徑 allowlist，且具 timeout、retry、delay（`cvs_radar/crawler.py:67-114,116-122`）。
- YAML 使用 `safe_load`，時間篩選會 clone 物件而非污染輸入（`cvs_radar/config.py:200-208`、`cvs_radar/filters.py:113-145`）。
- 公開 web payload 目前無 `profiles/contributors/user/author/raw` 等 identity keys；本次工具檢查 740 筆、904 個外連皆為 HTTPS PTT，百分比總和均為 100。
- 低可信度商品不顯示推薦分及情緒分布，單篇貼文的公開信心度也有限制（`web/build_data.py:86-101,104-109`）。
- 前端搜尋有 NFKC 正規化、排序不 mutate 原陣列，多數互動使用原生語意元素與 ARIA（`web/lib/data.ts:53-55,134-175`；`web/components/ProductCard.tsx:52-57`）。
- 測試對 parser、情緒、分組、時間邊界、一人一票與資料建置已有可觀的回歸基礎；CI 同時跑 backend、web test 與 production build（`.github/workflows/ci.yml:13-55`）。

### 公開可用性與 must-fix-now

**靜態網站本身可暫時維持公開服務，但公開 repo/發布流程不宜在未修 Issue 1 前宣稱完成去識別化。** 沒有發現可直接遠端接管網站的 Critical；Critical 數量為 0。然而 Issue 1 是隱私 P0，應立即停止再提交含 contributors 的 results、清理目前版本，並評估 git history 中既有帳號資料的移除與必要通知。Issues 2–6 也應在下一次資料發布前處理，否則分數、品牌、日期或資料更新仍可能系統性失真。

## 2. Issue list

### 1. High — Security — 公開 repo 發布了「個人評分檔案」，違反專案自訂的 Privacy by Design

- **釐清（framing 修正）**：問題**不是** PTT 帳號名稱本身外洩——帳號名稱與其原始留言本就在 PTT 公開，任何人點原文連結即可查證，這部分不構成新的洩漏。真正的問題是 `data/results.json` 發布了 PTT 上**不存在的衍生資料**：系統對每個具名帳號算出的意見分數 `score` 與可信度權重 `weight`，聚合成一份 machine-readable 的跨商品個人評分索引。
- **描述**：committed 的 `data/results.json`（repo 已確認為 **PUBLIC**：`github.com/YuHsunWang/cvs-radar`）中，`profiles` 雖為空，788/789 個 reports 仍帶 `contributors`；工具統計為 11,719 筆、3,443 個 unique `user`，每筆含 `role/score/weight`（例：`{"user":"nicedog","role":"commenter","score":0.9,"weight":0.2817}`）。任何人 `git clone` 即取得零聚合成本的全量個人評分檔，且 git history 會永久保留（即使日後修掉，或原帳號在 PTT 刪文）。
- **證據**：實際資料可見 `data/results.json:14-25`；serializer 主動輸出帳號於 `cvs_radar/store.py:167-170`；de-identify 步驟 `scripts/strip_profiles.py:15-18` 只做 `payload["profiles"] = []`，漏清 `contributors`；workflow 於 `.github/workflows/refresh-data.yml:76` 執行 strip 後 commit `data/results.json`；隱私測試只 assert `results["profiles"] == []`（`tests/test_publish_privacy.py:14`）。`web/README.md:3` 明稱 data.json「generated from the **de-identified** `../data/results.json`」，但該檔實際並未去識別。
- **為何仍成立（不因「PTT 已公開」而消失）**：此為專案**自訂設計決策**的實作破綻，與隱私嚴重度爭論無關——`README.md:69-74`（Privacy by Design）承諾「帳號 profile、**contributors** 與可疑分數**不會輸出**」「**不建立公開個人評分檔案**」；`docs/DECISIONS.md` Q2 更明確決定不公開個別帳號標籤，理由自陳「公開指控真實帳號有**法律/名譽風險**」。`reporting.py` 已有 `public_include_contributors: False` 隱私機制，但 `store.py` 的 results serializer 繞過它，`strip_profiles` 又未補上，導致這道防線有洞。（附註：網站 payload `web/public/data.json` 本身乾淨、不含 contributors，此承諾有守住；破綻僅在 git 追蹤的中間檔 results.json。）
- **可能影響**：公開 repo 提供了對 3,443 個真實帳號的系統評分/可信度權重檔案，直接違反專案自訂承諾並落入其自評的法律/名譽風險；git history 使其具持久性與不可撤回性。
- **建議修正**：`strip_profiles.py` 除 profiles 外一併移除各 report 的 `contributors`（並遞迴禁止 `user/suspicion_*` 等 identity keys）；`tests/test_publish_privacy.py` 改為遞迴斷言 committed results 無任何 contributor/identity 欄位（含 canary handle）；重新產生目前 committed 檔案；另評估以 `git filter-repo` 清除歷史（歷史改寫需另行規劃）。
- **修復難度**：程式低；歷史清理高。
- **建議優先級**：Immediate / P0。

### 2. High — Bug — 校準推薦分數產出後未被顯示或排序使用

- **描述**：Python 產生 0–100 的 `recommendationScore`，但前端 `comprehensiveScore()` 僅用它判斷 null，真正回傳 `fairScore`。
- **證據**：校準/輸出於 `web/build_data.py:75-93,119-139`；錯誤選值於 `web/lib/data.ts:93-95`；卡片顯示使用該函式（`web/components/ProductCard.tsx:42-46,121-128`）；近期推薦與評分排序亦使用它（`web/lib/data.ts:134-151,199-213`）。文件則明稱收合卡應顯示 recommendation score、fair score 留在詳情（`web/README.md:9-12`）。工具檢查 649 筆有 recommendation score，範圍 24–93，fair score 為 20–80，並非同值別名。
- **可能影響**：使用者看到、排序及「近期推薦」衰減的都是未校準指標，核心產品契約與 UI/文件不一致；現有測試反而把 fair-score 行為固定（`web/lib/data.test.ts:158-212`）。
- **建議修正**：先決定唯一的公開分數契約。若 recommendation score 是正式指標，`comprehensiveScore` 應回傳它，詳情另清楚標示 Bayesian fair score；若 fair score 才是正式值，移除無用校準欄與相反文件。補 UI/排序契約測試。
- **修復難度**：低至中。
- **建議優先級**：Immediate / P0。

### 3. High — Bug — 目前公開資料已有商品 ID 碰撞

- **描述**：ID 只由 `brand::productName` 組成，人工覆寫又可能把兩筆改成相同 ID，輸出前沒有 uniqueness check。
- **證據**：ID 建立於 `web/build_data.py:119-120`，覆寫後重建於 `web/build_data.py:60-67`；目前 `7-11::法朋蛋黃酥霜淇淋` 出現於 `web/public/data.json:4518` 與 `:4849`，`全家::香草卡士達生甜甜圈` 出現於 `:12796` 與 `:16040`。前端以 ID 當 React key（`web/components/ProductExplorer.tsx:244-252`）及 expanded Set key（`:89-104`）。
- **可能影響**：公開清單顯示相同商品兩次但分數/聲量/日期不同；點開一筆會讓同 ID 卡片一起展開，React reconciliation 也不可靠。
- **建議修正**：若實為同商品，應在上游合併證據與重算；若需保留不同實體，使用穩定 `product_key`/UUID。無論選擇為何，build_data 應對 ID 唯一性 fail-fast。
- **修復難度**：中。
- **建議優先級**：Immediate / P0。

### 4. High — Bug — ASCII 品牌別名無邊界匹配，`OK` 會命中 `cookie/okay` 等字串

- **描述**：parser 與 competitor attribution 都以無邊界 substring 搜尋別名；誤判後正常留言會被當成他牌內容而排除。
- **證據**：`cvs_radar/parser.py:36-41` 使用 `keyword in haystack`；`cvs_radar/scoring.py:1345-1359` 使用 `find()`；他牌非比較留言直接 `include_score=False`（`cvs_radar/scoring.py:1157-1166`）。唯讀實測輸出為 `infer_brand("", "", "cookie 很好吃") == "OK"`，全家貼文同留言被判 `competitor_brands=("OK",)` 且不計分。
- **可能影響**：含 cookie、okay、smoky 等 ASCII 片段的品名/留言可能錯分 OK，污染品牌統計、競品統計及 fair score。
- **建議修正**：集中共用 brand matcher；中文可保留 substring，ASCII alias 採 Unicode-aware token boundary；`OK` 僅接受獨立詞、`OKmart`、`OK超商` 等明確形式。
- **修復難度**：中。
- **建議優先級**：Immediate / P0。

### 5. High — Bug — 時區策略不一致，會錯篩、漏刷新或在評分時 TypeError

- **描述**：PTT parser 產生 naive 台北時間；filter 遇 aware/naive 直接拔掉 tz；refresh 則把 naive 當 UTC；score_product 對混合 datetime 直接 `max()`。
- **證據**：`cvs_radar/parser.py:283-322`、`cvs_radar/filters.py:162-173`、`cvs_radar/backfill.py:78-92`、`cvs_radar/scoring.py:1602-1606`。唯讀針對性實測確認 aware UTC 邊界錯篩、有效近期資料被判非候選，以及混合日期觸發 `TypeError: can't compare offset-naive and offset-aware datetimes`。
- **可能影響**：日期條件、30 日留言刷新、最新商品日期與計分可能錯誤；一筆 aware 外部/人工資料即可中斷整批。
- **建議修正**：資料進系統即將 PTT naive 時間附 `ZoneInfo("Asia/Taipei")`，持久化統一 UTC aware；比較時轉同一時區，不得用 `replace(tzinfo=None)`；schema 拒絕混合格式。
- **修復難度**：中。
- **建議優先級**：Immediate / P0。

### 6. High — Bug — JSONL append 非原子，任一壞行會阻斷全量更新

- **描述**：新文章直接 append；loader 對每行直接 `json.loads()`，沒有行號診斷、隔離或最後截斷行恢復。
- **證據**：`cvs_radar/store.py:98-115,118-135`；排程隨後一定全量載入重算（`crawl_job.py:95-108`）。refresh 有 atomic writer（`cvs_radar/backfill.py:153-161`），反而凸顯初始 append 路徑不一致。
- **可能影響**：程序中止、磁碟滿、手動誤編或併發執行留下單一半行，就會讓後續 crawl_job 全部失敗。
- **建議修正**：以鎖 + temp/`fsync`/atomic replace 更新；loader 至少回報 path/line 並將壞行 quarantine；對最後截斷行提供明確恢復流程。
- **修復難度**：中。
- **建議優先級**：Immediate / P0。

### 7. High（潛在）— Security — FastAPI 若被部署，可無驗證輸出原始帳號並同步觸發大量 crawl

- **部署現況（已查證）**：`cvs_radar.api:app` **目前並未對外部署**。active repo 無 `vercel.json`/`Dockerfile`/`Procfile`/`fly.toml`/`render.yaml` 等 API-serving 設定（唯一 Dockerfile/compose 在已歸檔的 `legacy/streamlit/`）；`uvicorn` 僅見於 `README.md:122` 的本機 dev 指令（`--reload`）；所有部署 workflow（`pages.yml`/`refresh-data.yml`/`ci.yml`）皆為靜態站或資料任務，無一啟動 FastAPI；`web/DESIGN.md:117` 明言設計上「no server to keep alive」。**故此攻擊面目前不存在**，本項為 latent（潛在）風險，非 live 事故。
- **描述**：`internal=true` 可輸出 raw contributor，`source=crawl` 可在 request 內同步抓最多 50 頁並跑全管線；沒有 auth/rate limit。
- **證據**：`cvs_radar/api.py:68-115`；internal serializer 在 `cvs_radar/reporting.py:144-149`；查詢內 crawl 由 `cvs_radar/app_helpers.py:53-62` 執行。
- **可能影響**：**僅在**有人日後將 `cvs_radar.api:app` 對公網開放時成立——屆時任何人可取得帳號/分數/權重，亦可反覆占用 worker、CPU 並讓服務向 PTT 發送大量請求。與 Issue 1 一致：即使已從發布資料移除 contributors，此 API 路徑仍可重新暴露 raw contributors。
- **建議修正**：公開 API 永遠禁止 internal 欄位；crawl 改排程/佇列，不由 GET 觸發；內部能力另設強制認證、速率限制、timeout 與審計。若確認產品為長期 static-only，亦可直接移除 `api.py` 與 `fastapi/uvicorn` 依賴（同時改善 Issue 20 依賴膨脹）。
- **修復難度**：中（硬化）／低（移除）。
- **建議優先級**：因未部署，降為 Short-term / 防禦性；一旦計畫部署 API 則升為 Immediate。

### 8. High — Bug — `shill_flag/shill_ratio` 在 results round-trip 中遺失

- **描述**：模型與即時計分會產生業配偵測欄位，但 store serializer/deserializer 皆遺漏，載入預算結果後一律回到預設 `False/0.0`。
- **證據**：欄位在 `cvs_radar/models.py:78-79`，賦值在 `cvs_radar/scoring.py:1630-1631`，reporting 會輸出於 `cvs_radar/reporting.py:139-140`；然而 `cvs_radar/store.py:155-184,187-222` 沒有兩欄。唯讀 round-trip 實測亦確認欄位不存在。
- **可能影響**：即時計算與 `--results`/API 預算輸出不一致，維運者無法從發布快照看見原有 flag。
- **建議修正**：升版結果 schema、補雙向欄位與舊資料 migration default，加入完整 `ProductReport` round-trip test。
- **修復難度**：低。
- **建議優先級**：Immediate / P1。

### 9. High — Deployment — production 資料更新依賴 repo 外的單一作者本機

- **描述**：GitHub schedule/push auto-refresh 已停用，workflow 只剩手動 fallback；實際 crawl/rebackfill/label/push 依賴未納入 repo 的本機管線、WSL cron、D: 備份與 Discord healthcheck。
- **證據**：`.github/workflows/refresh-data.yml:3-9`；`docs/runbook-data-recovery.md:8-16,29-40,59-65`。
- **可能影響**：作者機器、磁碟、cron 或私有腳本失效時，網站仍在線但資料可長期陳舊；新維護者只靠 repo 無法重現正式更新/告警/復原。
- **建議修正**：把可重現排程及健康檢查納入 repo 或受管服務；raw store 改放加密耐久儲存並保留版本；定義 freshness SLO、最後成功時間、告警與演練過的 restore。
- **修復難度**：高。
- **建議優先級**：Immediate / P1。

### 10. Medium — Bug — `run.py --results` 接受日期參數但不套用

- **描述**：CLI 先驗證日期，載入 results 後卻只套品牌/分數/數量條件，沒有警告。
- **證據**：`run.py:48-69,90-106`。FastAPI 對相同行為至少加 note（`cvs_radar/api.py:97-104,118-143`），CLI 沒有。
- **可能影響**：使用者以為結果已依 `--start-date/--end-date/--recent-days` 篩選，實際看到全期資料。
- **建議修正**：預算 schema 不支援重算時，遇日期參數直接 parser error；或保存足夠細粒度支援真正時間篩選。
- **修復難度**：低。
- **建議優先級**：Immediate / P1。

### 11. Medium — UX — 「褒貶不一」338 筆被視為低資訊灰色

- **描述**：tone mapping 只認「一致好評」與「評價兩極」，其餘皆為 low；實際 payload 的主流 enum 是「褒貶不一」。
- **證據**：`web/lib/data.ts:233-237`；例子 `web/public/data.json:4525`。本次工具統計「褒貶不一」338/740 筆。
- **可能影響**：近半商品的「意見分歧」被視覺降成普通灰色，使用者容易忽略風險/爭議。
- **建議修正**：後端與前端共用單一 enum；在 migration 前同時將「褒貶不一」「評價兩極」映射 mixed。
- **修復難度**：低。
- **建議優先級**：Short-term / P1。

### 12. Medium — Deployment — `generatedAt` 是 build 時間，不是資料 snapshot 時間

- **描述**：每次無關的 Pages/Vercel rebuild 都會把舊資料標成剛建立。
- **證據**：`web/build_data.py:143-160` 讀 results 後忽略 source `generated_at`，改用 `datetime.now()`；Pages 對每次 main push 重建（`.github/workflows/pages.yml:3-6,35-42`）；UI 顯示它為「資料建立」（`web/components/TopBar.tsx:85-89`）。
- **可能影響**：更新資訊看似新鮮、實際內容可能陳舊，侵蝕資料產品信任。
- **建議修正**：保留並格式化 `data/results.json.generated_at`，另有需要才增加 `siteBuiltAt`，UI 清楚區分「資料更新」與「網站建置」。
- **修復難度**：低。
- **建議優先級**：Immediate / P1。

### 13. Medium — Deployment — Vercel 與 Pages 的資料建置路徑可能分岔

- **描述**：CI/Pages 會先跑 build:data，但 Vercel 文件設定只執行 `npm run build`，依賴已 commit 的 public JSON；CI 生成後也未 fail on diff。
- **證據**：`.github/workflows/ci.yml:47-55`、`.github/workflows/pages.yml:35-42`、`web/README.md:55-62`、`web/package.json:5-10`。
- **可能影響**：PR 可改 results 或 builder 而忘記 commit payload，CI 仍綠；Pages 使用現場生成資料，Vercel 使用舊資料，兩個公開站不同。本次記憶體重建比較為 740/740 exact match，故目前未漂移。
- **建議修正**：CI build:data 後 `git diff --exit-code -- web/public/data.json`；Vercel prebuild 自動生成，或由同一不可變 release artifact 同時部署兩站。
- **修復難度**：低。
- **建議優先級**：Short-term / P1。

### 14. Medium — Security — seed-cache workflow 有 expression/script injection 與 raw-data 暫存風險

- **描述**：dispatch inputs 被直接插入 shell double quotes 與 Python heredoc；runbook 又要求把含帳號 JSONL 上傳至 anyone-with-link/一次性服務。
- **證據**：`.github/workflows/seed-cache.yml:13-20,30-50`；`docs/runbook-data-recovery.md:29-49`。
- **可能影響**：有 workflow dispatch 權限者的惡意/誤植引號可注入 shell/Python；URL 可能出現在 run metadata，raw handles 亦短暫暴露。外部可見性細節 **待驗證**。
- **建議修正**：所有 inputs 經 `env:` 傳入並嚴格 parse；限制 HTTPS/host/Content-Length/hash；改用私有 object storage + 短效 signed URL/secret，不使用半公開臨時分享。
- **修復難度**：中。
- **建議優先級**：Short-term / P1。

### 15. Medium — Bug — parser/backfill/crawler 的失敗分類與恢復不足

- **描述**：article parse 回 `None` 會永久加入 seen；回填與刷新捕捉所有 Exception 後無原因繼續；日期窗排除的已成功文章反而不寫 seen，排程重抓。
- **證據**：`cvs_radar/crawler.py:76-89`；`cvs_radar/backfill.py:41-55,114-137`。
- **可能影響**：暫時反爬頁/HTML schema 變動可造成永久漏文；全面失敗只顯示 updated=0；使用 recent window 又重複請求舊文章。
- **建議修正**：分開「成功解析/非商品/暫時失敗/納入輸出」狀態；按錯誤類型計數與 log；失敗率超門檻就 fail/alert；seen cache 記錄成功解析而非日期命中。
- **修復難度**：中。
- **建議優先級**：Short-term / P1。

### 16. Medium — Performance — 全量資料與全量計算會隨規模線性/次方惡化

- **描述**：前端只 slice DOM，仍一次把整包資料 hydration；商品 grouping 逐篇掃現有群組；LLM 模式逐留言重建 client 並同步呼叫，全量排程又重跑歷史。
- **證據**：`web/app/page.tsx:6-12`、`web/components/ProductExplorer.tsx:38-47,86-87`；`cvs_radar/scoring.py:1064-1082`；`cvs_radar/sentiment.py:103-111,266-273`；`crawl_job.py:95-103`。本次工具量測 public JSON 約 760 KiB/740 筆。
- **可能影響**：行動首載、JSON parse/hydration、商品分組與 LLM 成本會持續上升；LLM 啟用狀態 **待驗證**。
- **建議修正**：前端 index/detail 分片；分組先做品牌/normalized-key blocking 再做決定性相似圖；LLM client 重用、fingerprint 永久快取、只算 delta 並設 batch/timeout。
- **修復難度**：高。
- **建議優先級**：Medium-term / P2。

### 17. Medium — Architecture — `scoring.py` 過度集中，設定與跨層 enum 重複

- **描述**：單一 1,980 行模組同時擁有 parsing-adjacent extraction、normalization、category、attribution、scoring、summary；Python default config 與 YAML 已出現不同值，web 又硬編 brand/category/consensus。
- **證據**：`cvs_radar/scoring.py:1-1980`；例如 default `time_decay_lambda=0.0` 在 `cvs_radar/config.py:43-50`，實際 YAML 為 0.005（`config.yaml:48-58`）；shallow top-level merge 在 `cvs_radar/config.py:196-208`；web enum 在 `web/lib/data.ts:40-51,233-237`。
- **可能影響**：缺 config、局部 override、新品牌/分類/共識規則容易產生不同環境不同行為；修改核心規則的 blast radius 大。
- **建議修正**：先抽出 product identity、attribution、scoring、excerpt 四個純模組；設定做遞迴 merge + schema 驗證；用生成的 shared JSON schema/enum 連接 Python 與 web。
- **修復難度**：高。
- **建議優先級**：Medium-term / P2。

### 18. Medium — Testing — 測試數量足夠，但發布契約、元件與真實 API 邊界缺口大

- **描述**：API 測試直接呼叫 route endpoint，繞過 ASGI validation/serialization/middleware；web 主要測純函式，沒有 component/a11y；privacy test 只驗 profiles；多個資料腳本無直接測試。
- **證據**：自製 client 在 `tests/test_api.py:20-60`；`web/lib/data.test.ts:1-213`；`tests/test_publish_privacy.py:10-14`；CI commands 在 `.github/workflows/ci.yml:21-28,47-55`。`audit_categories.py`、`rebuild_review_excerpts.py`、`relabel_delta.py`、`strip_profiles.py`、`verify_extraction.py` 無對應直接測試（repo-wide test inventory 工具輸出）。
- **可能影響**：本次 Issues 1–3、11–14 全部能在 167+20 tests 皆綠時存在；422/query encoding、focus、payload schema 與發布隱私 regression 不會被抓。
- **建議修正**：優先加入下節列出的 end-to-end publish contract、真實 ASGI、component/a11y、unique ID 與 artifact diff 測試；CI 加 actionlint、dependency audit/SBOM 與 coverage threshold。
- **修復難度**：中。
- **建議優先級**：Short-term / P1。

### 19. Medium — Deployment — 開發容器與正式環境文件已失效

- **描述**：devcontainer 使用 Python 3.11，會開/啟動不存在的 `app.py`，並執行舊 Streamlit 指令；正式 runtime/CI 為 Python 3.12。repo 也沒有 Dockerfile/compose。
- **證據**：`.devcontainer/devcontainer.json:1-32`；`runtime.txt:1`；`.github/workflows/ci.yml:17-20`。工具檢查 `app.py`、`packages.txt`、Dockerfile、compose、`vercel.json` 均不存在。`docs/DECISIONS.md:11-15` 仍稱 Streamlit 為主介面。
- **可能影響**：Codespaces/devcontainer attach 立即失敗或啟動錯應用；新開發者無法依容器得到與 CI 相同環境。
- **建議修正**：更新為 Python 3.12，移除不存在的 app/Streamlit postAttach，加入 backend/web 明確 setup；若不維護容器則刪除 devcontainer，避免提供壞入口。
- **修復難度**：低。
- **建議優先級**：Short-term / P1。

### 20. Medium — Maintainability — 依賴不可重現且 prod/dev/optional 未分層

- **描述**：Python 全是無上限 lower bounds；active code 未引用的 Streamlit 與 optional SnowNLP/OpenAI 被固定安裝；pytest/ruff 又不在 requirements，CI 額外 ad-hoc 安裝。
- **證據**：`requirements.txt:1-8`；README 要求 pytest/ruff（`README.md:127-136`）；CI 額外安裝於 `.github/workflows/ci.yml:21-28`。repo-wide import 掃描只在 active code 找到 FastAPI/requests/bs4/yaml/SnowNLP/OpenAI，沒有 Streamlit。
- **可能影響**：新版本依賴可在無程式變更下破壞 build；新手照 README 安裝 prod requirements 後可能缺驗證工具；攻擊面與安裝時間增加。
- **建議修正**：改 `pyproject.toml` + lock/constraints；分 core、api、nlp-optional、dev extras；移除或把 Streamlit 放 legacy extra；定期 dependency audit。
- **修復難度**：中。
- **建議優先級**：Short-term / P1。

### 21. Medium — Bug — 多商品貼文的模糊訊號會被複製到所有商品

- **描述**：無唯一命中時留言加入每個 bucket；拆分後每份又複製作者分數/心得。
- **證據**：`cvs_radar/scoring.py:811-837,915-938`。
- **可能影響**：只評論其中一項的作者分數或留言可污染同文其他商品的 fair score、共識與 excerpt。
- **建議修正**：逐商品明確歸因；模糊訊號不計分或 fractional weighting；無商品級作者評分時標 uncertain，並用人工標註集量化誤差。
- **修復難度**：高。
- **建議優先級**：Medium-term / P2。

### 22. Medium — Bug — 未知新分類顯示為「其他」，卻無法用「其他」篩選找到

- **描述**：顯示函式會 fallback 到「其他」，filter 函式只接受硬編碼原始分類，兩者語意不一致。
- **證據**：`web/lib/data.ts:82-86,225-230`。目前 740 筆皆屬已知分類，故為 latent bug。
- **可能影響**：上游新增分類後，卡片看起來是「其他」但按「其他」會消失。
- **建議修正**：filter 直接比較 `displayCategory(product.category)`，或讓 build schema 正規化到 web enum。
- **修復難度**：低。
- **建議優先級**：Short-term / P1。

### 23. Medium — UX — 首屏目的/資料新鮮度/分數語意不足，a11y 尚未達完整 AA

- **描述**：首屏只有產品名與 filters，更新時間藏在鈴鐺；分數未標 `/100` 或方法；部分色彩對比不足，dialog focus 管理不完整。
- **證據**：`web/components/TopBar.tsx:51-89`、`web/components/ProductExplorer.tsx:116-231,274-295`、`web/components/ProductCard.tsx:23-27`。本地對白底計算 `#D97706` 3.19:1、`#D64545` 4.38:1、slate-400 2.56:1；dialog 只在 Escape 恢復 trigger（`TopBar.tsx:26-49,76-95`）。
- **可能影響**：新訪客不易在數秒內理解產品與資料時效；低視力/鍵盤/螢幕閱讀器使用者受阻。
- **建議修正**：首屏加一行目的、更新至日期、`x/100` 與方法連結；調深色彩並跑 axe；更新資訊改合適 popover 或完整 focus-trapped dialog。
- **修復難度**：低至中。
- **建議優先級**：Short-term / P1。

### 24. Low — Security — GA4 會送出原始搜尋文字，站內未揭露

- **描述**：GA 啟用時，debounce 後將完整 query 送為 `search_term`；footer 沒有 analytics/privacy 說明。
- **證據**：`web/lib/analytics.ts:5-15,26-30`、`web/app/layout.tsx:35-38`、`web/README.md:37-53`、`web/components/ProductExplorer.tsx:274-295`。
- **可能影響**：使用者可能輸入個資/敏感文字；適用的同意義務依部署地區與 GA 設定而異，**待驗證**。
- **建議修正**：只送 query 長度、命中數或類別，不送原字串；補簡短隱私說明與必要 consent。
- **修復難度**：低。
- **建議優先級**：Short-term / P2。

### 25. Low — Maintainability — 文件與實際產品已漂移

- **描述**：README 商品數、DECISIONS 主介面、DESIGN 元件/排序選項都與實際不同。
- **證據**：`README.md:37` 稱 772 項，實際 payload 工具輸出為 740；`docs/DECISIONS.md:11-15` 稱 Streamlit 為主；`web/DESIGN.md:65,93-103` 仍列不存在的 FilterSheet 與舊排序；現行 UI 在 `web/components/ProductExplorer.tsx:153-204`。
- **可能影響**：新開發者及使用者依錯誤規格做決策，review 時難分辨 dead design 與現況。
- **建議修正**：商品數由 build 產生；decision 標註 superseded；DESIGN 由現行元件/interaction 更新並加「last verified」。
- **修復難度**：低。
- **建議優先級**：Medium-term / P2。

### 26. Low — Deployment — workflow 缺 concurrency/timeout，Actions 未 pin commit SHA

- **描述**：refresh 可同時手動執行，從同 cache 基底重算並推 main；Actions 使用 mutable major tags。
- **證據**：`.github/workflows/refresh-data.yml:20-24,38-44,83-90` 無 concurrency/timeout；例如 `.github/workflows/ci.yml:16-17,33-37`、`pages.yml:21-25` 使用 `@v4/@v5/@v6`。
- **可能影響**：併發 run 可互相 push conflict/覆蓋 cache；上游 tag 變動增加 supply-chain 不確定性。
- **建議修正**：refresh 加不取消進行中工作的 concurrency group 與 job timeout；Actions pin full SHA，交由 Dependabot/Renovate 更新。
- **修復難度**：低。
- **建議優先級**：Medium-term / P2。

### 27. Low — Performance — `web/public/data.json` 與其他輸出採直接覆寫

- **描述**：build_data 直接寫最終檔，程序中斷可能留下截斷 JSON；前端 runtime 又無 schema validation。
- **證據**：`web/build_data.py:159-166`；`web/app/page.tsx:6-9`。
- **可能影響**：本機/Vercel build 中止或磁碟錯誤時，後續 commit/build 可能拿到壞檔。
- **建議修正**：temp file + flush/fsync + atomic replace；寫入前後做完整 payload schema 驗證。
- **修復難度**：低。
- **建議優先級**：Medium-term / P2。

### 28. Low — UX — 代表留言仍含 URL，SEO/share 基礎可再補齊

- **描述**：部分 likes/cautions 含圖片 URL；metadata 已有 title/description/canonical/OG text，但無 OG image、sitemap、robots，且 metadataBase 固定 Vercel。
- **證據**：URL 例見 `web/public/data.json:4534`；工具統計 likes 14、cautions 16 筆含 URL。metadata 在 `web/app/layout.tsx:6-27`，basePath 可變於 `web/next.config.js:2-8`。
- **可能影響**：卡片可讀性與分享預覽品質較差；Pages canonical 是否正確 **待驗證**。
- **建議修正**：代表句在 publish projection 移除 URL；新增 OG image/sitemap/robots，依 deploy target 產生 canonical。
- **修復難度**：低。
- **建議優先級**：Long-term / P3。

## 3. Priority roadmap

### Immediate — correctness / security / site uptime

1. **封住公開帳號資料（Issue 1）**：停止再 commit contributors；補 recursive privacy gate；重產檔案並決定 git history 清理方案。
2. **釐清並修正唯一公開分數契約（Issue 2）**：同步顯示、排序、命名、文件與測試。
3. **修商品 identity（Issue 3）**：合併現有兩組 collision，build 對 unique ID fail-fast。
4. **修品牌 matcher 與時區（Issues 4–5）**：以 regression fixtures 鎖住 cookie/OK、Taipei/UTC、DST-independent 邊界與 mixed datetime 拒絕。
5. **讓 raw store 可恢復（Issue 6）**：atomic/locked write、壞行診斷/quarantine、備份驗證。
6. **若 API 有對外，先關閉 internal/crawl（Issue 7）**；若沒有，明確記錄「not deployed」並在 code 層保持安全預設。
7. 補回 shill schema，CLI results 日期參數 fail-fast，generatedAt 使用 source time（Issues 8、10、12）。

### Short-term（1–2 週）

1. 修 consensus enum、未知分類、前端 runtime schema 與 UI trust/a11y（Issues 11、22、23）。
2. 統一 Pages/Vercel artifact flow，CI 加 generated diff gate（Issue 13）。
3. 強化 crawler/backfill failure telemetry 與 seed workflow input/raw-data handling（Issues 14–15）。
4. 更新 devcontainer、README/DECISIONS/DESIGN 與依賴分層（Issues 19、20、25）。
5. 完成 publish E2E、ASGI integration、component/a11y 與 workflow lint（Issue 18）。

### Medium-term — architecture / tests / ops

1. 將 scoring 單體拆為 product identity、attribution、scoring、excerpt 模組，導入版本化 schema（Issue 17）。
2. 重作 multi-product attribution 與 grouping 決定性/效能（Issues 16、21）。
3. 把正式 refresh、監控、備份與 restore 從作者本機移到可重現受管環境（Issue 9）。
4. 前端採 index/detail 分片，建立 Lighthouse/bundle/freshness SLO。
5. Actions pin SHA、concurrency/timeout、dependency audit/SBOM（Issues 20、26）。

### Long-term — product / tech debt

1. 擴大人工 gold set，量化多商品歸因、反諷、品牌比較與 calibration 誤差；目前 docs 自己指出 gold_v1 僅 17 則（`docs/crawl_plan.md:27-29`）。
2. 顯示方法、資料時效、樣本與「非客觀品質」說明，持續改善可解釋性。
3. 建立 SEO/share assets、sitemap/robots、跨部署 canonical 與實際裝置 a11y/Lighthouse 基線（Issue 28）。
4. 若新增資料源，以 `(source, user)` 為內部 identity，避免不同站台同名帳號合併；目前 profile key 只用 username（`cvs_radar/preference.py:39-50`）。

## 4. Quick wins

1. `strip_profiles.py` 改為同時移除 reports 內 contributors，privacy test 遞迴禁止 identity keys（Issue 1）。
2. 在 `build_data.main()` 結尾 assert `len(ids) == len(set(ids))`，立即阻擋再次發布碰撞（Issue 3）。
3. `comprehensiveScore()` 使用已決定的正式欄位，並加一個「fair 與 recommendation 不同」fixture（Issue 2）。
4. 將「褒貶不一」映射為 mixed，未知 category 以 displayCategory 篩選（Issues 11、22）。
5. `generatedAt` 直接沿用 results 的 `generated_at`，另加 `siteBuiltAt` 才表示 build（Issue 12）。
6. CI 在 `npm run build:data` 後執行 `git diff --exit-code -- web/public/data.json`（Issue 13）。
7. CLI `--results` 配日期參數時明確報錯，不再靜默忽略（Issue 10）。
8. seed workflow inputs 改由 env 讀入並嚴格轉型；refresh 加 concurrency/timeout（Issues 14、26）。
9. devcontainer 換 Python 3.12、移除 `app.py`/Streamlit postAttach；README 數量由 payload 自動產生（Issues 19、25）。
10. GA search 只送 query length/hit count，footer 加資料/分析說明（Issue 24）。

## 5. Recommended test cases

以下依加入順序排列；每個測試都應表達「為何不能退化」，而非只 snapshot 現值。

1. **發布隱私 E2E**：fixture raw post 含已知帳號，跑 pipeline → save_results → strip → build_data；遞迴 assert 最終所有 tracked/public artifacts 都沒有 `user/contributors/profiles/suspicion/author`，也不含 canary handle。
2. **商品 ID 唯一性**：兩筆 report 經 brand/name override 後碰撞，build 必須 fail 或依明確規則合併；不得輸出 duplicate React key。
3. **公開分數契約**：給 `fairScore=50, recommendationScore=60`，驗證卡片、四種排序、近期推薦與 hide-no-score 都使用正式欄位；詳情若顯示另一分數，標籤必須不同。
4. **品牌 token boundary**：`cookie/okay/smoky/WACOOKIES` 不得命中 OK；`OK`、`OKmart`、`OK超商` 必須命中；同規則覆蓋 infer_brand 與 competitor attribution。
5. **時區矩陣**：PTT Taipei naive input、ISO `+08:00`、UTC `Z`、跨日與跨年 push；統一後日期篩選/refresh/latest date 相同，混合非法值 fail-fast 而非 TypeError。
6. **JSONL 損壞/中斷/併發**：中間壞行、最後半行、重複 ID、兩 writer；驗證診斷含行號、健康資料可恢復且既有 store 不被截斷。
7. **ProductReport round-trip**：所有欄位逐一等值，特別是 `shill_flag/ratio`、contributors、日期；舊 schema 有明確 migration/default。
8. **真實 ASGI integration**：用 `httpx.AsyncClient(ASGITransport)` 驗證 422、query bounds、serialization、results date rejection，以及 public response 永不含 internal fields。
9. **Public payload schema**：缺欄、錯型別、未知 enum、非法/未允許 URL、百分比不等於 100、非法日期、空 product name、duplicate ID 都讓 build fail。
10. **多商品歸因**：同文兩商品、只指名其一、模糊留言、作者單一總分；驗證不把單項訊號完整複製給另一項。
11. **爬蟲失敗狀態**：HTTP 200 age wall/schema break 不得永久 seen；404 非商品、暫時 5xx、超時、離站 URL、舊文日期窗各有不同狀態與失敗率告警。
12. **ProductExplorer component**：搜尋×品牌×分類×日期交集、清除、load-more、空狀態、duplicate protection、展開只影響一張卡。
13. **a11y/keyboard**：DateRangeSlider 雙 thumb、TopBar popover/dialog focus/Escape/return focus、320px、200% zoom、axe color/name/role/value。
14. **artifact freshness**：source `generated_at` 被保留；無關 main push 不改資料時間；CI 重建與 committed payload 必須 byte/semantic equivalent。
15. **workflow/script validation**：relabel import 拒絕 blank/NaN/inf/out-of-range/非法 label 並 atomic；actionlint 驗 inputs 只經 env，refresh concurrency 生效。

## 6. Overall scoring

| 面向 | 分數（1–10） | 扣分理由 |
|---|---:|---|
| Functional correctness | 5 | 推薦分欄位未採用、ID collision、OK 誤判、日期參數忽略與多商品污染均會產生錯結果（Issues 2–5、10、21）。 |
| Architecture | 6 | pipeline 分層可讀，但 1,980 行 scoring 單體、schema/enum/config 跨層重複（Issue 17）。 |
| Maintainability | 5 | 設定 shallow merge、文件/容器漂移、依賴未分層；新增 store/source/rule 需跨多層同步（Issues 17、19、20、25）。 |
| Performance | 6 | 現有 740 筆仍可用，但全 payload hydration、近次方 grouping、LLM 無 delta/cache 路徑會隨量惡化（Issue 16）。 |
| Stability | 5 | retry/timeout/atomic refresh 是優點，但 JSONL 單壞行、時區混用與外部更新單點可中斷或悄悄停更（Issues 5、6、9、15）。 |
| Security | 4 | 靜態 web/SSRF allowlist/最小 Actions permissions 不錯，但公開 results 已含 3,443 個帳號，API internal/crawl 與 seed inputs 仍有風險（Issues 1、7、14）。 |
| Test completeness | 6 | 167 Python + 20 web tests 且 lint/typecheck 全過，但目前高嚴重度發布契約錯誤全部漏網，亦缺真實 ASGI、component/a11y、workflow 測試（Issue 18）。 |
| UX | 6 | 手機卡片、原文、低樣本處理與篩選基礎良好；分數契約、mixed tone、更新透明度與 a11y 仍削弱信任（Issues 2、11、12、23）。 |
| Deployment/ops | 4 | Pages/CI/runbook 已存在，但正式 refresh、監控與備份依賴 repo 外單機，Vercel/Pages artifact 可能分岔，devcontainer 已壞（Issues 9、13、19）。 |
| Overall product maturity | 5 | 是有實際資料、公開站與深度測試的成熟 prototype；隱私、核心指標契約、資料身份與可重現維運尚未達穩健公共資料產品標準。 |

## 審查覆蓋與限制

- 實際讀取/結構解析：`cvs_radar/` 19 檔；根入口 3 檔；`scripts/` 9 檔；`tests/` 9 檔；`web/` 27 個 tracked 檔；workflows 5 檔；docs Markdown 6 檔；README/web docs 3 檔；設定/依賴/devcontainer/gitignore/runtime 等 10+ 檔；另結構檢查 tracked labels/results/public data artifacts。大型 lockfile 以 manifest/version/integrity 結構解析，未逐行人工評論。
- 未執行 `next build`，因它必然寫 `.next/out/cache`，違反本次只允許新增報告的限制；CI 定義會跑 build（`.github/workflows/ci.yml:53-55`），遠端本次狀態 **待驗證**。
- 未執行 live crawler、GitHub Actions、Vercel deployment、Lighthouse、實體瀏覽器/螢幕閱讀器，亦未做需網路的 npm/pip 即時漏洞 audit；外部可用性、最新 CVE、GA/Api 實際部署設定均標為 **待驗證**。
- docs 內 6 張 PNG 僅盤點、未做逐像素視覺審查；UX 結論以實際 React/CSS/資料邏輯為主。
- 本機 ignored `web/.env.local` 未被 git 追蹤；tracked secret scan 未見硬編碼 API key。其 token 是否有效不屬 repo 靜態審查，**待驗證**。
