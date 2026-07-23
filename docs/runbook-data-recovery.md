# Runbook:raw 資料(posts.jsonl)遺失復原

> 排程/發布/新鮮度監控見 [`ops-pipeline.md`](./ops-pipeline.md)。發布者自
> 2026-07-21 起為本機 cron pipeline(`scripts/ops/`),`refresh-data.yml` 僅
> 手動備援;本頁下方部分 CI-cache 流程屬舊架構,復原步驟仍適用。

## 背景:raw 資料存放架構

`data/posts.jsonl`(含真實 PTT 帳號的爬取歷史)**絕不進 repo**(repo 是
public)。它有兩份副本:

| 副本 | 位置 | 風險 |
|---|---|---|
| CI 用 | GitHub Actions cache(key 前綴 `cvs-posts-`) | **7 天未被任何 run 觸碰即被 GitHub 清除**;無自動復原 |
| 本機 | WSL `~/github-work/YuHsunWang/cvs-radar-clean/data/posts.jsonl` | 每週日由 `cvs-backup.sh` 壓縮快照到 `D:\Claude\backups\cvs-radar\`(留 8 份) |

正常情況下每日 refresh-data run 會還原→附加→重存 cache,cache 常保新鮮。
cache 蒸發的前置事件通常是 **refresh-data 連續失敗多天**——本機
`cvs-ci-healthcheck.py`(cron 每日)會在最後成功 run 超過 2 天時發 Discord
警報,收到警報先修 workflow,通常趕在 7 天大限前 cache 還在。

## 判斷 cache 是否還在

```
gh cache list -R YuHsunWang/cvs-radar --key cvs-posts-
```

- 有列出且日期近:cache 還在,修好 workflow 重跑即可,不需 seed。
- 空的:cache 已蒸發,走下面的復原流程。

## 復原流程(cache 已蒸發)

1. 確認本機 store 健康(行數應接近遺失前的量;不足就先解壓
   `D:\Claude\backups\cvs-radar\posts-*.jsonl.gz` 最新一份):

   ```
   wc -l ~/github-work/YuHsunWang/cvs-radar-clean/data/posts.jsonl
   ```

2. 把 posts.jsonl 放到一個**可直接 GET 的暫時連結**(擇一):
   - Google Drive:上傳後開「知道連結者可檢視」,直鏈格式
     `https://drive.google.com/uc?export=download&id=<FILE_ID>`
   - 或任何一次性檔案服務(0x0.st、transfer.sh 類)。
   檔案含 PTT 帳號,連結屬半公開——用完立刻撤銷/刪除。

3. 觸發 seed workflow(驗證 JSONL 格式與最低篇數後存進 cache):

   ```
   gh workflow run seed-cache.yml -R YuHsunWang/cvs-radar -f seed_url="<URL>"
   gh run watch -R YuHsunWang/cvs-radar   # 等它綠
   ```

4. 立刻**撤銷第 2 步的分享連結**。

5. 驗證:手動跑一次每日管線,確認商品數沒有塌回單一爬取視窗(~數十):

   ```
   gh workflow run refresh-data.yml -R YuHsunWang/cvs-radar
   ```

   run 綠且 commit 訊息的商品數正常(700+)即復原完成。

## 相關警報與排程(本機 WSL)

| 元件 | 排程 | 說明 |
|---|---|---|
| `cvs-ci-healthcheck.py` | cron 每日 | refresh-data 最後成功 run > 2 天 → Discord |
| `cvs-rebackfill-healthcheck.py` | cron 每小時 | 本機 LLM 回補 > 3 天未成功 → Discord |
| `cvs-backup.sh` | cron 每週日 | store+labels 快照到 D:,留 8 份 |
