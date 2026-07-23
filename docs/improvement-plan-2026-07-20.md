# CVS Radar 體檢報告與改進計畫(2026-07-20)

盤點範圍:origin/main 完整管線(爬取 → 標註 → 計分 → 發佈)、本機 rebackfill
cron、GitHub Actions refresh-data。每項發現都附驗證方式;未驗證者標 UNVERIFIED。

---

## P0 — 現行故障(先修,別等改版)

### 0-1. 本機 rebackfill cron 已連續 4 天失敗
`~/.claude/logs/cvs-rebackfill.log`:07-16 16:30Z 起每天
`FAILED: 1 chunk(s) had non-zero Codex exit`,未標留言 16 → 36 → 68 持續累積,
healthcheck 每日發 Discord 警報中(stale 3.7d)。Codex auth 正常(`codex login
status` = Logged in),失因未知。

**連帶問題:失敗 log 自毀。** `cvs-rebackfill.sh` 第 60 行
`trap 'rm -rf "$WORK"' EXIT` 會在 die 時把 `$WORK/logs`(Codex chunk 輸出)
一起刪掉——錯誤訊息叫你「see $WORK/logs」,但那個目錄已經不存在了。

修法建議:
1. trap 改為:失敗時把 `$WORK/logs` 複製到
   `~/.claude/logs/rebackfill-failures/<date>/` 再刪 work dir。
2. 手動跑一次 `cvs-rebackfill.sh`(PUSH=0)看 chunk log 找失因
   (可疑方向:codex CLI 改版、inactivity-timeout 6 分鐘不夠、prompt 檔路徑)。
3. 修好後補跑,把積欠的 68+ 筆標掉。

### 0-2. cron 排程時區與設計意圖相反
設計意圖(memory 記載):UTC 00:30 = 台灣 08:30,排在 CI refresh(UTC 00:00
= 台灣 08:00)之後。實際:WSL 系統時區是 CST(台灣),crontab `30 0 * * *`
跑在**台灣 00:30** = UTC 16:30 前一天——比 CI 早 7.5 小時,順序整個顛倒。

後果:CI 早上 08:00 抓進的新留言,要等到隔天凌晨才有 LLM 標,整個白天
live 站上顯示的是 lexicon 分數(已知偏正)。

修法:crontab 改 `30 8 * * *`(台灣 08:30),一行搞定。改完後也才符合
「rebackfill 推 main → 觸發 refresh-data 重建」的即時上線設計。

---

## P1 — 計算面系統性偏差(增量資料每天重現)

### 1-1. 每日新留言只有 lexicon+tag prior,推文 tag 分數下限 +0.2
`tag_prior_weight=0.6` ⇒ score = 0.6×tag + 0.4×lexicon。實測
`score_comment('推','超難吃踩雷')` = **+0.2**——「推」tag 的留言無論文字多負
都不可能為負。炎上文的酸推(詐騙壽司案型)每天在新留言重現,rebackfill
正常時滯後數小時~一天,rebackfill 掛掉時(如現在)無限期錯下去。

選項(擇一或並行):
- a. 把 rebackfill 修穩(P0)並接受「當日 lexicon、隔日修正」的時滯 —— 現行
  設計,成本 0。
- b. 調降 `tag_prior_weight`(0.6 → 0.3?)讓文字能翻轉 tag;需用 gold_v1.csv
  對比校準後再動,不要裸調。
- c. CI 直接上 LLM(`CVS_RADAR_LLM_API_KEY` + gpt-4o-mini,DEV-9 已 wire 好
  未啟用)。你 07-13 曾婉拒 API key;若改變主意這是最乾淨解,每日增量
  幾十則,月費約數十元台幣等級。

