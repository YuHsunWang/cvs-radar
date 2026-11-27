from pathlib import Path

import pytest

import web.build_data as build_data
from cvs_radar.youtube_reviews import REVIEW_FIELDS, load_reviews, review_errors


def row(**overrides: str) -> dict[str, str]:
    base = {
        "video_id": "lLgH8aKjHys", "channel": "那個女生 Kiki", "video_date": "2026-10-16",
        "start_seconds": "812", "brand": "全家", "product_name": "冰心可可脆絲蛋糕", "product_id": "",
        "category": "甜點", "price": "49", "creator_score": "9/10", "summary": "巧克力味滿滿，脆絲加分、不會太甜",
    }
    return {**base, **overrides}


def ptt_product(product_id: str) -> dict:
    product = build_data.youtube_only_product(product_id, [row()])
    product.update(nPosts=2, consensus="一致好評", fairScore=70, recommendationScore=78)
    return product


def publishable(products: list[dict]) -> dict:
    for product in products:
        product.update(kcal=None, nutrition=None, image=None, vegetarian=None)
    return {"generatedAt": "2026-11-23T00:00:00+00:00", "siteBuiltAt": "2026-11-23T00:00:00+00:00", "products": products}


def test_a_product_only_youtube_covers_is_published_without_any_score() -> None:
    products = build_data.attach_youtube_reviews([ptt_product("全家::別的商品")], [row()])
    only = next(p for p in products if p["id"] == "全家::冰心可可脆絲蛋糕")
    # The creator's 9/10 is their words, shown beside their name; it must never
    # become the site's own score, which only PTT evidence may produce.
    assert only["recommendationScore"] is None and only["fairScore"] is None
    assert only["positivePct"] is None and only["nPosts"] == 0
    assert only["youtube"] == [{
        "channel": "那個女生 Kiki", "summary": "巧克力味滿滿，脆絲加分、不會太甜", "score": "9/10",
        "url": "https://www.youtube.com/watch?v=lLgH8aKjHys&t=812s", "date": "2026-10-16",
    }]
    build_data.validate_payload(publishable(products))


def test_reviews_join_the_ptt_product_they_match_instead_of_duplicating_it() -> None:
    ptt = ptt_product("全家::熊本麥味噌雞肉飯糰")
    rows = [
        # Matched by id although the transcript spelled the name differently.
        row(product_name="熊本賣味噌雞肉飯團", product_id="全家::熊本麥味噌雞肉飯糰"),
        # Same name as the PTT product, no id: still the same product.
        row(video_id="t2xVd60iicM", channel="厭世甜點店", video_date="2026-10-18", product_name="熊本麥味噌雞肉飯糰"),
    ]
    products = build_data.attach_youtube_reviews([ptt], rows)
    assert len(products) == 1
    assert [review["channel"] for review in products[0]["youtube"]] == ["厭世甜點店", "那個女生 Kiki"]  # newest first
    assert products[0]["recommendationScore"] == 78


def test_two_videos_on_one_new_product_make_one_card() -> None:
    rows = [row(), row(video_id="t2xVd60iicM", channel="厭世甜點店", video_date="2026-10-18", product_id="全家::冰心可可脆絲蛋糕", product_name="冰心可可脆絲")]
    products = build_data.attach_youtube_reviews([], rows)
    assert len(products) == 1 and len(products[0]["youtube"]) == 2
    assert products[0]["latestDate"] == "2026-10-18"


def test_names_differing_only_in_case_keep_every_review_on_one_card() -> None:
    # Each channel spells the brand its own way; dropping one creator's review
    # would silently misreport what YouTubers said.
    rows = [row(product_name="Homeal咖哩飯"), row(video_id="t2xVd60iicM", video_date="2026-10-18", product_name="HOMEAL咖哩飯")]
    products = build_data.attach_youtube_reviews([], rows)
    assert len(products) == 1 and len(products[0]["youtube"]) == 2
    assert products[0]["latestDate"] == "2026-10-18"


def test_a_youtube_only_product_obeys_product_overrides() -> None:
    # product_overrides.csv is the documented way to fix a wrong category or hide
    # a product; it must reach YouTube-only cards too, or the filters stay wrong.
    overrides = {"全家::冰心可可脆絲蛋糕": {"category": "冰品"}, "全家::別的": {"exclude": "1"}}
    products = build_data.attach_youtube_reviews([], [row(), row(product_name="別的")], overrides)
    assert [(p["id"], p["category"]) for p in products] == [("全家::冰心可可脆絲蛋糕", "冰品")]


def test_an_override_merge_keeps_the_newest_video_date() -> None:
    # The date filter reads latestDate; an older date would hide a card whose
    # newest review falls inside the chosen range.
    overrides = {"全家::舊名": {"productName": "冰心可可脆絲蛋糕"}}
    rows = [row(), row(video_id="t2xVd60iicM", video_date="2026-11-18", product_name="舊名")]
    products = build_data.attach_youtube_reviews([], rows, overrides)
    assert len(products) == 1 and len(products[0]["youtube"]) == 2
    assert products[0]["latestDate"] == "2026-11-18"


