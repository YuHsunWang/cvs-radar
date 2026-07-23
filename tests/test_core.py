from __future__ import annotations

import json
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zoneinfo import ZoneInfo

from cvs_radar import store
from cvs_radar.crawler import PttCrawler
from cvs_radar.models import Comment, Post, ProductReport
from cvs_radar.parser import (
    infer_brand,
    is_product_title,
    parse_ptt_article,
    parse_ptt_datetime,
    parse_ptt_list,
    parse_push_count,
    parse_push_datetime,
    parse_score,
)
from cvs_radar.pipeline import run_pipeline
from cvs_radar.reporting import hash_user, render_json, render_suspicion, render_text, report_to_dict
from cvs_radar.scoring import (
    _review_excerpt,
    _review_sentences,
    _same_combo_flavor_product,
    _same_product,
    canonical_product_name,
    categorize_product,
    extract_products_and_prices,
    group_products,
    normalize_product,
    preprocess_posts,
    representative_product_name,
    score_all,
    score_product,
)
from cvs_radar.sentiment import (
    LlmBackend,
    annotate_posts,
    apply_sentiment_overrides,
    clamp,
    llm_has_key,
    resolve_backend,
    score_comment,
    tag_prior,
)


class ParserTest(unittest.TestCase):
    def test_public_parser_helpers_for_titles_brands_counts_and_lists(self) -> None:
        html = """
        <div class="r-ent">
          <div class="nrec">爆</div>
          <div class="title"><a href="/bbs/CVS/M.1.html">[商品] 711 測試飯糰</a></div>
          <div class="author">tester</div>
          <div class="date">6/01</div>
        </div>
        <div class="r-ent">
          <div class="title"><a href="/bbs/CVS/M.2.html">[閒聊] ignored</a></div>
        </div>
        <a class="btn wide" href="/bbs/CVS/index123.html">上頁</a>
        """

        rows, prev_url = parse_ptt_list(html, base_url="https://www.ptt.cc")

        self.assertTrue(is_product_title("［商品］全家 測試甜點"))
        self.assertFalse(is_product_title("[閒聊] 測試"))
        self.assertEqual(infer_brand("family mart 測試"), "全家")
        self.assertEqual(parse_push_count("爆"), 100)
        self.assertEqual(parse_push_count("X2"), -2)
        self.assertEqual(rows, [
            {
                "title": "[商品] 711 測試飯糰",
                "url": "https://www.ptt.cc/bbs/CVS/M.1.html",
                "author": "tester",
                "date": "6/01",
                "push_count": "爆",
            }
        ])
        self.assertEqual(prev_url, "https://www.ptt.cc/bbs/CVS/index123.html")
        self.assertEqual(
            parse_ptt_datetime("Mon Jun  1 12:00:00 2026"),
            datetime(2026, 6, 1, 12, 0, tzinfo=ZoneInfo("Asia/Taipei")),
        )
        self.assertIsNone(parse_ptt_datetime("not a date"))

    def test_brand_aliases_respect_ascii_boundaries(self) -> None:
        for text in ("cookie", "okay", "smoky", "WACOOKIES"):
            with self.subTest(text=text):
                self.assertEqual(infer_brand(text), "其他")

        for text in ("OK", "OKmart", "OK超商", "OK便利商店"):
            with self.subTest(text=text):
                self.assertEqual(infer_brand(text), "OK")

    def test_parse_score_edge_cases(self) -> None:
        self.assertEqual(parse_score("85"), 85)
        self.assertEqual(parse_score("8/10"), 80)
        self.assertEqual(parse_score("★★★★"), 80)
        self.assertIsNone(parse_score("無"))

    def test_parse_ptt_article_fields_and_pushes(self) -> None:
        html = """
        <div id="main-content">
          <div class="article-metaline"><span class="article-meta-tag">作者</span><span class="article-meta-value">tester (測試)</span></div>
          <div class="article-metaline"><span class="article-meta-tag">標題</span><span class="article-meta-value">[商品] 711 測試飯糰</span></div>
          <div class="article-metaline"><span class="article-meta-tag">時間</span><span class="article-meta-value">Mon Jun  1 12:00:00 2026</span></div>
          【商品名稱/價格】測試飯糰 / 39
          【便利商店/廠商名稱】7-11
          【評分】8/10
          【心得】好吃會回購
          <div class="push"><span class="push-tag">推 </span><span class="push-userid">alice</span><span class="push-content">: 好吃</span><span class="push-ipdatetime">06/01 12:01</span></div>
        </div>
        """
        post = parse_ptt_article(html, "https://www.ptt.cc/bbs/CVS/M.1.html")
        assert post is not None
        self.assertEqual(post.author, "tester")
        self.assertEqual(post.brand, "7-11")
        self.assertEqual(post.author_score, 80)
        self.assertEqual(len(post.comments), 1)

    def test_parse_ptt_article_recovers_unlabeled_review_after_score(self) -> None:
        html = """
        <div id="main-content">
          <div class="article-metaline"><span class="article-meta-tag">作者</span><span class="article-meta-value">tester (測試)</span></div>
          <div class="article-metaline"><span class="article-meta-tag">標題</span><span class="article-meta-value">[商品] 全家 測試商品</span></div>
          <div class="article-metaline"><span class="article-meta-tag">時間</span><span class="article-meta-value">Mon Jun  1 12:00:00 2026</span></div>
          【商品名稱/價格】測試商品 / 35
          【便利商店/廠商名稱】全家
          【評分】80
          主要是白胡椒味加芹菜，很像貢丸湯，但香菜味不明顯。
          不吃香菜的人應該也可以接受。
        </div>
        """

        post = parse_ptt_article(html, "https://www.ptt.cc/bbs/CVS/M.unlabeled.html")

        assert post is not None
        self.assertEqual(post.author_score, 80)
        self.assertIn("很像貢丸湯", post.review_text)
        self.assertIn("不吃香菜的人應該也可以接受", post.review_text)
        self.assertNotIn("80", post.review_text)

    def test_reply_does_not_treat_quoted_score_tail_as_new_review(self) -> None:
        html = """
        <div id="main-content">
          <div class="article-metaline"><span class="article-meta-tag">作者</span><span class="article-meta-value">tester (測試)</span></div>
          <div class="article-metaline"><span class="article-meta-tag">標題</span><span class="article-meta-value">Re: [商品] 7-11 切達起司貝果</span></div>
          <div class="article-metaline"><span class="article-meta-tag">時間</span><span class="article-meta-value">Mon Jun  1 12:00:00 2026</span></div>
          【商品名稱/價格】切達起司貝果 / 28
          【便利商店/廠商名稱】7-11
          【評分】60
          引用舊文中的心得，不是本篇新增內容。
        </div>
        """

        post = parse_ptt_article(html, "https://www.ptt.cc/bbs/CVS/M.reply.html")

        assert post is not None
        self.assertTrue(post.is_reply)
        self.assertEqual(post.review_text, "")

    def test_parse_comments_merges_adjacent_same_user_three_line_run(self) -> None:
        html = """
        <div id="main-content">
          <div class="article-metaline"><span class="article-meta-tag">作者</span><span class="article-meta-value">tester (測試)</span></div>
          <div class="article-metaline"><span class="article-meta-tag">標題</span><span class="article-meta-value">[商品] 711 測試飯糰</span></div>
          <div class="article-metaline"><span class="article-meta-tag">時間</span><span class="article-meta-value">Mon Jun  1 12:00:00 2026</span></div>
          【商品名稱】測試飯糰
          <div class="push"><span class="push-tag">推 </span><span class="push-userid">alice</span><span class="push-content">: 第一段</span><span class="push-ipdatetime">06/01 12:01</span></div>
          <div class="push"><span class="push-tag">→ </span><span class="push-userid">alice</span><span class="push-content">: 第二段</span><span class="push-ipdatetime">06/01 12:02</span></div>
          <div class="push"><span class="push-tag">→ </span><span class="push-userid">alice</span><span class="push-content">: 第三段</span><span class="push-ipdatetime">06/01 12:03</span></div>
        </div>
        """

        post = parse_ptt_article(html, "https://www.ptt.cc/bbs/CVS/M.merge.html")

        assert post is not None
        self.assertEqual(len(post.comments), 1)
        comment = post.comments[0]
        self.assertEqual(comment.user, "alice")
        self.assertEqual(comment.tag, "推")
        self.assertEqual(comment.text, "第一段第二段第三段")
        self.assertEqual(comment.posted_at.isoformat(), "2026-06-01T12:01:00+08:00")

    def test_parse_comments_keeps_non_adjacent_same_user_separate(self) -> None:
        html = """
        <div id="main-content">
          <div class="article-metaline"><span class="article-meta-tag">作者</span><span class="article-meta-value">tester (測試)</span></div>
          <div class="article-metaline"><span class="article-meta-tag">標題</span><span class="article-meta-value">[商品] 711 測試飯糰</span></div>
          <div class="article-metaline"><span class="article-meta-tag">時間</span><span class="article-meta-value">Mon Jun  1 12:00:00 2026</span></div>
          【商品名稱】測試飯糰
          <div class="push"><span class="push-tag">推 </span><span class="push-userid">alice</span><span class="push-content">: A1</span><span class="push-ipdatetime">06/01 12:01</span></div>
          <div class="push"><span class="push-tag">推 </span><span class="push-userid">bob</span><span class="push-content">: B</span><span class="push-ipdatetime">06/01 12:02</span></div>
          <div class="push"><span class="push-tag">推 </span><span class="push-userid">alice</span><span class="push-content">: A2</span><span class="push-ipdatetime">06/01 12:03</span></div>
        </div>
        """

        post = parse_ptt_article(html, "https://www.ptt.cc/bbs/CVS/M.nonadjacent.html")

        assert post is not None
        self.assertEqual([comment.user for comment in post.comments], ["alice", "bob", "alice"])
        self.assertEqual([comment.text for comment in post.comments], ["A1", "B", "A2"])

    def test_parse_comments_keeps_adjacent_different_users_separate(self) -> None:
        html = """
        <div id="main-content">
          <div class="article-metaline"><span class="article-meta-tag">作者</span><span class="article-meta-value">tester (測試)</span></div>
          <div class="article-metaline"><span class="article-meta-tag">標題</span><span class="article-meta-value">[商品] 711 測試飯糰</span></div>
          <div class="article-metaline"><span class="article-meta-tag">時間</span><span class="article-meta-value">Mon Jun  1 12:00:00 2026</span></div>
          【商品名稱】測試飯糰
          <div class="push"><span class="push-tag">推 </span><span class="push-userid">alice</span><span class="push-content">: 好吃</span><span class="push-ipdatetime">06/01 12:01</span></div>
          <div class="push"><span class="push-tag">噓 </span><span class="push-userid">bob</span><span class="push-content">: 難吃</span><span class="push-ipdatetime">06/01 12:02</span></div>
        </div>
        """

        post = parse_ptt_article(html, "https://www.ptt.cc/bbs/CVS/M.diffusers.html")

        assert post is not None
        self.assertEqual([(comment.user, comment.text) for comment in post.comments], [("alice", "好吃"), ("bob", "難吃")])

    def test_parse_comments_cross_line_sentence_scores_negative_after_merge(self) -> None:
        html = """
        <div id="main-content">
          <div class="article-metaline"><span class="article-meta-tag">作者</span><span class="article-meta-value">tester (測試)</span></div>
          <div class="article-metaline"><span class="article-meta-tag">標題</span><span class="article-meta-value">[商品] 711 測試飯糰</span></div>
          <div class="article-metaline"><span class="article-meta-tag">時間</span><span class="article-meta-value">Mon Jun  1 12:00:00 2026</span></div>
          【商品名稱】測試飯糰
          <div class="push"><span class="push-tag">→ </span><span class="push-userid">alice</span><span class="push-content">: 這個</span><span class="push-ipdatetime">06/01 12:01</span></div>
          <div class="push"><span class="push-tag">→ </span><span class="push-userid">alice</span><span class="push-content">: 真的很難吃</span><span class="push-ipdatetime">06/01 12:02</span></div>
        </div>
        """

        post = parse_ptt_article(html, "https://www.ptt.cc/bbs/CVS/M.negative.html")

        assert post is not None
        self.assertEqual(len(post.comments), 1)
        self.assertEqual(post.comments[0].text, "這個真的很難吃")
        self.assertLess(score_comment(post.comments[0].tag, post.comments[0].text, backend="lexicon"), -0.2)

    def test_parse_push_datetime_uses_article_year_and_rollover(self) -> None:
        from datetime import datetime

        same_year = parse_push_datetime("05/02 12:30", reference=datetime(2025, 5, 1, 10, 0))
        rollover = parse_push_datetime("01/01 00:05", reference=datetime(2025, 12, 31, 23, 50))
        previous_year = parse_push_datetime("12/31 23:55", reference=datetime(2026, 1, 1, 0, 5))

        taipei = ZoneInfo("Asia/Taipei")
        self.assertEqual(same_year, datetime(2025, 5, 2, 12, 30, tzinfo=taipei))
        self.assertEqual(rollover, datetime(2026, 1, 1, 0, 5, tzinfo=taipei))
        self.assertEqual(previous_year, datetime(2025, 12, 31, 23, 55, tzinfo=taipei))

    def test_parse_push_datetime_accepts_leap_day_with_reference_year(self) -> None:
        from datetime import datetime

        parsed = parse_push_datetime("02/29 08:15", reference=datetime(2024, 2, 29, 8, 0))

        self.assertEqual(parsed, datetime(2024, 2, 29, 8, 15, tzinfo=ZoneInfo("Asia/Taipei")))