### 1-2. 詞典無斷詞,子字串誤觸
實測:`這餅乾好吃` = 0.25(「乾」-0.5 誤觸)、`麻油雞好香` = 0.1
(「油」-0.4 誤觸)、`香草口味不錯` 的「香」+0.6 誤觸。影響所有無 LLM
標籤的留言。低成本修法:高誤觸單字(乾/油/香/鹹/濃/脆/嫩/雷)加排除
context(如 餅乾/麻油/奶油/香草/香蕉/香菇),或整包換 jieba 斷詞後再比對。

### 1-3. 業配偵測單字 keyword 是地雷
`SHILL_DETECTION.keywords` 含單字「業」「葉」:實測 專業/畢業/營業 全被判
喊業配。目前全庫 0 商品被 flag(25% 門檻擋住),尚無實害,但門檻碰巧救場
不是設計。修法:刪掉單字項,只留「業配」「葉配」,一行 config。

### 1-4. 時間衰減整個是關的
`time_decay_lambda: 0.0` ⇒ `_decay()` 恆回 1.0,一年前的心得與昨天等權。
超商商品多期間限定/改配方,舊評價權重過高會誤導。建議:先跑一次
開/關對比(λ=0.005/0.01/0.02 各算一輪,看分數位移分布與翻色帶比例,
照 07-17 指紋回補量化的方法),有感再拍板,不要裸上。

### 1-5. 共識分類區分度低:69% 商品是「褒貶不一」
現況 758 商品:褒貶不一 523、一致好評 96、資料不足 83、一致負評 43、
評價兩極 13。對使用者幾乎沒有資訊量。CONSENSUS 門檻(mean 0.4/0.7、
std 0.2/0.3)是拍腦袋值,可用現有分數分布重新校準(例如以分位數切,
讓四類各有合理占比),屬純展示層調整、不動 fair_score。

### 1-6. 品牌歸因規則覆蓋 LLM 標籤(權威順序矛盾)
套用順序:指紋 LLM 標籤 → 文字覆寫(最終權威)→ **計分時
`_comment_attribution` 再改一次**:(a) 提他牌但無比較詞 ⇒ 整則排除;
(b) 判定偏好本品牌時 `own_brand_positive_floor=0.4` 把分數強制拉到 ≥+0.4,
即使 LLM 判 -0.5 也被蓋掉。這與「LLM/人工標籤是權威」的設計精神矛盾。
建議:LLM 已標(backend=llm-backfill/codex)的留言跳過 attribution 的
分數改寫(排除邏輯可留),讓規則只兜底 lexicon 留言。

### 1-7. 已知資料髒點(既有票,列此存查)
- 跨商品 excerpt 污染(一文評多商品共用摘要)= DEV-85 類,未修。
- ~815/835 篇 product_name 髒值(不影響情感,影響分組與顯示)。
- 分類「其他」131 個(17%)、無價格 81 個。
- 建議打包成一次 LLM 批次清理(同指紋回補模式:export → Codex 判 →
  product_overrides.csv 收),比繼續加 regex 特例便宜。scoring.py 1920 行
  裡約六成是商品名 regex 特例,已到邊際效益遞減點,新髒值一律走
  override 表,別再加 regex。

---

## P2 — 更新流程與架構風險

### 2-1. raw store 有兩套真相,CI 那套只活在 cache 裡
- CI:`data/posts.jsonl` 只存 actions/cache(隱私設計,正確),但 GitHub
  cache 7 天未觸即蒸發;seed fallback 已移除(33c8d89),cache miss = 工作流
  誠實失敗,**沒有自動復原路徑**。連續假期 + workflow 壞掉一週 = CI 歷史
  全滅。
- 本機:855 篇(比 CI 多),在舊 repo 目錄 `cvs-radar/data/posts.jsonl`
  當 rebackfill 的 STORE_SEED,兩套各自演化。

建議:
1. 寫一份 recovery runbook(cache miss 時如何從本機 seed:手動塞 cache 或
   臨時 branch),放 docs/。
2. healthcheck 加一條:偵測 refresh-data workflow 連續失敗 ≥3 天就 Discord
   警報(gh api 查 run 狀態),別讓 cache 靜默走向蒸發。