@pytest.mark.parametrize(
    ("overrides", "problem"),
    [
        ({"brand": "家樂福"}, "brand"),
        ({"summary": "好" * 41}, "summary"),
        ({"summary": "看 https://x.y"}, "URL"),
        ({"creator_score": "很高"}, "creator_score"),
        ({"category": "宵夜"}, "category"),
        ({"start_seconds": "5000"}, "past the end"),
    ],
)
def test_rows_that_would_misquote_or_mislink_are_rejected(overrides: dict, problem: str) -> None:
    assert any(problem in error for error in review_errors(row(**overrides), duration_seconds=1064))


def test_a_malformed_committed_row_stops_the_build(tmp_path: Path) -> None:
    path = tmp_path / "youtube_reviews.csv"
    bad = row(brand="家樂福")
    path.write_text(",".join(REVIEW_FIELDS) + "\n" + ",".join(bad[key] for key in REVIEW_FIELDS) + "\n", encoding="utf-8-sig")
    with pytest.raises(ValueError, match="brand"):
        load_reviews(path)
    assert load_reviews(tmp_path / "missing.csv") == []


def vtt(cues: list[tuple[int, str]]) -> str:
    blocks = [f"00:{s // 60:02d}:{s % 60:02d}.000 --> 00:{s // 60:02d}:{s % 60:02d}.900\n{text}" for s, text in cues]
    return "WEBVTT\nKind: captions\nLanguage: zh-TW\n\n" + "\n\n".join(blocks) + "\n"


def test_captions_become_whisper_style_lines_without_tags_or_repeats() -> None:
    from scripts.youtube_reviews import vtt_lines

    text = vtt([(5, "各位觀眾<c> 大家好</c>"), (6, "各位觀眾 大家好"), (75, "這個肉鬆麵包\n我給八分")])
    assert vtt_lines(text) == ["0:05 各位觀眾 大家好", "1:15 這個肉鬆麵包 我給八分"]


def test_prices_on_their_own_caption_line_survive_but_cue_ids_do_not() -> None:
    """Extraction reads prices and scores from the transcript; a bare `49` line is one of them."""
    from scripts.youtube_reviews import vtt_lines

    text = "WEBVTT\n\n7\n00:00:05.000 --> 00:00:06.000\n這個售價\n49\n\n8\n00:00:07.000 --> 00:00:08.000\n8\n"
    assert vtt_lines(text) == ["0:05 這個售價 49", "0:07 8"]


def test_a_stalled_caption_download_falls_back_to_whisper(monkeypatch: pytest.MonkeyPatch) -> None:
    """A timeout must not mark the video failed; the audio path should still run."""
    import subprocess

    import scripts.youtube_reviews as yt

    def stall(cmd: list[str], **_kwargs):
        raise subprocess.TimeoutExpired(cmd, 600)

    monkeypatch.setattr(yt.subprocess, "run", stall)
    assert yt.captions({"video_id": "x", "duration": 600}) is None


@pytest.mark.parametrize(
    ("lines", "problem"),
    [
        ([f"{i // 60}:{i % 60:02d} 這個很好吃" for i in range(0, 600, 30)][:10], "only 10 lines"),
        ([f"{i // 60}:{i % 60:02d} this one is really tasty" for i in range(0, 600, 20)], "Chinese"),
        ([f"{i // 60}:{i % 60:02d} 這個很好吃" for i in range(0, 200, 5)], "stop at"),
    ],
)
def test_captions_that_cannot_replace_a_transcript_are_rejected(lines: list[str], problem: str) -> None:
    from scripts.youtube_reviews import caption_problem

    assert problem in (caption_problem(lines, duration=600) or "")


def test_full_chinese_captions_are_accepted() -> None:
    from scripts.youtube_reviews import caption_problem

    assert caption_problem([f"{i // 60}:{i % 60:02d} 這個很好吃 7-11 $45" for i in range(0, 600, 20)], duration=600) is None


def test_english_or_missing_captions_fall_back_to_whisper(monkeypatch: pytest.MonkeyPatch) -> None:
    """A wrong-language track must never reach Codex as the transcript."""
    import subprocess

    import scripts.youtube_reviews as yt

    def fake_run(cmd: list[str], **_kwargs):
        out = Path(cmd[cmd.index("-o") + 1])
        (out.parent / "sub.zh-TW.vtt").write_text(vtt([(s, "this one is tasty") for s in range(0, 600, 20)]), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(yt.subprocess, "run", fake_run)
    assert yt.captions({"video_id": "x", "duration": 600}) is None

    monkeypatch.setattr(yt.subprocess, "run", lambda cmd, **_: subprocess.CompletedProcess(cmd, 0, "", ""))
    assert yt.captions({"video_id": "x", "duration": 600}) is None