class CrawlerSeenCacheTest(unittest.TestCase):
    def _crawl_one(self, parsed_post: Post | None) -> tuple[str, PttCrawler, list[str], list[Post]]:
        article_url = "https://example.test/bbs/CVS/M.1.html"
        with TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / ".cvs_radar_seen.json"
            crawler = PttCrawler(
                base_url="https://example.test",
                request_delay_sec=0,
                timeout_sec=0.1,
                retries=0,
                cache_path=cache_path,
            )
            crawler._get = lambda url: "article-html" if url == article_url else "list-html"  # type: ignore[method-assign]
            with (
                patch("cvs_radar.crawler.parse_ptt_list", return_value=([{"url": article_url, "push_count": "1"}], None)),
                patch("cvs_radar.crawler.parse_ptt_article", return_value=parsed_post),
            ):
                posts = crawler.crawl(max_pages=1, start_date="2026-06-10", end_date="2026-06-10")
            cached_urls = json.loads(cache_path.read_text(encoding="utf-8"))
        return article_url, crawler, cached_urls, posts

    def test_crawl_does_not_mark_out_of_window_post_seen(self) -> None:
        post = Post(id="old", url="https://example.test/bbs/CVS/M.1.html", posted_at=datetime(2026, 6, 1, 12, 0))

        article_url, crawler, cached_urls, posts = self._crawl_one(post)

        self.assertEqual(posts, [])
        self.assertNotIn(article_url, crawler.seen_urls)
        self.assertNotIn(article_url, cached_urls)

    def test_crawl_marks_non_product_post_seen(self) -> None:
        article_url, crawler, cached_urls, posts = self._crawl_one(None)

        self.assertEqual(posts, [])
        self.assertIn(article_url, crawler.seen_urls)
        self.assertIn(article_url, cached_urls)

    def test_crawl_skips_off_site_article_urls(self) -> None:
        with TemporaryDirectory() as tmpdir:
            crawler = PttCrawler(
                base_url="https://example.test",
                request_delay_sec=0,
                timeout_sec=0.1,
                retries=0,
                cache_path=Path(tmpdir) / ".cvs_radar_seen.json",
            )
            requested_urls = []
            crawler._get = lambda url: requested_urls.append(url) or "list-html"  # type: ignore[method-assign]
            with patch(
                "cvs_radar.crawler.parse_ptt_list",
                return_value=([{"url": "http://169.254.169.254/latest/meta-data", "push_count": "1"}], None),
            ):
                posts = crawler.crawl(max_pages=1)

        self.assertEqual(posts, [])
        self.assertEqual(requested_urls, ["https://example.test/bbs/CVS/index.html"])

    def test_crawl_marks_in_window_post_seen(self) -> None:
        post = Post(id="in", url="https://example.test/bbs/CVS/M.1.html", posted_at=datetime(2026, 6, 10, 12, 0))

        article_url, crawler, cached_urls, posts = self._crawl_one(post)

        self.assertEqual([post.id for post in posts], ["in"])
        self.assertIn(article_url, crawler.seen_urls)
        self.assertIn(article_url, cached_urls)


