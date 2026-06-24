# Codex 任務：azz 多段留言合併（parser 層）

> Claude 拍板。Codex 執行，完成後 Claude 獨立驗證。**先單獨跑測試確認綠燈再 commit/push（勿串同條指令）。**

## 目標
PTT 同一帳號常把一則留言拆成**連續多行 push**。現況每行是獨立 Comment、各自算情感再被 per_user_cap 平均，導致「跨行才完整的句子」（否定詞/語氣在下一行）情感誤判。
改進：**在 parser 把「同帳號連續相鄰」的 push 合併成單一 Comment（文字串接）**，再進情感分析。

## 實作（`cvs_radar/parser.py` `_parse_comments`）
- 掃描 push 序列，**相鄰且同 `user`** 的合併為一個 Comment：
  - `text` = 各段文字依序串接（用單一空白或無分隔，擇一致；中文建議無分隔或空白）
  - `tag` = **第一段的 tag**（通常第一行才有明確 推/噓，續行多為 →）；若要更穩可取「該串中第一個非 → 的 tag，否則第一段 tag」
  - `user` = 同帳號；`posted_at` = 第一段時間
- **只合併相鄰**：同帳號但中間夾了別人留言的「非相鄰」兩則，**不可合併**（那是不同留言，仍交給 scoring 的 per_user_cap 處理）。
- 不改動 scoring 的 per_user_cap / exclude_self_push 行為。

## 測試（擴 tests）
- 同帳號連續 3 行 → 合併為 1 個 Comment、文字串接、tag=第一段、時間=第一段。
- 同帳號但**非相鄰**（A,B,A）→ 不合併（仍 2 個 A）。
- 不同帳號連續 → 不合併。
- 跨行句子情感：造一筆「line1=這個 / line2=真的很難吃」同帳號連續 → 合併後情感為負（驗證改善）。
- 既有 45 測試全過。

## 驗收（Claude 複驗）
- 上述測試為真且過；既有 45 測試不破。
- **重跑 gold_v1 評測**（`data/labels/gold_v1.csv`，lexicon backend）→ 極性準確率**不得低於改動前 94.1%**（理想持平或提升），把數字寫進 commit/報告。
- `CHANGELOG` 或 commit message 記錄行為改動。
- 先驗測試再 commit，push 回 GitHub。
