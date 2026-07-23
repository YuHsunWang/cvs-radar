# CONTEXT.md — CVS Radar 領域詞彙

> 給 agent 與協作者的共同語言。名詞的**規範定義**以指向的文件為準,
> 本檔只是查找表;規則與流程見 CLAUDE.md / AGENTS.md,此處不重述。

## 產品概念

- **推薦分**:商品層級的綜合評價分數。低樣本商品**不顯示**推薦分
  (防過度解讀的門檻邏輯)。計分決策記錄在 docs/DECISIONS.md。
- **共識**:評價分布的一致程度,與推薦分並列顯示。
- **聲量**:商品被討論的量(文章+推文數)。
- **作者評價 vs 留言評價**:兩條獨立的訊號來源——發文作者的心得評價,
  與推文/留言的情緒;展開卡片時依序呈現,不混算。
- **意圖分類**:使用者查詢的分類(正餐/甜點/冰品/飲料/麵包/零食)。
- **品牌 chips**:UI 上可交叉篩選的品牌標籤。
- **通路**:7-11、全家、萊爾富、OK、美聯社及其他。
- **公開快照**:去識別化的靜態資料(目前 772 項商品),公開網站只用
  這份,不含帳號層級分析。

## 資料與標註

- **PTT CVS 板**:唯一的原始資料來源。
- **反諷/離題回覆**:情緒判讀的兩大干擾源,標註規範處理。
- **標註規範**:docs/labeling_guideline.md,標註的規範定義。
- **luna 標註 loop**:半自動標註流程(人工覆核 + 模型預標)。
- **NFKC 正規化**:搜尋層的字元正規化(全形/半形統一)。

## 不變量(違反 = bug)

- **隱私不變量**:profiles 保持空、raw 資料不進 repo、公開資料
  一律去識別化。
- **低樣本 gating**:樣本數不足的商品不顯示推薦分與百分比分布。

## Repo 拓撲

- 兩個 local repo 共用同一 remote:`cvs-radar-clean`(main,
  Next.js 15 + TS,Vercel 部署)與 `cvs-radar`(ui/mobile-redesign,
  Streamlit 舊版)。
- Python 3.12 管線(crawl_job.py 每日抓取)+ 靜態輸出給前端。
- Issue tracker:Linear(DEV-xx)。

## 規範文件指標

- 評分決策:docs/DECISIONS.md
- 標註規範:docs/labeling_guideline.md
- 產品需求:CVS-Radar-PRD-v0.2.md