class ScoringTest(unittest.TestCase):
    def test_public_scoring_helpers_directly_score_and_group_products(self) -> None:
        posts = [
            Post(
                id="multi",
                brand="7-11",
                product_name="抹茶霜淇淋55草莓蛋糕59",
                author="a1",
                author_score=80,
            ),
            Post(
                id="single",
                brand="7-11",
                product_name="小7 阜杭饅頭豬排蛋 心得",
                author="a2",
                author_score=90,
                comments=[Comment("推", "u1", "好吃會回購", sentiment=0.9)],
            ),
        ]

        processed = preprocess_posts(posts)
        groups = group_products(processed)
        report = score_product([processed[-1]], {})
        reports = score_all(processed, {})

        self.assertEqual(canonical_product_name("7-11", "小7 阜杭饅頭豬排蛋 心得"), "阜杭豆漿饅頭夾豬排蛋")
        self.assertIn("抹茶霜淇淋", [post.product_name for post in processed])
        self.assertTrue(groups)
        self.assertEqual(report.product_name, "阜杭豆漿饅頭夾豬排蛋")
        self.assertEqual(representative_product_name([processed[-1]]), "阜杭豆漿饅頭夾豬排蛋")
        self.assertEqual([item.product_name for item in reports], ["阜杭豆漿饅頭夾豬排蛋", "抹茶霜淇淋", "草莓蛋糕"])

    def test_product_normalization_removes_brand(self) -> None:
        self.assertEqual(normalize_product("7-11", "711  測試飯糰"), "測試飯糰")

    def test_product_normalization_strips_noise_and_units(self) -> None:
        self.assertEqual(
            normalize_product("7-11", "鮪魚飯糰2入"),
            normalize_product("7-11", "鮪魚飯糰"),
        )
        self.assertEqual(
            normalize_product("全家", "新品 XX蛋糕 心得開箱"),
            normalize_product("全家", "XX蛋糕"),
        )

    def test_noise_regex_keeps_bare_lei_inside_product_name(self) -> None:
        # DEV-110 Bug B: a lone 雷 in the noise alternation must not be stripped
        # from inside a real name (蜂蜜雷夢 = 蜂蜜檸檬 pun).
        self.assertEqual(normalize_product("全家", "蜂蜜雷夢軟歐"), "蜂蜜雷夢軟歐")
        # compound editorial noise (踩雷) is still stripped.
        self.assertEqual(
            normalize_product("全家", "踩雷心得草莓大福"),
            normalize_product("全家", "草莓大福"),
        )

    def test_space_separated_parallel_products_split(self) -> None:
        # DEV-110 Bug A: two names sharing a product-type suffix, separated by a
        # space, must split into two products instead of concatenating.
        items = extract_products_and_prices(
            "：地瓜起司雞排三明治 厚里肌蛋沙拉三明治", "萊爾富"
        )
        self.assertEqual(
            [name for name, _ in items],
            ["地瓜起司雞排三明治", "厚里肌蛋沙拉三明治"],
        )

    def test_space_in_single_name_does_not_over_split(self) -> None:
        # A single product must stay one item when its space-separated segments
        # do not all end in a product-type suffix (brand prefix / partial name).
        self.assertEqual(
            [n for n, _ in extract_products_and_prices("全家 蜂蜜雷夢軟歐", "全家")],
            ["蜂蜜雷夢軟歐"],
        )
        self.assertEqual(
            [n for n, _ in extract_products_and_prices("明太子 起司貝果", "7-11")],
            ["明太子起司貝果"],
        )

    def test_product_synonym_normalization(self) -> None:
        self.assertEqual(
            normalize_product("7-11", "起士蛋糕"),
            normalize_product("7-11", "起司蛋糕"),
        )
        self.assertEqual(
            normalize_product("全家", "蕃薯球"),
            normalize_product("全家", "地瓜球"),
        )

    def test_product_grouping_merges_name_with_parenthetical(self) -> None:
        posts = [
            Post(id="p1", brand="7-11", product_name="阜杭豆漿饅頭夾豬排蛋", author="a1", author_score=80),
            Post(id="p2", brand="7-11", product_name="阜杭豆漿饅頭夾豬排蛋(新包裝)", author="a2", author_score=82),
        ]
        reports, _ = run_pipeline(posts)
        self.assertEqual(len(reports), 1)

    def test_product_grouping_keeps_different_flavors_separate_with_synonyms(self) -> None:
        posts = [
            Post(id="p1", brand="7-11", product_name="起司蛋糕", author="a1", author_score=80),
            Post(id="p2", brand="7-11", product_name="草莓蛋糕", author="a2", author_score=82),
        ]
        reports, _ = run_pipeline(posts)
        self.assertEqual(len(reports), 2)

    def test_product_grouping_does_not_merge_shared_flavor_without_product_form(self) -> None:
        self.assertFalse(_same_combo_flavor_product("鹽烤麻辣雞心", "麻辣奶油鮮蝦義大利麵"))
        self.assertFalse(_same_product("7-11", "鹽烤麻辣雞心", "麻辣奶油鮮蝦義大利麵"))

    def test_product_grouping_keeps_combo_flavor_shortcut_with_shared_product_form(self) -> None:
        self.assertTrue(_same_combo_flavor_product("麻辣起司飯糰", "起司麻辣飯糰"))
        self.assertTrue(_same_product("7-11", "麻辣起司飯糰", "起司麻辣飯糰"))

    def test_junk_product_name_falls_back_to_title_not_unknown(self) -> None:
        # The 商品名稱 field is promo junk that canonicalizes to "unknown"; the real
        # name lives in the title. Unrelated posts must not collapse under "unknown".
        posts = [
            Post(id="p1", brand="全家", title="[商品] 全家 牙寶寵物頭套",
                 product_name="：加價購169元", author="a1", author_score=80),
            Post(id="p2", brand="7-11", title="[商品] 7-11 動物方城市安全帽",
                 product_name="：\n599預購加點數", author="a2", author_score=82),
        ]
        processed = preprocess_posts(posts)
        names = [p.product_name for p in processed]
        self.assertNotIn("unknown", names)
        self.assertTrue(any("牙寶寵物頭套" in (n or "") for n in names))
        self.assertTrue(any("安全帽" in (n or "") for n in names))

    def test_rescue_discount_line_falls_back_to_title(self) -> None:
        # A Hi-Life poster put the 即時救援 (near-expiry rescue) discount price into the
        # 商品名稱 field; the real name "炸雞白醬燉飯" lives in the title. The rescue-promo
        # line must not become the product key (ptt M.1784209146).
        post = Post(id="p1", brand="萊爾富", title="[商品] 萊爾富-炸雞白醬燉飯",
                    product_name="售價：99元/ 即時救援7折69元", author="a1", author_score=80)
        names = [p.product_name for p in preprocess_posts([post])]
        self.assertNotIn("即時救援7折", names)
        self.assertTrue(any("炸雞白醬燉飯" in (n or "") for n in names))

    def test_bare_form_name_expands_to_title_flavor(self) -> None:
        # A shorthand price line ("霜淇淋49/草莓大福45") loses the flavor; the title
        # carries the full flavored name, which must be used instead of a bare "霜淇淋".
        post = Post(id="p1", brand="全家", title="[商品] 全家草莓優格x比利時巧克力霜淇淋",
                    product_name="：霜淇淋49/草莓大福45", author="a1", author_score=80)
        names = [p.product_name for p in preprocess_posts([post])]
        self.assertNotIn("霜淇淋", names)  # bare form replaced by the flavored title name
        self.assertTrue(any("霜淇淋" in (n or "") and "巧克力" in (n or "") for n in names))

    def test_pipeline_caps_same_user_comments_and_excludes_self_push(self) -> None:
        post = Post(
            id="p1",
            brand="7-11",
            product_name="測試飯糰",
            author="author",
            author_score=None,
            comments=[
                Comment("推", "spammer", "好吃"),
                Comment("推", "spammer", "好吃"),
                Comment("推", "spammer", "好吃"),
                Comment("噓", "critic", "難吃"),
                Comment("推", "author", "自己推"),
            ],
        )
        reports, _ = run_pipeline([post])
        report = reports[0]
        commenters = [c for c in report.contributors if c.role == "commenter"]
        self.assertEqual({c.user for c in commenters}, {"spammer", "critic"})
        self.assertEqual(len(commenters), 2)

    def test_public_json_does_not_expose_contributors(self) -> None:
        post = Post(id="p1", brand="7-11", product_name="測試", author="u", author_score=80)
        reports, _ = run_pipeline([post])
        payload = json.loads(render_json(reports, internal=False))
        self.assertNotIn("contributors", payload[0])

    def test_product_grouping_merges_noisy_same_product_titles(self) -> None:
        posts = [
            Post(id="p1", brand="7-11", product_name="阜杭豆漿饅頭夾豬排蛋", author="a1", author_score=80),
            Post(id="p2", brand="7-11", product_name="阜杭豆漿饅頭夾豬排蛋(回購)", author="a2", author_score=82),
            Post(id="p3", brand="7-11", product_name="7-11阜杭豆漿饅頭夾豬排蛋 心得", author="a3", author_score=84),
            Post(id="p4", brand="7-11", product_name="阜杭饅頭豬排蛋", author="a4", author_score=86),
            Post(id="p5", brand="7-11", product_name="小7 阜杭豆漿饅頭夾豬排蛋 分享", author="a5", author_score=88),
        ]

        reports, _ = run_pipeline(posts)

        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0].product_name, "阜杭豆漿饅頭夾豬排蛋")
        self.assertEqual(reports[0].product_key, "7-11:阜杭豆漿饅頭夾豬排蛋")

    def test_product_grouping_keeps_different_flavors_and_items_separate(self) -> None:
        posts = [
            Post(id="p1", brand="7-11", product_name="阜杭豆漿饅頭夾豬排蛋", author="a1", author_score=80),
            Post(id="p2", brand="7-11", product_name="阜杭豆漿饅頭夾豬排蛋辣味", author="a2", author_score=81),
            Post(id="p3", brand="7-11", product_name="阜杭豆漿飯糰豬排蛋", author="a3", author_score=82),
        ]

        reports, _ = run_pipeline(posts)

        self.assertEqual(
            {report.product_name for report in reports},
            {"阜杭豆漿饅頭夾豬排蛋", "阜杭豆漿饅頭夾豬排蛋辣味", "阜杭豆漿飯糰豬排蛋"},
        )

    def test_representative_comments_are_deduped_and_cleaned(self) -> None:
        post = Post(
            id="p1",
            brand="7-11",
            product_name="測試飯糰",
            author="author",
            comments=[
                Comment("推", "u1", "7-11 這款超好吃推薦"),
                Comment("推", "u2", "  超好吃  "),
                Comment("推", "u3", "超好吃"),
                Comment("噓", "u4", "7-11 這個很難吃"),
                Comment("噓", "u5", "很難吃"),
            ],
        )

        reports, _ = run_pipeline([post])

        self.assertEqual(reports[0].rep_positive, ["超好吃"])
        self.assertEqual(reports[0].rep_negative, ["很難吃"])

    def test_representative_comment_preserves_brand_inside_sentence(self) -> None:
        from cvs_radar.scoring import _clean_representative_comment

        self.assertEqual(
            _clean_representative_comment("全家", "全家的甜品真的只有友善才會捨得買"),
            "全家的甜品真的只有友善才會捨得買",
        )
        self.assertEqual(
            _clean_representative_comment("全家", "我買全家的時候會配咖啡，好吃"),
            "我買全家的時候會配咖啡,好吃",
        )
        self.assertEqual(
            _clean_representative_comment("7-11", "7-11 這款超好吃推薦"),
            "超好吃",
        )

    def test_public_reports_hide_internal_fields_unless_internal_mode(self) -> None:
        post = Post(id="p1", brand="7-11", product_name="測試", author="u", author_score=80)
        reports, _ = run_pipeline([post])

        public_payload = json.loads(render_json(reports, internal=False))
        internal_payload = json.loads(render_json(reports, internal=True))
        public_text = render_text(reports, internal=False)
        internal_text = render_text(reports, internal=True)

        self.assertNotIn("product_key", public_payload[0])
        self.assertNotIn("n_eff", public_payload[0])
        self.assertNotIn("score_std", public_payload[0])
        self.assertIn("evidence_note", public_payload[0])
        self.assertIn("product_key", internal_payload[0])
        self.assertIn("n_eff", internal_payload[0])
        self.assertNotIn("key=", public_text)
        self.assertNotIn("n_eff=", public_text)
        self.assertNotIn("std=", public_text)
        self.assertIn("key=", internal_text)

    def test_low_confidence_products_are_ranked_after_better_supported_items(self) -> None:
        posts = [
            Post(id="low", brand="7-11", product_name="高分但資料少", author="a1", author_score=100),
            Post(
                id="supported",
                brand="7-11",
                product_name="分數較穩",
                author="a2",
                author_score=80,
                comments=[
                    Comment("推", "u1", "好吃"),
                    Comment("推", "u2", "好吃"),
                    Comment("推", "u3", "好吃"),
                ],
            ),
        ]

        reports, _ = run_pipeline(posts)
        payload = json.loads(render_json(reports, internal=False))

        self.assertEqual([report.product_name for report in reports], ["分數較穩", "高分但資料少"])
        self.assertEqual(payload[1]["confidence"], "低")
        self.assertIn("降權", payload[1]["evidence_note"])

    def test_cross_brand_decision_1_keeps_own_brand_or_no_competitor_comments(self) -> None:
        post = Post(
            id="own",
            brand="全家",
            product_name="測試飯糰",
            comments=[
                Comment("推", "u1", "全家這款好吃"),
                Comment("推", "u2", "好吃會回購"),
            ],
        )

        reports, _ = run_pipeline([post])
        report = reports[0]

        self.assertIsNotNone(report.fair_score)
        self.assertEqual({c.user for c in report.contributors}, {"u1", "u2"})
        self.assertEqual(report.competitor_mention_count, 0)
        self.assertEqual(report.competitor_preference_count, 0)

    def test_cross_brand_decision_2_keeps_comment_when_own_brand_wins_comparison(self) -> None:
        post = Post(
            id="own-wins",
            brand="全家",
            product_name="測試甜點",
            comments=[
                Comment("→", "u1", "比小7好吃"),
                Comment("→", "u2", "吃過小7，還是全家的好吃"),
            ],
        )

        reports, _ = run_pipeline([post])
        report = reports[0]
        payload = json.loads(render_json(reports, internal=False))[0]

        self.assertIsNotNone(report.fair_score)
        self.assertEqual({c.user for c in report.contributors}, {"u1", "u2"})
        self.assertTrue(all(c.score > 0.5 for c in report.contributors))
        self.assertEqual(report.competitor_mention_count, 2)
        self.assertEqual(report.competitor_preference_count, 0)
        self.assertEqual(report.competitor_brands, ["7-11"])
        self.assertEqual(payload["competitor_mentions"]["preferred_other"], 0)

    def test_own_brand_positive_floor_does_not_override_llm_label(self) -> None:
        from cvs_radar.scoring import _comment_attribution

        # An LLM-labeled negative comment that the heuristics read as "own brand
        # wins" must keep its LLM score; the +0.4 floor only backstops lexicon.
        llm_comment = Comment("→", "u1", "全家比小7好一點但都難吃", sentiment=-0.5, backend="llm-backfill")
        lexicon_comment = Comment("→", "u2", "全家比小7好一點但都難吃", sentiment=-0.5, backend="lexicon")

        llm_attr = _comment_attribution("全家", llm_comment)
        lexicon_attr = _comment_attribution("全家", lexicon_comment)

        self.assertTrue(llm_attr.own_preference)
        self.assertEqual(llm_attr.effective_sentiment, -0.5)
        self.assertTrue(lexicon_attr.own_preference)
        self.assertEqual(lexicon_attr.effective_sentiment, 0.4)

    def test_cross_brand_decision_3_excludes_comment_when_competitor_wins_comparison(self) -> None:
        post = Post(
            id="other-wins",
            brand="全家",
            product_name="測試甜點",
            comments=[
                Comment("推", "u1", "小7的比較好吃"),
                Comment("推", "u2", "還是小7好"),
            ],
        )

        reports, _ = run_pipeline([post])
        report = reports[0]

        self.assertIsNone(report.fair_score)
        self.assertEqual(report.contributors, [])
        self.assertEqual(report.rep_positive, [])
        self.assertEqual(report.competitor_mention_count, 2)
        self.assertEqual(report.competitor_preference_count, 2)
        self.assertEqual(report.competitor_brands, ["7-11"])

    def test_cross_brand_decision_4_excludes_non_comparison_competitor_mentions(self) -> None:
        post = Post(
            id="other-mentioned",
            brand="全家",
            product_name="測試甜點",
            comments=[
                Comment("推", "u1", "小7也有賣"),
            ],
        )

        reports, _ = run_pipeline([post])
        report = reports[0]

        self.assertIsNone(report.fair_score)
        self.assertEqual(report.contributors, [])
        self.assertEqual(report.competitor_mention_count, 1)
        self.assertEqual(report.competitor_preference_count, 0)
        self.assertEqual(report.competitor_brands, ["7-11"])

    def test_competitor_attribution_respects_ascii_brand_boundaries(self) -> None:
        from cvs_radar.scoring import _comment_attribution

        for text in ("cookie 很好吃", "okay", "smoky 口味", "WACOOKIES"):
            with self.subTest(text=text):
                attribution = _comment_attribution("全家", Comment("推", "u1", text, sentiment=0.8))
                self.assertTrue(attribution.include_score)
                self.assertEqual(attribution.competitor_brands, ())

        for text in ("OK", "OKmart", "OK超商", "OK便利商店"):
            with self.subTest(text=text):
                attribution = _comment_attribution("全家", Comment("推", "u1", text, sentiment=0.8))
                self.assertFalse(attribution.include_score)
                self.assertEqual(attribution.competitor_brands, ("OK",))

    def test_reaction_echo_comments_do_not_count_as_independent_complaints(self) -> None:
        post = Post(
            id="M.1782841359.A.FDF",
            brand="7-11",
            product_name="富錦樹金沙南瓜",
            author="author",
            author_score=50,
            comments=[
                Comment("→", "reactor", "原來這麼雷", sentiment=-0.9),
                Comment("→", "firsthand", "我吃過真的難吃", sentiment=-0.9),
            ],
        )

        report = score_product([post], {})

        self.assertNotIn("reactor", {c.user for c in report.contributors})
        self.assertIn("firsthand", {c.user for c in report.contributors})
        self.assertNotIn("原來這麼雷", report.rep_negative)
        self.assertIn("我吃過真的難吃", report.rep_negative)


