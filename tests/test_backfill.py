from __future__ import annotations

from cvs_radar.backfill import backfill_missing_reviews, is_backfill_candidate


ARTICLE_HTML = """
<div id="main-content">
  <div class="article-metaline"><span class="article-meta-tag">作者</span><span class="article-meta-value">tester (測試)</span></div>
  <div class="article-metaline"><span class="article-meta-tag">標題</span><span class="article-meta-value">[商品] 全家 可樂果香菜貢丸湯</span></div>
  <div class="article-metaline"><span class="article-meta-tag">時間</span><span class="article-meta-value">Wed Sep 17 19:50:28 2025</span></div>
  【商品名稱/價格】可樂果香菜貢丸湯 / 35
  【便利商店/廠商名稱】全家
  【評分】80
  主要是白胡椒味加芹菜，很像貢丸湯，但香菜味不明顯。
</div>
"""


def row(**overrides: object) -> dict:
    value = {
        "id": "M.test",
        "source": "PTT",
        "board": "CVS",
        "url": "https://www.ptt.cc/bbs/CVS/M.test.html",
        "title": "[商品] 全家 可樂果香菜貢丸湯",
        "review_text": "",
        "is_reply": False,
        "comments": [],
    }
    value.update(overrides)
    return value


def test_backfills_missing_review_without_mutating_input() -> None:
    original = row()

    updated_rows, attempted, updated = backfill_missing_reviews([original], lambda _url: ARTICLE_HTML)

    assert attempted == 1
    assert updated == 1
    assert "很像貢丸湯" in updated_rows[0]["review_text"]
    assert original["review_text"] == ""


def test_skips_replies_existing_reviews_and_offsite_urls() -> None:
    rows = [
        row(id="reply", title="Re: [商品] 7-11 切達起司貝果", is_reply=True),
        row(id="done", review_text="已有心得"),
        row(id="offsite", url="https://example.com/article"),
    ]

    updated_rows, attempted, updated = backfill_missing_reviews(
        rows,
        lambda _url: ARTICLE_HTML,
    )

    assert attempted == 0
    assert updated == 0
    assert updated_rows == rows
    assert not is_backfill_candidate(rows[0])


def test_fetch_failure_keeps_original_row() -> None:
    def fail(_url: str) -> str:
        raise RuntimeError("temporary failure")

    original = row()
    updated_rows, attempted, updated = backfill_missing_reviews([original], fail)

    assert attempted == 1
    assert updated == 0
    assert updated_rows == [original]
