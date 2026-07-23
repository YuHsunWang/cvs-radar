from __future__ import annotations

from datetime import datetime, timezone

import pytest

from cvs_radar.backfill import (
    backfill_missing_reviews,
    is_backfill_candidate,
    is_recent_refresh_candidate,
    refresh_recent_posts,
)


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



def recent_article_html() -> str:
    html = ARTICLE_HTML.replace(
        "Wed Sep 17 19:50:28 2025",
        "Fri Jul 10 19:50:28 2026",
    )
    before_close, close = html.rsplit("</div>", 1)
    push = (
        '<div class="push"><span class="push-tag">推 </span>'
        '<span class="push-userid">new_reader</span>'
        '<span class="push-content">: 後來補充，搭咖啡很好吃</span>'
        '<span class="push-ipdatetime">07/15 12:01</span></div>'
    )
    return before_close + push + "</div>" + close


def test_refresh_recent_post_replaces_comment_snapshot_without_mutating_input() -> None:
    original = row(
        posted_at="2026-07-10T19:50:28+08:00",
        push_count=7,
        comments=[{"tag": "→", "user": "old_reader", "text": "舊留言"}],
    )

    updated_rows, attempted, updated = refresh_recent_posts(
        [original],
        lambda _url: recent_article_html(),
        recent_days=30,
        now=datetime(2026, 7, 16, tzinfo=timezone.utc),
    )

    assert attempted == 1
    assert updated == 1
    assert original["comments"][0]["user"] == "old_reader"
    assert [comment["user"] for comment in updated_rows[0]["comments"]] == ["new_reader"]
    assert updated_rows[0]["comments"][0]["text"] == "後來補充，搭咖啡很好吃"
    assert updated_rows[0]["push_count"] == 7


def test_recent_refresh_candidate_respects_age_and_ptt_cvs_url() -> None:
    now = datetime(2026, 7, 16, tzinfo=timezone.utc)

    assert is_recent_refresh_candidate(
        row(posted_at="2026-07-10T00:00:00+08:00"),
        recent_days=30,
        now=now,
    )
    assert not is_recent_refresh_candidate(
        row(posted_at="2026-06-01T00:00:00+08:00"),
        recent_days=30,
        now=now,
    )
    assert not is_recent_refresh_candidate(
        row(posted_at="2026-07-10T00:00:00+08:00", url="https://example.com/article"),
        recent_days=30,
        now=now,
    )
    with pytest.raises(ValueError, match="invalid date/datetime"):
        is_recent_refresh_candidate(
            row(posted_at="not-a-date"),
            recent_days=30,
            now=now,
        )


def test_recent_refresh_interprets_naive_timestamp_as_taipei() -> None:
    assert not is_recent_refresh_candidate(
        row(posted_at="2026-07-15T01:00:00"),
        recent_days=1,
        now=datetime(2026, 7, 16, tzinfo=timezone.utc),
    )


def test_recent_refresh_failure_keeps_previous_comments() -> None:
    original = row(
        posted_at="2026-07-10T00:00:00+08:00",
        comments=[{"tag": "推", "user": "reader", "text": "保留我"}],
    )

    def fail(_url: str) -> str:
        raise RuntimeError("temporary failure")

    updated_rows, attempted, updated = refresh_recent_posts(
        [original],
        fail,
        recent_days=30,
        now=datetime(2026, 7, 16, tzinfo=timezone.utc),
    )

    assert attempted == 1
    assert updated == 0
    assert updated_rows == [original]