class ReviewExcerptTest(unittest.TestCase):
    def test_selects_purchase_relevant_sentences_in_source_order(self) -> None:
        post = Post(
            id="review",
            review_text=(
                "今天路過全家看到新品就買了\n"
                "奶香很明顯，甜度不高\n"
                "口感滑順但份量有點少\n"
                "整體耐吃，應該會再回購！"
            ),
        )

        excerpt = _review_excerpt([post])

        self.assertEqual(
            excerpt,
            "奶香很明顯，甜度不高。 口感滑順但份量有點少。 整體耐吃，應該會再回購。",
        )
        self.assertNotIn("路過", excerpt)

    def test_uses_distinct_evidence_across_multiple_posts(self) -> None:
        posts = [
            Post(id="taste", review_text="茶味很濃，尾韻帶一點苦味。", posted_at=datetime(2026, 6, 1)),
            Post(id="value", review_text="份量足夠，這個價位算划算。", posted_at=datetime(2026, 6, 2)),
        ]

        excerpt = _review_excerpt(posts)

        self.assertIn("茶味很濃", excerpt)
        self.assertIn("份量足夠", excerpt)

    def test_stops_at_signature_and_dedupes_near_identical_sentences(self) -> None:
        posts = [
            Post(id="one", review_text="口感很滑順，奶味也很香。\n--\n推文說價格太貴"),
            Post(id="two", review_text="口感滑順，奶味很香。"),
        ]

        excerpt = _review_excerpt(posts)

        self.assertNotIn("推文", excerpt)
        self.assertEqual(excerpt.count("奶味"), 1)

    def test_reconstructs_fixed_width_ptt_line_wraps(self) -> None:
        post = Post(
            id="wrapped",
            review_text=(
                "之前吃過一款桃我開心塔是\n\n"
                "半顆杏桃搭配硬塔皮，這款\n\n"
                "則是杏桃片搭配奶霜蛋糕，\n\n"
                "切片後罐頭水蜜桃感降低，\n\n"
                "加上柔軟奶霜蛋糕整體很順\n\n"
                "口，有點像在吃迷你生日蛋\n\n"
                "糕的感覺(?)\n\n--"
            ),
        )

        excerpt = _review_excerpt([post])

        self.assertIn("順口", excerpt)
        self.assertNotIn("這款。", excerpt)
        self.assertNotIn("生日蛋。", excerpt)
        self.assertNotIn("(。", excerpt)

    def test_respects_length_limit_without_cutting_a_sentence(self) -> None:
        post = Post(id="short", review_text="茶味濃而且不會太甜。\n口感滑順，喝起來很清爽。")

        excerpt = _review_excerpt([post], max_len=18)

        self.assertLessEqual(len(excerpt), 18)
        self.assertTrue(excerpt.endswith("。"))

    def test_parenthetical_note_does_not_merge_with_next_opinion(self) -> None:
        sentences = _review_sentences(
            "（但補充一下因為還沒烤過之前就吃光了，所以不知道烤過會如何）\n"
            "我覺得黑糖味道很濃郁而且不會太甜"
        )

        self.assertTrue(any(sentence.startswith("我覺得") for sentence in sentences))
        self.assertTrue(all(")我覺得" not in sentence for sentence in sentences))

    def test_removes_unmatched_parentheses_without_dropping_review_text(self) -> None:
        posts = [
            Post(id="open", review_text="奶味很香，是整體唯一救贖(。"),
            Post(id="close", review_text=")口感偏硬，我不會再買。"),
        ]

        excerpt = _review_excerpt(posts)

        self.assertNotIn("(", excerpt)
        self.assertNotIn(")", excerpt)
        self.assertIn("唯一救贖", excerpt)
        self.assertIn("不會再買", excerpt)