3. 每週把本機 store 備份一份(本機即可,zip 到 Drive 或另一顆碟)。

### 2-2. 每天兩次全量 crawl 重複打 ptt.cc
CI 10 頁 + 本機 12 頁,同一批文章一天抓兩輪。可接受但非必要;若 0-2 的
時序修好(rebackfill 移到 CI 之後),rebackfill 可改吃 CI 剛產出的
results.json 反推、或減頁數(pages=3)只補 CI 之後的零星新文。低優先。

### 2-3. repo 每日膨脹
results.json 2.5MB + data.json 0.8MB 每日 commit,pack 現 13 MiB,估一年
+50~100MB。注意:**這些每日 commit 正是 DEV-23 趨勢洞察需要的快照**,
在 DEV-23 定案讀取方式前不要清理歷史。中期選項:DEV-23 改成每日把關鍵
欄位(product_key, fair_score, n_comments, date)append 到一個小 CSV,
之後 results.json 就可考慮移出版控。

### 2-4. 隱私殘留(既知,票未開)
ui/mobile-redesign 分支舊 commit 歷史仍含 raw PTT 帳號資料,徹底抹除需
git filter-repo 改寫公開歷史。風險低(需翻歷史才挖得到)但存在;建議開
一張票排期,改寫前先通知(會動公開 repo 歷史,屬不可逆操作)。

### 2-5. 本機三個 checkout 易混淆
舊 repo(Streamlit 分支)+ clean repo + rebackfill worktree
(`~/.cache/cvs-rebackfill-wt`,掛在舊 repo 下)。已踩過「在過期基底診斷」
的雷(07-17)。整併建議:rebackfill 的 REPO/STORE_SEED 改指 clean repo,
舊 repo 留純封存(或加 README 警語)。

---

## P3 — 改版計畫(對齊既有 roadmap,不另起爐灶)

| 順位 | 項目 | 內容 | 依賴 |
|---|---|---|---|
| 1 | DEV-107 GA4 | 事件埋點(search/product_expand/filter_apply/sort_change/outbound_ptt_click),env var 閘控 | 手動建 GA4 資源 + Vercel 設 NEXT_PUBLIC_GA_ID |
| 2 | 本文件 P0/P1 | 修 cron、修偏差 —— 屬「自動化」章的品質收尾,面試敘事可講「監控抓到故障 → 診斷 → 修復」完整一圈 | 無 |
| 3 | DEV-23 趨勢洞察 | git 歷史已累積 >1 個月每日快照,可提前 prototype:分數走勢、聲量週報 | 2-3 的快照讀取決策 |
| 4 | DEV-108 回報 MVP | 😋/😐/🤮 匿名回報,Upstash KV + rate limit | GA4 收兩週數據證明有流量 |
| 5 | 信任層 | suspicion model 套站內回報(取代已取消的 Dcard 第二來源) | DEV-108 |

前端小項(獨立於主線,可塞零碎時間):
- 「褒貶不一」佔比修正後,列表頁的 consensus 徽章才有意義(依賴 1-5)。
- 分數解釋性:展開卡加一行「分數依據:N 篇 N 則留言、最近 N 天」,
  likes/cautions 已有,補充信心脈絡即可,不新增資料欄位。

---

## 建議執行順序(一句話版)

1. 今天:修 rebackfill(log 保留 + 手動診斷 + crontab 改 `30 8`),補標積欠 68 筆。
2. 本週:1-3 業配單字(1 行)、1-2 詞典排除 context(小)、1-6 attribution 不蓋 LLM 標籤(中)。
3. 下週:1-4 衰減對比實驗 + 1-5 共識重校準(一次跑,量化後拍板)。
4. 並行:DEV-107 GA4(既定下一步,與上述互不阻塞)。
5. 排期:2-1 runbook + CI 失敗警報、1-7 LLM 批次清理、2-4 filter-repo 票。