class ExtractionRegressionTest(unittest.TestCase):
    def test_extract_products_and_prices_cases(self) -> None:
        cases = [
            ("BF薄荷岩鹽檸檬糖35", [("BF薄荷岩鹽檸檬糖", 35)]),
            ("抹茶霜淇淋兩支55抹茶千層59", [("抹茶霜淇淋", 55), ("抹茶千層", 59)]),
            ("：\n大大大香辣鹹酥雞/59\n兩件88元", [("大大大香辣鹹酥雞", 59)]),
            ("詹姆士香蒜胡椒肉骨茶泡麵 79元", [("詹姆士香蒜胡椒肉骨茶泡麵", 79)]),
            ("莊園牛奶霜淇淋49\n取件優惠買一送一", [("莊園牛奶霜淇淋", 49)]),
            ("https://example.test/deal/999\nBF薄荷岩鹽檸檬糖35", [("BF薄荷岩鹽檸檬糖", 35)]),
            ("抹茶霜淇淋/草莓蛋糕都55元", [("抹茶霜淇淋", 55), ("草莓蛋糕", 55)]),
            (
                "：\n沙漠之星(石榴洛神氣泡飲)、\n法老的紅寶石(草莓氣泡飲)、\n拉神之眼(柑橘氣泡飲)/各49$",
                [("沙漠之星", 49), ("法老的紅寶石", 49), ("拉神之眼", 49)],
            ),
        ]

        for raw_name, expected in cases:
            with self.subTest(raw_name=raw_name):
                self.assertEqual(extract_products_and_prices(raw_name), expected)

    def test_extract_products_and_prices_template_garbage(self) -> None:
        results = extract_products_and_prices("：\n(區域型商品請註明 試吃試用品請標示價格0元)")

        self.assertFalse(
            [
                (name, price)
                for name, price in results
                if name.strip() and price is not None
            ]
        )

    def test_reply_post_signature_commentary_is_not_a_product(self) -> None:
        raw_name = (
            "：7-11 切達起士貝果 28元\n\n"
            ": 【便利商店/廠商名稱】：7-11\n\n"
            ": 【心得】：\n\n"
            ": 藍莓寒天貝果，這款也是我愛吃的口味，\n\n"
            ": --\n\n"
            "身為友善人 這2款貝果是少數無打折會去買的\n\n"
            "28元撐了15年  今天看到藍莓口味改版變35元\n\n"
            "--"
        )
        post = Post(
            id="M.1782550157.A.0A3",
            brand="7-11",
            product_name=raw_name,
            is_reply=True,
        )

        processed = preprocess_posts([post])
        names = [item.product_name for item in processed]

        self.assertIn("切達起士貝果", names)
        self.assertFalse(any("今天看到藍莓" in name or "年今天" in name for name in names))

    def test_reply_post_quoted_review_prose_is_not_a_product(self) -> None:
        raw_name = (
            "：7-11 切達起士貝果 28元\n\n\n"
            ": 【便利商店/廠商名稱】：7-11\n\n\n"
            ": 【規格/內容物/熱量】：\n\n\n"
            ": 【評分】： 60\n\n\n"
            ": (未滿60分為不推薦)\n\n\n"
            ": 【心得】：\n\n\n"
            ": \nhttp://example.com/blog\n\n\n"
            ": 切達起士貝果買回來後，用烤箱烤一下，\n\n\n"
            ": 真的蠻好吃的~\n\n\n"
            ": 可惜價格太貴了=  =  28元買一個貝果，CP值很低><\n\n\n"
            ": 而且餡料似乎有縮水~不然，起司的味道還不錯!!!\n\n\n"
            ": 鹹的口味比較耐吃^^\n\n\n"
            ": 藍莓寒天貝果，這款也是我愛吃的口味，\n\n\n"
            ": 藍莓特有的甜味很不錯，然後塗的果醬不會說太少~\n\n\n"
            ": 但跟起司貝果比較的話，起司的分數比較高~\n\n\n"
            ": --\n \n \n"
            "身為友善人 這2款貝果是少數無打折會去買的\n \n"
            "雖然知道漲價是遲早的事 沒想到一次漲這麼多\n \n"
            "28元撐了15年  今天看到藍莓口味改版變35元\n \n"
            "切達口味應該也快了….\n \n \n \n--"
        )
        post = Post(
            id="M.1782550157.A.0A3",
            brand="7-11",
            product_name=raw_name,
            is_reply=True,
        )

        processed = preprocess_posts([post])

        self.assertEqual([item.product_name for item in processed], ["切達起士貝果"])
        self.assertEqual(processed[0].price, "28")
        self.assertFalse(any("可惜價格太貴了" in item.product_name for item in processed))

    def test_payment_aside_after_slash_is_not_product_name(self) -> None:
        raw_name = "：萊爾富X頂呱呱13cm娃包/ipass聯邦卡付款71元（？\n\nhttps://i.mopix.cc/CbGuR4.jpg"

        result = extract_products_and_prices(raw_name, "萊爾富")

        self.assertEqual(result, [("X頂呱呱13cm娃包", 71)])
        self.assertNotIn("ipass", result[0][0].lower())
        self.assertNotIn("聯邦卡付款", result[0][0])

    def test_price_only_product_field_falls_back_to_title_name_and_primary_price(self) -> None:
        post = Post(
            id="M.1765785731.A.F72",
            title="[商品] 全家 惡魔乳酪生義大利麵",
            brand="全家",
            product_name="：99 目前會員特價88\n(區域型商品請註明 試吃試用品請標示價格0元)",
            price="：99 目前會員特價88",
        )

        processed = preprocess_posts([post])

        self.assertEqual(len(processed), 1)
        self.assertEqual(processed[0].product_name, "惡魔乳酪生義大利麵")
        self.assertEqual(processed[0].price, "99")
        self.assertEqual(categorize_product(processed[0].product_name), "便當")

    def test_preorder_points_field_falls_back_to_title_name_and_price(self) -> None:
        post = Post(
            id="M.1765708866.A.59B",
            title="[商品] 7-11聯名動物方城市安全帽",
            brand="7-11",
            product_name="：\n599預購加點數",
            price="：\n599預購加點數",
        )

        processed = preprocess_posts([post])

        self.assertEqual(len(processed), 1)
        self.assertEqual(processed[0].product_name, "動物方城市安全帽")
        self.assertEqual(processed[0].price, "599")
        self.assertEqual(categorize_product(processed[0].product_name), "周邊")

    def test_digit_promo_fragment_falls_back_to_title_name(self) -> None:
        post = Post(
            id="M.1761067990.A.125",
            title="[商品] 7-11 明太子雞肉溏心蛋三明治",
            brand="7-11",
            product_name="：85套餐\n(區域型商品請註明 試吃試用品請標示價格0元)",
            price="：85套餐",
        )

        processed = preprocess_posts([post])

        self.assertEqual(len(processed), 1)
        self.assertEqual(processed[0].product_name, "明太子雞肉溏心蛋三明治")
        self.assertEqual(processed[0].price, "85")

    def test_trailing_points_exchange_suffix_is_stripped(self) -> None:
        post = Post(
            id="M.1767279405.A.5B1",
            title="[商品] 全家 SOMA 荔枝烏龍鮮果凍",
            brand="全家",
            product_name="SOMA 荔枝烏龍鮮果凍點數兌換",
        )

        processed = preprocess_posts([post])

        self.assertEqual(len(processed), 1)
        self.assertEqual(processed[0].product_name, "SOMA荔枝烏龍鮮果凍")

    def test_real_digit_product_names_are_not_replaced_by_title(self) -> None:
        posts = [
            Post(
                id="digit-chocolate",
                title="[商品] 7-11 77乳加星球含餡巧克力",
                brand="7-11",
                product_name="77乳加星球含餡巧克力",
            ),
            Post(
                id="digit-coffee",
                title="[商品] 全家 5minx膽大黨茶包式咖啡",
                brand="全家",
                product_name="5minx膽大黨茶包式咖啡",
            ),
        ]

        processed = preprocess_posts(posts)

        self.assertEqual(
            [post.product_name for post in processed],
            ["77乳加星球含餡巧克力", "5minx膽大黨茶包式咖啡"],
        )


class CategoryRegressionTest(unittest.TestCase):
    def test_categorize_product_cases(self) -> None:
        cases = [
            ("霜淇淋", "冰品"),
            ("拿鐵", "飲料"),
            ("蛋糕", "甜點"),
            ("可頌", "麵包"),
            ("捏捏球", "周邊"),
            ("吊飾", "周邊"),
            ("動物方城市安全帽", "周邊"),
            ("雞排", "鹹食"),
            ("unknown_product_xyz", "其他"),
        ]

        for name, expected in cases:
            with self.subTest(name=name):
                self.assertEqual(categorize_product(name), expected)


class PrecomputedResultsTest(unittest.TestCase):
    def _report(self, price: int | None = 49, category: str = "冰品") -> ProductReport:
        return ProductReport(
            brand="7-11",
            product_name="莊園牛奶霜淇淋",
            fair_score=85.0,
            consensus="推薦",
            confidence="中",
            n_eff=1.0,
            score_std=0.0,
            n_posts=1,
            n_comments=0,
            price=price,
            category=category,
        )

    def test_load_results_preserves_price_and_category(self) -> None:
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "results.json"
            payload = {
                "generated_at": "2026-06-30 12:00:00",
                "reports": [store.report_to_store_dict(self._report())],
                "profiles": [],
            }
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

            loaded = store.load_results(path)

        assert loaded is not None
        reports, profiles = loaded
        self.assertEqual(profiles, {})
        stored = store.report_to_store_dict(reports[0])
        self.assertEqual(stored["price"], 49)
        self.assertEqual(stored["category"], "冰品")

    def test_store_dict_to_report_handles_missing_price_and_category(self) -> None:
        data = store.report_to_store_dict(self._report())
        data.pop("price")
        data.pop("category")

        report = store.store_dict_to_report(data)

        self.assertIsNone(report.price)
        self.assertEqual(report.category, "")

    def test_report_to_store_dict_includes_price_and_category(self) -> None:
        data = store.report_to_store_dict(self._report(price=59, category="甜點"))

        self.assertEqual(data["price"], 59)
        self.assertEqual(data["category"], "甜點")


class SentimentTest(unittest.TestCase):
    def test_override_ignores_trailing_punctuation(self) -> None:
        post = Post(
            id="sentiment-override",
            comments=[Comment("→", "u1", "先看有沒有毒油啊!!", sentiment=0.8)],
        )

        apply_sentiment_overrides([post], {"先看有沒有毒油啊": -0.9})

        self.assertEqual(post.comments[0].sentiment, -0.9)
        self.assertEqual(post.comments[0].backend, "codex")

    def test_public_sentiment_helpers_resolve_annotate_and_check_key(self) -> None:
        post = Post(
            id="sentiment",
            brand="7-11",
            product_name="測試飯糰",
            comments=[Comment("推", "u1", "好吃會回購")],
        )

        with patch.dict("os.environ", {}, clear=True):
            has_key = llm_has_key()
        annotated = annotate_posts([post])

        self.assertEqual(clamp(2.5), 1.0)
        self.assertEqual(clamp(-2.5), -1.0)
        self.assertEqual(tag_prior("噓"), -1.0)
        self.assertEqual(resolve_backend("lexicon").name, "lexicon")
        self.assertFalse(has_key)
        self.assertGreater(annotated[0].comments[0].sentiment, 0)
        self.assertEqual(annotated[0].comments[0].backend, "lexicon")

    def test_tag_and_lexicon_mix(self) -> None:
        self.assertGreater(score_comment("推", "好吃會回購"), 0)
        self.assertLess(score_comment("噓", "難吃踩雷"), 0)
        self.assertEqual(score_comment("→", ""), 0)

    def test_lexicon_skips_sentiment_chars_inside_compound_nouns(self) -> None:
        from cvs_radar.sentiment import lexicon_score

        # 乾 in 餅乾 / 油 in 麻油 / 香 in 香草 are product names, not opinions:
        # they must not dilute or flip the real sentiment words around them.
        self.assertEqual(lexicon_score("這餅乾好吃"), 1.0)
        self.assertEqual(lexicon_score("麻油雞好香"), 0.6)
        self.assertEqual(lexicon_score("香草口味"), 0.0)
        # Standalone sentiment chars still count.
        self.assertLess(lexicon_score("吃起來太乾"), 0)
        self.assertLess(lexicon_score("好油喔超難吃"), 0)

    def test_backend_switch_accepts_lexicon_and_snownlp(self) -> None:
        lexicon_score = score_comment("→", "好吃會回購", backend="lexicon")
        snownlp_score = score_comment("→", "好吃會回購", backend="snownlp")

        self.assertGreater(lexicon_score, 0)
        self.assertGreaterEqual(snownlp_score, -1)
        self.assertLessEqual(snownlp_score, 1)

    def test_tag_prior_remains_primary_over_text_backend(self) -> None:
        self.assertGreater(score_comment("推", "難吃踩雷", backend="snownlp"), 0)
        self.assertLess(score_comment("噓", "好吃會回購", backend="snownlp"), 0)

    def test_llm_backend_without_key_falls_back_without_network_client(self) -> None:
        backend = LlmBackend(client=None)

        score = score_comment("推", "好吃會回購", backend=backend)

        self.assertGreater(score, 0)

    def test_openai_client_parses_float_response(self) -> None:
        """OpenAiSentimentClient.score_text returns float from API response."""
        import sys
        import types
        from unittest.mock import MagicMock, patch
        from cvs_radar.sentiment import OpenAiSentimentClient

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "0.75"

        client = OpenAiSentimentClient()
        fake_openai = types.SimpleNamespace(OpenAI=MagicMock())
        with patch.dict(sys.modules, {"openai": fake_openai}):
            with patch("openai.OpenAI") as mock_openai:
                mock_openai.return_value.chat.completions.create.return_value = mock_response
                score = client.score_text("好吃會回購", provider="openai", model="gpt-4o-mini", api_key="test-key")

        self.assertAlmostEqual(score, 0.75)

    def test_openai_client_negative_response(self) -> None:
        """OpenAiSentimentClient handles negative scores."""
        import sys
        import types
        from unittest.mock import MagicMock, patch
        from cvs_radar.sentiment import OpenAiSentimentClient

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "-0.8"

        client = OpenAiSentimentClient()
        fake_openai = types.SimpleNamespace(OpenAI=MagicMock())
        with patch.dict(sys.modules, {"openai": fake_openai}):
            with patch("openai.OpenAI") as mock_openai:
                mock_openai.return_value.chat.completions.create.return_value = mock_response
                score = client.score_text("難吃踩雷", provider="openai", model="gpt-4o-mini", api_key="test-key")

        self.assertAlmostEqual(score, -0.8)

    def test_llm_backend_fallback_when_no_key(self) -> None:
        """LlmBackend falls back to snownlp when no API key is set."""
        import os
        from unittest.mock import patch
        from cvs_radar.sentiment import LlmBackend

        with patch.dict(os.environ, {}, clear=True):
            backend = LlmBackend()
            score = backend.text_score("好吃")

        self.assertIsInstance(score, float)
        self.assertGreaterEqual(score, -1.0)
        self.assertLessEqual(score, 1.0)

    def test_llm_backend_fallback_on_api_error(self) -> None:
        """LlmBackend falls back when API call raises."""
        from unittest.mock import patch
        from cvs_radar.sentiment import LlmBackend, OpenAiSentimentClient

        client = OpenAiSentimentClient()
        with patch.object(client, "score_text", side_effect=Exception("API error")):
            backend = LlmBackend(client=client)
            with patch.dict("os.environ", {"CVS_RADAR_LLM_API_KEY": "test"}):
                with patch(
                    "cvs_radar.sentiment.SENTIMENT",
                    {
                        "backend": "llm",
                        "tag_prior_weight": 0.6,
                        "llm": {
                            "enabled": True,
                            "provider": "openai",
                            "model": "gpt-4o-mini",
                            "api_key": "",
                            "api_key_env": "CVS_RADAR_LLM_API_KEY",
                            "fallback_backend": "lexicon",
                        },
                    },
                ):
                    score = backend.text_score("好吃")

        self.assertIsInstance(score, float)


class TimeAndServiceTest(unittest.TestCase):
    def test_time_window_public_helpers_parse_validate_and_clone_posts(self) -> None:
        from cvs_radar.filters import TimeWindow, build_time_window, filter_post_by_time, filter_posts_by_time, parse_datetime

        post = Post(
            id="dated",
            brand="7-11",
            product_name="Coffee",
            author_score=80,
            posted_at=datetime(2026, 6, 2, 10, 0),
            comments=[
                Comment("推", "in", "好吃", datetime(2026, 6, 2, 11, 0)),
                Comment("噓", "out", "難吃", datetime(2026, 6, 3, 11, 0)),
            ],
        )
        window = build_time_window(start_date="2026/06/02", end_date="20260602")

        selected_post = filter_post_by_time(post, window)
        selected_posts = filter_posts_by_time([post], start_date="2026-06-02", end_date="2026-06-02")

        assert selected_post is not None
        self.assertEqual(parse_datetime("2026-06-02").isoformat(), "2026-06-02T00:00:00")
        self.assertTrue(window.enabled)
        self.assertTrue(window.contains(datetime(2026, 6, 2, 23, 59)))
        self.assertFalse(TimeWindow(start=datetime(2026, 6, 4)).contains(None))
        self.assertEqual([comment.user for comment in selected_post.comments], ["in"])
        self.assertEqual([comment.user for comment in selected_posts[0].comments], ["in"])

    def test_pipeline_filters_posts_and_comments_by_date(self) -> None:
        from datetime import datetime

        post = Post(
            id="dated",
            brand="7-11",
            product_name="Coffee",
            author="author",
            author_score=100,
            posted_at=datetime(2026, 6, 1, 10, 0),
            comments=[
                Comment("push", "old", "great", datetime(2026, 6, 1, 11, 0)),
                Comment("boo", "new", "bad", datetime(2026, 6, 10, 11, 0)),
            ],
        )

        reports, _ = run_pipeline([post], start_date="2026-06-10", end_date="2026-06-10")

        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0].n_comments, 1)
        self.assertEqual({c.user for c in reports[0].contributors}, {"new"})

    def test_time_filter_keeps_unknown_time_comments_only_when_parent_post_matches(self) -> None:
        from datetime import datetime
        from cvs_radar.service import select_reviews

        posts = [
            Post(
                id="in",
                brand="7-11",
                product_name="Coffee",
                posted_at=datetime(2026, 6, 10, 10, 0),
                comments=[Comment("push", "unknown", "great", None)],
            ),
            Post(
                id="out",
                brand="7-11",
                product_name="Tea",
                posted_at=datetime(2026, 6, 1, 10, 0),
                comments=[Comment("push", "unknown", "great", None)],
            ),
        ]

        selected = select_reviews(posts, start_date="2026-06-10", end_date="2026-06-10")

        self.assertEqual([post.id for post in selected], ["in"])
        self.assertEqual([comment.user for comment in selected[0].comments], ["unknown"])

    def test_pipeline_does_not_mutate_input_posts(self) -> None:
        post = Post(
            id="immutable",
            brand="7-11",
            product_name="Coffee",
            comments=[Comment("push", "u1", "great")],
        )

        run_pipeline([post])

        self.assertIsNone(post.comments[0].sentiment)

    def test_recent_days_filter_uses_supplied_now(self) -> None:
        from datetime import datetime
        from cvs_radar.service import select_reviews

        posts = [
            Post(id="old", brand="7-11", product_name="Old", posted_at=datetime(2026, 6, 1)),
            Post(id="new", brand="7-11", product_name="New", posted_at=datetime(2026, 6, 14)),
        ]

        selected = select_reviews(posts, recent_days=3, now=datetime(2026, 6, 15))

        self.assertEqual([post.id for post in selected], ["new"])

    def test_time_filter_mixed_timezone_uses_wall_clock(self) -> None:
        from datetime import datetime
        from cvs_radar.service import select_reviews

        posts = [
            Post(id="before", brand="7-11", product_name="Before", posted_at=datetime(2026, 5, 31, 20, 0)),
            Post(id="after", brand="7-11", product_name="After", posted_at=datetime(2026, 6, 1, 1, 0)),
        ]

        selected = select_reviews(posts, start_date="2026-06-01T00:00:00+08:00")

        self.assertEqual([post.id for post in selected], ["after"])

    def test_time_window_validation_accepts_mixed_timezone_bounds(self) -> None:
        from datetime import datetime
        from cvs_radar.service import select_reviews

        posts = [
            Post(id="in", brand="7-11", product_name="In", posted_at=datetime(2026, 6, 1, 12, 0)),
        ]

        selected = select_reviews(
            posts,
            start_date="2026-06-01T00:00:00+08:00",
            end_date="2026-06-02",
        )

        self.assertEqual([post.id for post in selected], ["in"])

    def test_timezone_matrix_filters_recent_window_and_latest_date(self) -> None:
        from cvs_radar.service import select_reviews

        raw_times = (
            "2026-06-01T08:00:00",
            "2026-06-01T08:00:00+08:00",
            "2026-06-01T00:00:00Z",
        )
        posts = [
            store.dict_to_post(
                {
                    "id": f"tz-{index}",
                    "brand": "7-11",
                    "product_name": "時區測試",
                    "posted_at": raw_time,
                    "comments": [],
                }
            )
            for index, raw_time in enumerate(raw_times)
        ]

        taipei = ZoneInfo("Asia/Taipei")
        expected = datetime(2026, 6, 1, 8, 0, tzinfo=taipei)
        self.assertTrue(all(post.posted_at == expected for post in posts))
        selected = select_reviews(
            posts,
            start_date="2026-06-01T07:59:00+08:00",
            end_date="2026-06-01T08:01:00+08:00",
        )
        recent = select_reviews(
            posts,
            recent_days=1,
            now=datetime(2026, 6, 2, 8, 0, tzinfo=taipei),
        )
        self.assertEqual([post.id for post in selected], ["tz-0", "tz-1", "tz-2"])
        self.assertEqual([post.id for post in recent], ["tz-0", "tz-1", "tz-2"])

        mixed = posts + [
            Post(
                id="tz-latest",
                brand="7-11",
                product_name="時區測試",
                posted_at=datetime(2026, 6, 1, 1, 0, tzinfo=ZoneInfo("UTC")),
            )
        ]
        report = score_product(mixed, {})
        self.assertEqual(report.latest_post_date, datetime(2026, 6, 1, 9, 0, tzinfo=taipei))

    def test_service_lists_brands_and_filters_rankings(self) -> None:
        from cvs_radar.service import ProductQuery, list_brands, query_products

        posts = [
            Post(id="a", brand="7-11", product_name="Coffee", author="a1", author_score=90),
            Post(id="b", brand="FamilyMart", product_name="Tea", author="b1", author_score=50),
            Post(id="c", brand="7-11", product_name="Cake", author="a2", author_score=70),
        ]

        brands = list_brands(posts)
        result = query_products(posts, ProductQuery(brand="7-11", min_score=50, min_posts=1))
        payload = result.to_dict()

        self.assertEqual({item.brand for item in brands}, {"7-11", "FamilyMart"})
        self.assertEqual([report.brand for report in result.reports], ["7-11", "7-11"])
        self.assertGreaterEqual(result.reports[0].fair_score, result.reports[1].fair_score)
        self.assertIn("reports", payload)
        self.assertNotIn("contributors", payload["reports"][0])

    def test_service_brand_filter_accepts_aliases(self) -> None:
        from cvs_radar.service import ProductQuery, query_products

        posts = [
            Post(id="a", brand="7-11", product_name="Coffee", author="a1", author_score=90),
            Post(id="b", brand="FamilyMart", product_name="Tea", author="b1", author_score=50),
        ]

        result = query_products(posts, ProductQuery(brand="711"))

        self.assertEqual([report.brand for report in result.reports], ["7-11"])

    def test_service_rejects_negative_report_filters(self) -> None:
        from cvs_radar.service import filter_reports

        with self.assertRaisesRegex(ValueError, "limit must be non-negative"):
            filter_reports([], limit=-1)

        with self.assertRaisesRegex(ValueError, "min_score must be non-negative"):
            filter_reports([], min_score=-0.1)

    def test_service_recent_days_filters_and_metadata_use_same_now(self) -> None:
        from datetime import datetime
        from cvs_radar.service import ProductQuery, query_products

        now = datetime(2026, 6, 15, 12, 0)
        posts = [
            Post(id="old", brand="7-11", product_name="Old", author_score=90, posted_at=datetime(2026, 6, 12, 11, 59)),
            Post(id="new", brand="7-11", product_name="New", author_score=80, posted_at=datetime(2026, 6, 12, 12, 0)),
        ]

        result = query_products(posts, ProductQuery(recent_days=3), now=now)

        self.assertEqual([report.product_name for report in result.reports], ["New"])
        self.assertEqual(result.filters["start_date"], "2026-06-12T12:00:00")
        self.assertEqual(result.filters["end_date"], "2026-06-15T12:00:00")

    def test_brand_summaries_from_reports_aggregates_product_reports(self) -> None:
        from cvs_radar.service import brand_summaries_from_reports

        reports = [
            ProductReport("7-11", "A", 80, "一致好評", "低", 1, 0, 2, 3),
            ProductReport("7-11", "B", 70, "褒貶不一", "低", 1, 0, 1, 1),
            ProductReport("全家", "C", 60, "褒貶不一", "低", 1, 0, 4, 5),
        ]

        summaries = brand_summaries_from_reports(reports)

        self.assertEqual([(item.brand, item.product_count, item.post_count, item.comment_count) for item in summaries], [
            ("7-11", 2, 3, 4),
            ("全家", 1, 4, 5),
        ])


class AppHelperTest(unittest.TestCase):
    def test_volume_label_caps_single_post_high_confidence_reports(self) -> None:
        from cvs_radar.app_helpers import volume_label

        single_post = ProductReport("7-11", "單篇商品", 80, "一致好評", "高", 9, 0.1, 1, 10)
        multi_post = ProductReport("7-11", "多篇商品", 80, "一致好評", "高", 9, 0.1, 2, 10)

        self.assertEqual(volume_label(single_post), "聲量中等")
        self.assertEqual(volume_label(multi_post), "聲量充足")

    def test_consensus_distribution_uses_zero_to_one_contributor_scores(self) -> None:
        from cvs_radar.app_helpers import consensus_distribution
        from cvs_radar.models import Contributor

        report = ProductReport(
            brand="7-11",
            product_name="測試商品",
            fair_score=60,
            consensus="褒貶不一",
            confidence="高",
            n_eff=6,
            score_std=0.3,
            n_posts=1,
            n_comments=3,
            contributors=[
                Contributor("positive", "commenter", 0.8, 3),
                Contributor("neutral", "commenter", 0.5, 2),
                Contributor("negative", "commenter", 0.2, 1),
            ],
        )

        self.assertEqual(consensus_distribution(report), (50, 33, 17))

    def test_load_results_or_none_delegates_to_store_loader(self) -> None:
        from cvs_radar.app_helpers import load_results_or_none

        with patch("cvs_radar.store.load_results", return_value=([], {})):
            self.assertEqual(load_results_or_none(), ([], {}))

    def test_app_helpers_use_service_query_shape(self) -> None:
        from datetime import datetime
        from cvs_radar.app_helpers import (
            ALL_BRANDS,
            brand_options,
            build_product_query,
            filter_reports_by_search,
            product_rows,
            relative_date_label,
        )
        from cvs_radar.sample_data import load_sample
        from cvs_radar.service import query_products

        now = datetime(2026, 6, 15, 12, 0)
        posts = load_sample()
        reports = [
            ProductReport(
                brand="7-11",
                product_name="伯爵 紅茶拿鐵",
                fair_score=82,
                consensus="一致好評",
                confidence="高",
                n_eff=3,
                score_std=0.1,
                n_posts=1,
                n_comments=2,
            ),
            ProductReport(
                brand="FamilyMart",
                product_name="香蕉優格",
                fair_score=70,
                consensus="褒貶不一",
                confidence="中",
                n_eff=2,
                score_std=0.2,
                n_posts=1,
                n_comments=1,
            ),
        ]

        options = brand_options(posts, recent_days=30, now=now)
        query = build_product_query(
            brand=ALL_BRANDS,
            recent_days=30,
            min_posts=1,
            min_comments=0,
            limit=5,
        )
        result = query_products(posts, query, now=now)
        rows = product_rows(result)

        self.assertEqual(options[0], ALL_BRANDS)
        self.assertIsNone(query.brand)
        self.assertTrue(rows)
        self.assertLessEqual(len(rows), 5)
        self.assertIn("fair_score", rows[0])
        self.assertIn("正向留言", rows[0])
        self.assertIn("討論聲量", rows[0])
        self.assertEqual(filter_reports_by_search(reports, "紅茶拿鐵"), [reports[0]])
        self.assertEqual(filter_reports_by_search(reports, "family"), [reports[1]])
        self.assertEqual(filter_reports_by_search(reports, "優 格"), [reports[1]])
        self.assertEqual(relative_date_label("2026-06-12", now=datetime(2026, 6, 15, 12, 0)), "3 天前")
        self.assertEqual(relative_date_label("2026-06-01", now=datetime(2026, 6, 15)), "2 週前")
        self.assertEqual(relative_date_label("2026-05-01", now=datetime(2026, 6, 15)), "1 個月前")

    def test_filter_reports_by_recent_days(self) -> None:
        from datetime import datetime
        from cvs_radar.app_helpers import filter_reports_by_recent_days

        now = datetime(2026, 7, 7, 12, 0)
        recent = ProductReport(
            brand="7-11", product_name="新品", fair_score=80, consensus="一致好評",
            confidence="高", n_eff=3, score_std=0.1, n_posts=1, n_comments=2,
            latest_post_date=datetime(2026, 7, 5),
        )
        old = ProductReport(
            brand="全家", product_name="舊品", fair_score=70, consensus="褒貶不一",
            confidence="中", n_eff=2, score_std=0.2, n_posts=1, n_comments=1,
            latest_post_date=datetime(2026, 1, 1),
        )
        undated = ProductReport(
            brand="OK", product_name="無日期", fair_score=60, consensus="褒貶不一",
            confidence="低", n_eff=1, score_std=0.3, n_posts=1, n_comments=0,
            latest_post_date=None,
        )
        reports = [recent, old, undated]
        # None / non-positive window means no date filtering.
        self.assertEqual(filter_reports_by_recent_days(reports, None), reports)
        self.assertEqual(filter_reports_by_recent_days(reports, 0), reports)
        # A 30-day window keeps only the recent report; undated is dropped.
        self.assertEqual(filter_reports_by_recent_days(reports, 30, now=now), [recent])


class ReportingTest(unittest.TestCase):
    def test_reporting_public_helpers_render_dict_suspicion_and_hash(self) -> None:
        from cvs_radar.preference import AccountProfile

        report = ProductReport(
            brand="7-11",
            product_name="測試飯糰",
            fair_score=80,
            consensus="一致好評",
            confidence="高",
            n_eff=5,
            score_std=0.1,
            n_posts=1,
            n_comments=1,
        )
        profile = AccountProfile(user="alice", total_comments=3, suspicion_score=0.2, credibility=0.8)

        payload = report_to_dict(report)
        suspicion = render_suspicion({"alice": profile})

        self.assertEqual(payload["brand"], "7-11")
        self.assertNotIn("contributors", payload)
        self.assertIn("alice", suspicion)
        self.assertEqual(hash_user("alice"), hash_user("alice"))
        self.assertNotEqual(hash_user("alice"), hash_user("bob"))


class CrawlerTest(unittest.TestCase):
    def test_seen_cache_creates_parent_directory(self) -> None:
        from tempfile import TemporaryDirectory
        from pathlib import Path
        from cvs_radar.crawler import PttCrawler

        with TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "nested" / "seen.json"
            crawler = PttCrawler(cache_path=cache_path, request_delay_sec=0, retries=0)
            crawler.seen_urls.add("https://www.ptt.cc/bbs/CVS/M.test.html")

            crawler._save_seen()

            self.assertTrue(cache_path.exists())

    def test_crawl_does_not_mark_filtered_out_articles_as_seen(self) -> None:
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from cvs_radar.crawler import PttCrawler

        list_html = """
        <div class="r-ent">
          <div class="nrec">1</div>
          <div class="title"><a href="/bbs/CVS/M.old.html">[商品] 711 Old</a></div>
          <div class="author">author</div>
          <div class="date">6/01</div>
        </div>
        """
        article_html = """
        <div id="main-content">
          <div class="article-metaline"><span class="article-meta-tag">作者</span><span class="article-meta-value">author</span></div>
          <div class="article-metaline"><span class="article-meta-tag">標題</span><span class="article-meta-value">[商品] 711 Old</span></div>
          <div class="article-metaline"><span class="article-meta-tag">時間</span><span class="article-meta-value">Mon Jun  1 12:00:00 2026</span></div>
          【商品名稱】Old
          【評分】80
        </div>
        """

        with TemporaryDirectory() as tmp:
            crawler = PttCrawler(cache_path=Path(tmp) / "seen.json", request_delay_sec=0, retries=0)

            def fake_get(url: str) -> str:
                return article_html if url.endswith("M.old.html") else list_html

            crawler._get = fake_get  # type: ignore[method-assign]

            posts = crawler.crawl(max_pages=1, start_date="2026-06-02", end_date="2026-06-03")

            self.assertEqual(posts, [])
            self.assertNotIn("https://www.ptt.cc/bbs/CVS/M.old.html", crawler.seen_urls)


class CliTest(unittest.TestCase):
    def test_cli_rejects_negative_recent_days_without_traceback(self) -> None:
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "run.py", "--demo", "--recent-days", "-1"],
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must be non-negative", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_cli_rejects_negative_limit_without_traceback(self) -> None:
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "run.py", "--demo", "--limit", "-1"],
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must be non-negative", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_cli_rejects_negative_float_filters_without_traceback(self) -> None:
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "run.py", "--demo", "--min-score", "-1"],
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must be non-negative", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_cli_rejects_reversed_date_range_without_traceback(self) -> None:
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "run.py", "--demo", "--start-date", "2026-06-03", "--end-date", "2026-06-01"],
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("start_date must be earlier than or equal to end_date", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_cli_json_output_creates_parent_directory(self) -> None:
        import subprocess
        import sys
        from pathlib import Path
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "nested" / "reports.json"
            result = subprocess.run(
                [sys.executable, "run.py", "--demo", "--json", str(output_path)],
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(output_path.exists())


if __name__ == "__main__":
    unittest.main()
