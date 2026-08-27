from __future__ import annotations

import json
import itertools
import csv
import math
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
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
from cvs_radar.excerpt_labels import (
    ExcerptLabel,
    PROMPT_VERSION as CURRENT_EXCERPT_PROMPT_VERSION,
    excerpt_fingerprint,
    excerpt_fingerprint_v2,
    load_excerpt_labels,
)
from cvs_radar.comment_labels import (
    PROMPT_VERSION as COMMENT_PICKS_PROMPT_VERSION,
    CommentPicks,
    comment_picks_fingerprint,
    comment_picks_fingerprint_v2,
    load_comment_picks,
)
from cvs_radar.label_validation import Rewrite
from cvs_radar.product_labels import (
    load_product_name_labels,
    product_name_fingerprint,
    product_name_fingerprint_v2,
)
from cvs_radar.scoring import (
    _clean_extracted_product_name,
    _rep_candidates,
    _rep_comments,
    _body_candidates,
    _ReviewCandidate,
    _review_candidates,
    _review_excerpt,
    _review_sentences,
    _same_combo_flavor_product,
    _same_product,
    canonical_product_name,
    categorize_product,
    extract_products_and_prices,
    extract_products_and_prices_by_rules,
    group_products,
    normalize_product,
    preprocess_posts,
    representative_product_name,
    score_all,
    score_product,
)
from cvs_radar.sentiment import (
    LlmBackend,
    _normalize_override_text,
    annotate_posts,
    apply_sentiment_overrides,
    clamp,
    comment_fingerprint_v2,
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
            cached_urls = (
                json.loads(cache_path.read_text(encoding="utf-8"))
                if cache_path.exists()
                else []
            )
        return article_url, crawler, cached_urls, posts

    def test_crawl_marks_successfully_parsed_out_of_window_post_seen(self) -> None:
        post = Post(id="old", url="https://example.test/bbs/CVS/M.1.html", posted_at=datetime(2026, 6, 1, 12, 0))

        article_url, crawler, cached_urls, posts = self._crawl_one(post)

        self.assertEqual(posts, [])
        self.assertNotIn(article_url, crawler.seen_urls)
        self.assertIn(article_url, crawler.pending_seen_urls)
        self.assertNotIn(article_url, cached_urls)
        self.assertEqual(crawler.last_crawl_counts["date_excluded"], 1)

    def test_crawl_leaves_non_product_post_uncached_for_a_future_parse_retry(self) -> None:
        article_url, crawler, cached_urls, posts = self._crawl_one(None)

        self.assertEqual(posts, [])
        self.assertNotIn(article_url, crawler.seen_urls)
        self.assertNotIn(article_url, cached_urls)
        self.assertEqual(crawler.last_crawl_counts["non_product"], 1)

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
        self.assertNotIn(article_url, crawler.seen_urls)
        self.assertIn(article_url, crawler.pending_seen_urls)
        self.assertNotIn(article_url, cached_urls)


class CrawlJobSeenTransactionTest(unittest.TestCase):
    def test_seen_cache_is_committed_only_after_store_fsync_succeeds(self) -> None:
        from crawl_job import main

        crawler = Mock()
        crawler.crawl.return_value = [Post(id="new", url="https://example.test/M.new")]
        argv = ["crawl_job.py", "--skip-recompute", "--store", "/tmp/test-posts.jsonl"]

        with (
            patch("sys.argv", argv),
            patch("crawl_job.PttCrawler", return_value=crawler),
            patch("crawl_job.save_posts", side_effect=OSError("disk full")),
        ):
            with self.assertRaisesRegex(OSError, "disk full"):
                main()

        crawler.commit_seen.assert_not_called()

    def test_successful_store_commit_persists_pending_seen_urls(self) -> None:
        from crawl_job import main

        events: list[str] = []
        crawler = Mock()
        crawler.crawl.return_value = [Post(id="new", url="https://example.test/M.new")]
        crawler.commit_seen.side_effect = lambda: events.append("seen")
        argv = ["crawl_job.py", "--skip-recompute", "--store", "/tmp/test-posts.jsonl"]

        with (
            patch("sys.argv", argv),
            patch("crawl_job.PttCrawler", return_value=crawler),
            patch("crawl_job.save_posts", side_effect=lambda *_: events.append("store") or 1),
            patch(
                "crawl_job.store_stats",
                return_value={"post_count": 1, "comment_count": 0},
            ),
        ):
            main()

        self.assertEqual(events, ["store", "seen"])


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

    def test_product_grouping_is_permutation_stable_and_complete_link(self) -> None:
        posts = [
            Post(id="a", brand="其他", product_name="abcdefghij"),
            Post(id="b", brand="其他", product_name="abcdefghijklmno"),
            Post(id="bridge", brand="其他", product_name="abcdefghijkl"),
        ]
        memberships = []
        for permutation in itertools.permutations(posts):
            groups = group_products(list(permutation))
            memberships.append(
                sorted(sorted(post.id for post in members) for members in groups.values())
            )

        self.assertTrue(all(item == memberships[0] for item in memberships))
        self.assertEqual(memberships[0], [["a", "bridge"], ["b"]])

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

    def test_ambiguous_comment_not_shared_across_split_products(self) -> None:
        # review #21: in a multi-product post, a comment that names none of the
        # split products must be dropped, not copied into every product's bucket
        # (which polluted the others' fair score / consensus / excerpt). Comments
        # that DO distinctly match are still attributed to that one product.
        from cvs_radar.scoring import _route_comments_by_product

        names = ["草莓大福", "巧克力泡芙"]
        comments = [
            Comment("推", "a", "草莓大福好好吃"),
            Comment("推", "b", "巧克力泡芙超讚"),
            Comment("推", "c", "好吃推薦"),  # names neither -> must be dropped
        ]
        routed = _route_comments_by_product(comments, names)
        self.assertEqual([c.text for c in routed[0]], ["草莓大福好好吃"])
        self.assertEqual([c.text for c in routed[1]], ["巧克力泡芙超讚"])
        # the unattributable comment must land in NEITHER bucket
        self.assertNotIn("好吃推薦", [c.text for bucket in routed for c in bucket])
        # a comment about exactly one product carries no attribution tag, so its
        # existing sentiment label keeps answering to the same key
        self.assertEqual([c.attributed_product for c in routed[0]], [""])

    def test_comment_naming_both_products_goes_to_each_with_its_own_key(self) -> None:
        # "糰子不好吃 蕨餅還可以" holds an opposite verdict for each product, so
        # dropping it lost both, and one shared scalar could only ever be right
        # about one. Route it to each product tagged with that product, which is
        # what moves the sentiment key from (comment, post) to (comment, product).
        from cvs_radar.scoring import _route_comments_by_product

        names = ["抹茶紅豆串糰子", "和風蕨餅小盛"]
        comment = Comment("推", "a", "糰子不好吃 蕨餅還可以")
        routed = _route_comments_by_product([comment], names)

        self.assertEqual([c.text for c in routed[0]], ["糰子不好吃 蕨餅還可以"])
        self.assertEqual([c.text for c in routed[1]], ["糰子不好吃 蕨餅還可以"])
        self.assertEqual(routed[0][0].attributed_product, "抹茶紅豆串糰子")
        self.assertEqual(routed[1][0].attributed_product, "和風蕨餅小盛")

        post = Post(id="p1", brand="全家", product_name="抹茶紅豆串糰子", author="a1")
        post.source_product_name = "抹茶紅豆串糰子/和風蕨餅小盛"
        self.assertNotEqual(
            comment_fingerprint_v2(post, routed[0][0]),
            comment_fingerprint_v2(post, routed[1][0]),
        )

    def test_shared_comment_never_takes_a_text_keyed_score(self) -> None:
        # Legacy text labels and reviewed corrections are keyed on the comment
        # alone. Letting either answer for a comment that evaluates two products
        # would put one scalar on both — the pollution routing exists to prevent.
        # Without a per-product label the copy stays out of the score entirely.
        post = Post(id="p1", brand="全家", product_name="抹茶紅豆串糰子", author="a1")
        post.source_product_name = "抹茶紅豆串糰子/和風蕨餅小盛"
        post.comments = [
            Comment("推", "a", "糰子不好吃 蕨餅還可以", attributed_product="抹茶紅豆串糰子")
        ]
        post.comments[0].sentiment = 0.8  # whatever the rule backend guessed

        text_key = _normalize_override_text("糰子不好吃 蕨餅還可以")
        apply_sentiment_overrides(
            [post],
            overrides={text_key: 0.9},
            fingerprint_labels={},
            corrections={text_key: 0.9},
        )
        self.assertIsNone(post.comments[0].sentiment)
        self.assertEqual(post.comments[0].backend, "unattributed")

        # the per-product label, and only that, decides it
        apply_sentiment_overrides(
            [post],
            overrides={text_key: 0.9},
            fingerprint_labels={comment_fingerprint_v2(post, post.comments[0]): (-0.7, True)},
            corrections={text_key: 0.9},
        )
        self.assertEqual(post.comments[0].sentiment, -0.7)

    def test_shared_comment_counts_once_towards_its_author(self) -> None:
        # The copies routing makes are one act by one account. Counting each would
        # show the account posting identical text at the same minute, which is what
        # the template_like and burst suspicion features exist to punish — so the
        # author of a single multi-product comment would lose credibility for it.
        from cvs_radar.models import CommentOpinion
        from cvs_radar.preference import build_profiles

        text = "糰子不好吃 蕨餅還可以"
        posted = datetime(2026, 8, 24, 11, 6, tzinfo=timezone.utc)
        url = "https://example.test/M.shared"
        left = Post(id="p1_a", url=url, brand="全家", product_name="抹茶紅豆串糰子", author="x")
        right = Post(id="p1_b", url=url, brand="全家", product_name="和風蕨餅小盛", author="x")
        left.comments = [Comment("推", "u1", text, posted, attributed_product="抹茶紅豆串糰子")]
        right.comments = [Comment("推", "u1", text, posted, attributed_product="和風蕨餅小盛")]

        profiles = build_profiles(
            [left, right],
            {
                ("p1_a", 0): CommentOpinion(True, -0.6),
                ("p1_b", 0): CommentOpinion(True, 0.3),
            },
        )
        self.assertEqual(profiles["u1"].total_comments, 1)

    def test_variant_spelling_routes_to_the_product_it_names(self) -> None:
        # Half the commenters on 慢燉滷肉油蔥粄條 write 板條. The routing match is
        # exact on characters, so the variant matched nothing and every one of
        # those comments — most of them the "太油" complaints — was dropped, while
        # a comparison like 喜歡板條勝過意麵 matched only 意麵 and was counted as
        # praise for the product it ranks second.
        from cvs_radar.scoring import _route_comments_by_product

        names = ["慢燉滷肉油蔥粄條", "府城鹽水意麵"]
        comments = [
            Comment("推", "a", "板條好吃，但超油"),
            Comment("推", "b", "喜歡板條勝過意麵 肉燥味很香"),
        ]
        routed = _route_comments_by_product(comments, names)

        self.assertEqual([c.text for c in routed[0]], ["板條好吃，但超油", "喜歡板條勝過意麵 肉燥味很香"])
        self.assertEqual([c.text for c in routed[1]], ["喜歡板條勝過意麵 肉燥味很香"])
        # the plain 板條 comment is now this product's alone, no attribution tag
        self.assertEqual(routed[0][0].attributed_product, "")
        # the comparison names both, so each side gets its own labelled copy
        self.assertEqual(routed[0][1].attributed_product, "慢燉滷肉油蔥粄條")
        self.assertEqual(routed[1][0].attributed_product, "府城鹽水意麵")

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

    def test_capped_user_stance_respects_time_decay(self) -> None:
        # One user pushing 200 days ago and complaining today must not net out to
        # neutral: at lambda=0.005 the old push carries e^-1≈0.368 of the weight, so
        # the stance has to land near 0.27, not the 0.5 an unweighted mean produces.
        # Averaging the scores first is what silently switched the decay off.
        as_of = datetime(2026, 8, 1, tzinfo=timezone.utc)
        post = Post(
            id="p1",
            brand="7-11",
            product_name="測試飯糰",
            author="author",
            author_score=None,
            posted_at=as_of - timedelta(days=200),
            comments=[
                Comment("推", "u1", "好吃", sentiment=1.0,
                        posted_at=as_of - timedelta(days=200)),
                Comment("噓", "u1", "難吃", sentiment=-1.0, posted_at=as_of),
            ],
        )
        from cvs_radar.scoring.compute import _opinion_pairs

        pairs, contributors = _opinion_pairs([post], {}, as_of)
        self.assertEqual(len(pairs), 1)
        old_weight = math.exp(-0.005 * 200)
        expected = old_weight / (1.0 + old_weight)
        self.assertAlmostEqual(contributors[0].score, round(expected, 4), places=4)
        # The unweighted mean these two comments used to produce:
        self.assertNotAlmostEqual(contributors[0].score, 0.5, places=2)

    def test_one_author_posting_repeatedly_gets_one_vote(self) -> None:
        # per_user_cap is meant to stop one person outvoting a product, but it only
        # ever applied to commenters: ten reviews by one account carried ten full
        # votes and inflated n_eff with them, so a single enthusiast could hold a
        # product at a high score and high confidence on their own.
        as_of = datetime(2026, 8, 1, tzinfo=timezone.utc)
        posts = [
            Post(
                id=f"p{i}",
                brand="7-11",
                product_name="測試飯糰",
                author="fan",
                author_score=100,
                posted_at=as_of,
            )
            for i in range(10)
        ]
        posts.append(
            Post(
                id="p10",
                brand="7-11",
                product_name="測試飯糰",
                author="other",
                author_score=0,
                posted_at=as_of,
            )
        )
        reports, _ = run_pipeline(posts, now=as_of)
        report = reports[0]
        self.assertEqual(sorted(c.user for c in report.contributors), ["fan", "other"])
        self.assertAlmostEqual(report.n_eff, 2.0, places=2)
        # Two humans disagreeing completely sit at the prior, not near the fan's 100.
        self.assertAlmostEqual(report.fair_score, 50.0, places=1)

    def test_an_author_who_also_comments_is_still_one_person(self) -> None:
        # The same account reviewing one thread and pushing another about the same
        # product used to contribute an author vote and a commenter vote.
        as_of = datetime(2026, 8, 1, tzinfo=timezone.utc)
        posts = [
            Post(id="p1", brand="7-11", product_name="測試飯糰", author="fan",
                 author_score=100, posted_at=as_of),
            Post(id="p2", brand="7-11", product_name="測試飯糰", author="other",
                 author_score=None, posted_at=as_of,
                 comments=[Comment("推", "fan", "好吃", posted_at=as_of)]),
        ]
        reports, _ = run_pipeline(posts, now=as_of)
        self.assertEqual([c.user for c in reports[0].contributors], ["fan"])

    def test_scores_are_reproducible_from_an_explicit_as_of_time(self) -> None:
        # Reading the wall clock inside the decay means a rebuild of the same stored
        # snapshot drifts as time passes, so a published score cannot be reproduced.
        post = Post(
            id="p1",
            brand="7-11",
            product_name="測試飯糰",
            author="a1",
            author_score=100,
            posted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        early = datetime(2026, 1, 1, tzinfo=timezone.utc)
        later = early + timedelta(days=math.log(2) / 0.005)  # exactly one half-life

        first, _ = run_pipeline([post], now=early)
        again, _ = run_pipeline([post], now=early)
        aged, _ = run_pipeline([post], now=later)

        self.assertEqual(first[0].fair_score, again[0].fair_score)
        self.assertAlmostEqual(first[0].fair_score, 75.0, places=1)
        self.assertAlmostEqual(aged[0].fair_score, 66.7, places=1)

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

    def test_non_food_comment_without_lexicon_sentiment_reaches_model_pool(self) -> None:
        # 「可愛」 is a meaningful merchandise attribute, but it is absent from the
        # food sentiment lexicon. Candidate construction must not make that model
        # judgement in advance.
        post = Post(
            id="cute-merch",
            brand="7-11",
            product_name="飲料小夥伴吊飾",
            comments=[Comment("→", "u1", "可愛", sentiment=0.0)],
        )

        self.assertEqual(_rep_candidates([post]), ["可愛"])

    def test_model_pool_keeps_contentful_neutral_and_availability_comments(self) -> None:
        post = Post(
            id="mechanical-comment-pool",
            brand="全家",
            product_name="測試生活用品",
            comments=[
                Comment("→", "u1", "找不到", sentiment=None),
                Comment("→", "u2", "質感好", sentiment=0.0),
            ],
        )

        self.assertEqual(_rep_candidates([post]), ["找不到", "質感好"])

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
            "這款超好吃推薦",
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
    def test_contentless_praise_loses_to_a_sentence_with_substance(self) -> None:
        # 「超級好吃」對選購者沒有任何資訊；同一篇裡講份量與價格的句子才有用。
        post = Post(
            id="vacuous",
            review_text=(
                "我拍的不好看\n"
                "但是這個超級好吃\n"
                "而且冰淇淋好大一坨\n"
                "單價90塊我都會買"
            ),
        )

        excerpt = _review_excerpt([post])

        self.assertIn("好大一坨", excerpt)
        self.assertIn("90塊", excerpt)
        self.assertNotIn("超級好吃", excerpt)

    def test_verdict_without_a_described_aspect_still_counts_as_substance(self) -> None:
        # 「會回購」沒有口感/份量等面向，但那是明確的購買結論，不可被當成空泛稱讚丟掉。
        post = Post(id="verdict", review_text="看起來很讚\n整體耐吃，應該會再回購！")

        self.assertIn("回購", _review_excerpt([post]))

    def test_suppression_heuristics_never_blank_an_excerpt(self) -> None:
        # 跨品類過濾與「aspect 只出現在品名」的抑制都是啟發式：比較句（吃起來就是奶油
        # 餅乾）會被誤判成別的商品，而品名含「香」會讓每個「香」都被當成品名的一部分。
        # 兩者同時命中時不可把候選句清成零，否則商品的摘錄整個消失。
        comparison = Post(
            id="compare",
            product_name="這不是菠蘿麵包",
            review_text="跟扁可頌一樣的概念吧\n吃起來就是奶油餅乾\n有糖粒感 還蠻涮嘴的",
        )
        name_collision = Post(
            id="collide",
            product_name="椒香皮蛋香菜冷麵",
            review_text="只有香菜味是有的\n皮蛋我吃完再看才想到\n但是就完全跟預期的落差非常大",
        )

        for post in (comparison, name_collision):
            with self.subTest(product=post.product_name):
                self.assertTrue(_review_excerpt([post]).strip())

    def test_merchandise_review_still_gets_an_excerpt(self) -> None:
        # 周邊商品沒有味道口感可寫，只剩主觀評價；此時寧可用弱節錄也不要空白。
        post = Post(id="goods", review_text="免費送但質感做得很不錯")

        self.assertTrue(_review_excerpt([post]).strip())

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

    def test_uses_wrapped_product_description_not_product_name_or_promo(self) -> None:
        # Candidate export is intentionally broad; the provisional selector still
        # suppresses the promotion line before a model label exists.
        post = Post(
            id="fruit-bread",
            product_name="滿滿果乾切片軟歐",
            review_text=(
                "全家推出了兩款切 片軟歐 優惠券也超級搶手\n"
                "滿滿果乾切片軟歐\n"
                "果乾的確也是滿滿\n"
                "麵包本體吃起來也軟\n"
                "帶點彈牙\n"
                "但因為麵包本體份量大"
            ),
        )

        candidates = _review_candidates([post])
        excerpt = _review_excerpt([post])

        self.assertTrue(any("優惠券" in candidate.text for candidate in candidates))
        self.assertIn("果乾", excerpt)
        self.assertRegex(excerpt, r"軟|彈牙")
        self.assertIn("軟帶點彈牙", excerpt)
        self.assertNotIn("優惠券", excerpt)
        self.assertNotIn("超級搶手", excerpt)

    def test_prefers_target_product_review_over_other_product_in_thread(self) -> None:
        # 多商品串中，雪糕的句子不能因「鹹／一坨」等 aspect 詞污染涼麵節錄。
        post = Post(
            id="vinegar-noodles",
            product_name="嘉義崇文白醋涼麵",
            review_text=(
                "吃起來很清爽、醋味很解膩，跟一般涼麵比起來就是多了醋味。\n"
                "有網路說的超好吃嗎，其實也沒有，但是滿便宜清爽的解決一餐很不錯。\n"
                "這不是一支鹹甜口味的雪糕，是單純的鹹而已。\n"
                "最後可能是製程關係，末端會有一坨美乃滋。\n"
                "有49元想吃冰的話，請去買古娃娃的紅心芭樂雪糕。"
            ),
        )

        excerpt = _review_excerpt([post])

        self.assertTrue(excerpt.startswith("吃起來很清爽、醋味很解膩"))
        self.assertIn("清爽", excerpt)
        self.assertIn("解膩", excerpt)
        self.assertNotIn("雪糕", excerpt)
        self.assertNotIn("一坨", excerpt)

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
                self.assertEqual(extract_products_and_prices_by_rules(raw_name), expected)

    def test_extract_products_and_prices_template_garbage(self) -> None:
        results = extract_products_and_prices_by_rules("：\n(區域型商品請註明 試吃試用品請標示價格0元)")

        self.assertFalse(
            [
                (name, price)
                for name, price in results
                if name.strip() and price is not None
            ]
        )

    def test_extract_strips_promo_size_and_discount_tail_noise(self) -> None:
        # Posters append coupon / cup-size / friendly-time-discount markers and
        # stray prices to the 商品名稱 field; the report must key on the product
        # itself, otherwise the same item scatters across separate keys.
        cases = [
            # 全家 Fami 酷碰價 優惠券
            ("：四季檸檬酷繽球/酷碰價39元", "全家", [("四季檸檬酷繽球", 39)]),
            # 全家 友善時光 即期折扣尾巴：品名/原價 /折扣價時光
            ("： 核桃腰果稻禾壽司組/55 /38時光", "全家", [("核桃腰果稻禾壽司組", 55)]),
            # 酷碰券 優惠券 + 杯型
            ("：厚奶拿鐵/酷碰券特大杯59", "全家", [("厚奶拿鐵", 59)]),
        ]
        for raw_name, brand, expected in cases:
            with self.subTest(raw_name=raw_name):
                self.assertEqual(extract_products_and_prices_by_rules(raw_name, brand), expected)

    def test_extract_strips_retail_qualifier_families(self) -> None:
        # 商品名稱欄的通用形狀是「品名 + 分隔符 + 價格修飾詞 + 價格」。價格被抽走後
        # 修飾詞會黏在品名尾巴，讓同一商品散成多個 key。逐族各鎖一例。DEV-110。
        cases = [
            # 價格／折扣尾巴
            ("：鹽花生焦糖捲蛋糕/友善$34", "全家", ("鹽花生焦糖捲蛋糕", 34)),
            ("：楊枝甘露果C果昔 嚐鮮價$79", "萊爾富", ("楊枝甘露果C果昔", 79)),
            ("：白蘭氏養蔘元氣凍/折價後$49", "全家", ("白蘭氏養蔘元氣凍", 49)),
            # 價格黏在修飾詞前面時要回收成 price
            ("：法朋蛋黃酥霜淇淋  49 第二隻10元", "7-11", ("法朋蛋黃酥霜淇淋", 49)),
            # 贈品／門檻尾巴
            ("：褲褲兔中秋款光柵扇/消費滿200免費送", "全家", ("褲褲兔中秋款光柵扇", None)),
            ("：炙燒燒肉拌麵89元+5元送可樂", "全家", ("炙燒燒肉拌麵", 89)),
            ("：明治指定巧克力兩件8折送手機掛繩", "7-11", ("明治指定巧克力", None)),
            # 價格不確定／結帳敘述（斜線後整段不含數字）
            ("：廣達香肉鬆飯糰/ 一起結帳不確定價格", "OK", ("廣達香肉鬆飯糰", None)),
            ("：光泉優質蛋白牛奶/一起結帳忘記了", "OK", ("光泉優質蛋白牛奶", None)),
            # 供應／模板標籤殘留
            # 名稱是重點；此路徑的價格目前救不回來（已知小缺口，不影響分組 key）
            ("：五窨茉莉茶后 40元限店", "全家", ("五窨茉莉茶后", None)),
            ("：世界的山將 - 夢幻唐揚雞 / 單價59", "7-11", ("世界的山將夢幻唐揚雞", 59)),
            # 折扣乘數與小數價格
            ("：燻雞起司米披薩卷/79X0.7", "7-11", ("燻雞起司米披薩卷", 79)),
            ("：雪淋霜-甜鹽蜜語牛奶/24.5元", "7-11", ("雪淋霜甜鹽蜜語牛奶", 24)),
        ]
        for raw_name, brand, expected in cases:
            with self.subTest(raw_name=raw_name):
                self.assertEqual(extract_products_and_prices_by_rules(raw_name, brand), [expected])

    def test_qualifier_rules_do_not_damage_real_names(self) -> None:
        # 這些真品名含有與促銷詞同形的字，規則只在尾端＋分隔符/價格後生效，不得誤傷。
        safe = [
            # 「送」在品名中間，不是贈品條款
            ("：牧場直送生食鮮蛋/150元", "全家", ("牧場直送生食鮮蛋", 150)),
            # 品名內的小數不接「元」，不可被當價格而拆成兩個商品
            ("：牧場直送4.0花生牛奶雪糕/45元", "全家", ("牧場直送4.0花生牛奶雪糕", 45)),
            ("：開運黑糖發糕/59元", "7-11", ("開運黑糖發糕", 59)),
            ("：光泉午后時光紅茶39", "全家", ("光泉午后時光紅茶", 39)),
        ]
        for raw_name, brand, expected in safe:
            with self.subTest(raw_name=raw_name):
                self.assertEqual(extract_products_and_prices_by_rules(raw_name, brand), [expected])

    def test_combo_bundle_keeps_only_first_product(self) -> None:
        # "A3入+B3入/75元" 是併購組合，第二項是比較對象；報告只以第一個商品為
        # key，而非把兩個品名黏成「翻轉布丁統一布丁」。
        self.assertEqual(
            extract_products_and_prices_by_rules("：翻轉布丁3入+統一布丁3入/75元", "7-11"),
            [("翻轉布丁", 75)],
        )

    def test_combo_guard_does_not_split_flavour_swirl(self) -> None:
        # 沒有「兩側都帶數量」的 '+'（如霜淇淋雙口味）不可被截半，避免誤把
        # 完整品名砍成前半段。
        self.assertEqual(
            extract_products_and_prices_by_rules("巧克力+香草霜淇淋/59", "7-11"),
            [("巧克力香草霜淇淋", 59)],
        )

    def test_friendly_time_mark_stripped_but_real_name_preserved(self) -> None:
        # 「友善時光」整組剝除；但含「時光」的真實品名（午后時光）不可被誤傷。
        self.assertEqual(
            extract_products_and_prices_by_rules("度小月擔仔炊粉湯 友善時光 56", "全家"),
            [("度小月擔仔炊粉湯", 56)],
        )
        self.assertEqual(
            [n for n, _ in extract_products_and_prices_by_rules("光泉午后時光紅茶39", "全家")],
            ["光泉午后時光紅茶"],
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

        result = extract_products_and_prices_by_rules(raw_name, "萊爾富")

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
        # 「99 目前會員特價88」要記實付的 88：站上的價格是給人參考要花多少錢買，
        # 不是原價牌價。標籤流程也是照這個規則判的。
        self.assertEqual(processed[0].price, "88")
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

        # 欄位只有價格時，品名必須改由標題提供，否則商品會以「599預購加點數」入庫。
        self.assertEqual(len(processed), 1)
        self.assertIn("動物方城市安全帽", processed[0].product_name)
        self.assertEqual(processed[0].price, "599")
        self.assertEqual(categorize_product(processed[0].product_name), "周邊")

    def test_decimal_point_survives_in_the_name_but_not_in_the_merge_key(self) -> None:
        # 「牧場直送4.0」的 4.0 是品名的一部分，剝掉會變成看起來像容量的「40」。
        # 過去是靠 product_overrides 逐項把點補回去。
        self.assertEqual(
            canonical_product_name("全家", "牧場直送4.0玉米牛奶雪糕"),
            "牧場直送4.0玉米牛奶雪糕",
        )
        self.assertEqual(canonical_product_name("7-11", "可樂2.5公升"), "可樂2.5公升")
        # 合併用的 key 反過來要吃掉小數點：發文者兩種寫法都有，同一個商品不能因為
        # 有人漏打點就被拆成兩項。顯示要保真、合併要粗暴，兩者刻意不同。
        self.assertEqual(
            normalize_product("全家", "牧場直送4.0玉米牛奶雪糕"),
            normalize_product("全家", "牧場直送40玉米牛奶雪糕"),
        )
        # 品名裡本來就沒有點的數字不受影響。
        self.assertEqual(canonical_product_name("萊爾富", "77乳加星球含餡巧克力"), "77乳加星球含餡巧克力")

    def test_an_ascii_brand_alias_is_not_carved_out_of_a_longer_word(self) -> None:
        # 全家的別名含 "fami"，一旦用無字界的比對就會把 FAMIMA 咬成 MA，
        # 線上因此出現過「MA托特包」。品牌只有在自己成詞時才算品牌。
        self.assertEqual(
            canonical_product_name("全家", "FAMIMA托特包一太陽星星"),
            "FAMIMA托特包一太陽星星",
        )
        # 同一條規則對 OK 更要緊：cookie 裡的 ok 不是超商。
        self.assertEqual(canonical_product_name("OK", "cookie餅乾"), "cookie餅乾")
        # 但品牌真的獨立成詞時仍要拔掉，否則整批品名都會多出前綴。
        self.assertEqual(canonical_product_name("全家", "全家 草莓大福"), "草莓大福")
        self.assertEqual(canonical_product_name("OK", "ok便利商店 廣達香肉鬆飯糰"), "便利商店廣達香肉鬆飯糰")

    def test_the_famice_sub_brand_is_stripped_whole_not_halfway(self) -> None:
        # Fami!ce 是全家自有霜淇淋品牌。字界規則會放行 fami（後面是驚嘆號），
        # 只拔掉前半就會讓 !ce 黏在品名開頭——線上出現過「ce霜淇淋」。
        # 解法是讓完整的 Fami!ce 先被當成品牌比對掉。
        self.assertEqual(
            canonical_product_name("全家", "全家Fami!ce霜淇淋 伊藤園抹茶x焦糖蘇打"),
            "霜淇淋伊藤園抹茶x焦糖蘇打",
        )
        # 併回既有商品才是重點：拔一半會讓同一支霜淇淋被拆成兩項。
        self.assertEqual(
            canonical_product_name("全家", "Fami!ce 滑爆可樂霜淇淋 買一送一"),
            canonical_product_name("全家", "滑爆可樂霜淇淋"),
        )

    def test_bracketed_qualifier_survives_but_a_bracketed_promo_does_not(self) -> None:
        # 括號裡的變體標記是識別商品的一部分：整組剝掉會讓無糖與有糖、中杯與大杯
        # 收斂成同一項商品。
        for brand, name, expected in (
            ("7-11", "純喫茶金萱青茶(無糖)", "純喫茶金萱青茶無糖"),
            ("7-11", "拿坡里風味肉球義大利麵(含牛肉)", "拿坡里風味肉球義大利麵含牛肉"),
            ("7-11", "(晶華)富貴海皇羹", "晶華富貴海皇羹"),
            ("7-11", "單品拿鐵(中)", "單品拿鐵中"),
        ):
            with self.subTest(name=name):
                self.assertEqual(canonical_product_name(brand, name), expected)
        # 括號裡的促銷／價格附註仍要連內容剝掉。
        for brand, name, expected in (
            ("全家", "芋泥Q皮半月燒(友善35)", "芋泥Q皮半月燒"),
            ("7-11", "Rody摺疊置物箱(原價$399)", "Rody摺疊置物箱"),
            ("全家", "抹茶蒙布朗布丁(活動期間八折 52 元)", "抹茶蒙布朗布丁"),
        ):
            with self.subTest(name=name):
                self.assertEqual(canonical_product_name(brand, name), expected)
        # 有寫括號和沒寫括號是同一個商品，合併 key 必須一致。
        self.assertEqual(
            normalize_product("7-11", "純喫茶金萱青茶(無糖)"),
            normalize_product("7-11", "純喫茶金萱青茶無糖"),
        )

    def test_percent_is_kept_in_a_name_but_dropped_from_a_discount(self) -> None:
        # 54% 是可可含量，屬於品名；後面還接著品名文字。
        self.assertEqual(
            canonical_product_name("全家", "GODIVA 54%黑巧克力夏威夷果仁脆粒雪糕"),
            "GODIVA54%黑巧克力夏威夷果仁脆粒雪糕",
        )
        # 位在字尾的百分比是折扣，不是商品的一部分。
        self.assertNotIn("%", _clean_extracted_product_name("台式海陸炒麵 89元 刷卡再折5%", "萊爾富"))
        self.assertNotIn("%", _clean_extracted_product_name("50 x 65%", "7-11"))
        # 合併 key 照樣吃掉 %，讓有寫和沒寫的兩種拼法算同一個商品。
        self.assertEqual(
            normalize_product("全家", "GODIVA 54%黑巧克力夏威夷果仁脆粒雪糕"),
            normalize_product("全家", "GODIVA54黑巧克力夏威夷果仁脆粒雪糕"),
        )

    def test_acquisition_condition_field_falls_back_to_title_name_without_price(self) -> None:
        post = Post(
            id="M.1785371973.A.101",
            title="[商品] 全家超級瑪利歐矽膠杯墊",
            brand="全家",
            product_name="：買六件20元以上冰品飲料免費送",
            price="：買六件20元以上冰品飲料免費送",
        )

        processed = preprocess_posts([post])

        # 欄位寫的是「怎麼拿到」而不是「這是什麼」，品名要改由標題提供，
        # 否則首頁會出現一項叫「買六件以上冰品飲料免費送」的商品。
        self.assertEqual(len(processed), 1)
        self.assertEqual(processed[0].product_name, "超級瑪利歐矽膠杯墊")
        # 20 是「買六件20元以上」的門檻，不是杯墊的售價；杯墊是贈品，不該有價格。
        # score_product 只採計純數字的 price 欄位（compute.py），所以「沒有被換成
        # 數字」就等於商品頁不顯示價格。
        self.assertFalse(processed[0].price.isdigit())
        self.assertNotEqual(processed[0].price, "20")

    def test_promo_tail_after_a_real_name_keeps_the_name(self) -> None:
        post = Post(
            id="M.1785371974.A.102",
            title="[商品] 全家 香草布丁",
            brand="全家",
            product_name="：香草布丁 39 買一送一",
            price="：香草布丁 39 買一送一",
        )

        processed = preprocess_posts([post])

        # 「買一送一」單獨出現只是接在真品名後的促銷尾巴，不能讓整個品名作廢。
        self.assertEqual(len(processed), 1)
        self.assertEqual(processed[0].product_name, "香草布丁")

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
            # Cookware redeemed with stamps is merchandise; a hotpot dish is a meal.
            # Both contain 鍋, so the specific cookware term has to outrank it.
            ("導磁不沾鍋", "周邊"),
            ("暖心麻油雞鍋", "便當"),
            ("韓式部隊鍋", "便當"),
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

    def test_crawl_marks_successfully_parsed_filtered_out_articles_as_seen(self) -> None:
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
            self.assertIn(
                "https://www.ptt.cc/bbs/CVS/M.old.html", crawler.pending_seen_urls
            )


class CliTest(unittest.TestCase):
    def test_cli_rejects_date_filters_with_precomputed_results(self) -> None:
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "run.py", "--results", "--recent-days", "7"],
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("precomputed results cannot be re-filtered by date", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

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


class ProductNameLabelCacheTest(unittest.TestCase):
    """The LLM decides a raw field's product once; the cache keeps it reproducible."""

    def _write(self, rows: str) -> str:
        path = os.path.join(tempfile.mkdtemp(), "product_name_labels.csv")
        with open(path, "w", encoding="utf-8", newline="") as handle:
            handle.write(
                "fingerprint,item_index,brand,title,raw_name,product_name,price,model,prompt_version\n"
                + rows
            )
        return path

    def test_label_wins_over_the_rule_fallback(self) -> None:
        raw = "：廣達香肉鬆飯糰/ 一起結帳不確定價格"
        title = "[商品] OK 廣達香肉鬆飯糰"
        digest = product_name_fingerprint("OK", title, raw)
        path = self._write(
            f"{digest},0,OK,{title},{raw},廣達香肉鬆飯糰,45,codex,product-name-v1\n"
        )

        self.assertEqual(
            load_product_name_labels(path)[digest], [("廣達香肉鬆飯糰", 45)]
        )

    def test_multi_product_rows_keep_their_order(self) -> None:
        digest = product_name_fingerprint("7-11", "[商品] 7-11 抹茶", "A/55 B/59")
        path = self._write(
            f"{digest},1,7-11,[商品] 7-11 抹茶,A/55 B/59,抹茶千層,59,codex,product-name-v1\n"
            f"{digest},0,7-11,[商品] 7-11 抹茶,A/55 B/59,抹茶霜淇淋,55,codex,product-name-v1\n"
        )

        self.assertEqual(
            load_product_name_labels(path)[digest],
            [("抹茶霜淇淋", 55), ("抹茶千層", 59)],
        )

    def test_blank_name_records_an_empty_item_list_not_a_cache_miss(self) -> None:
        # A field carrying only a price ("55元 甜點兩件六九折") has no usable name.
        # That verdict must be remembered, otherwise every rebuild re-runs the rules
        # on it and the caller cannot tell "labelled as unusable" from "not labelled".
        digest = product_name_fingerprint("全家", "[商品] 全家 甜點", "55元 甜點兩件六九折")
        path = self._write(
            f"{digest},0,全家,[商品] 全家 甜點,55元 甜點兩件六九折,,,codex,product-name-v1\n"
        )

        labels = load_product_name_labels(path)

        self.assertIn(digest, labels)
        self.assertEqual(labels[digest], [])

    def test_fingerprint_ignores_incidental_whitespace_and_leading_colon(self) -> None:
        title = "[商品] OK 廣達香肉鬆飯糰"
        self.assertEqual(
            product_name_fingerprint("OK", title, "：廣達香肉鬆飯糰/ 一起結帳不確定價格"),
            product_name_fingerprint("OK", title, "： 廣達香肉鬆飯糰/  一起結帳不確定價格 "),
        )
        self.assertNotEqual(
            product_name_fingerprint("OK", title, "廣達香肉鬆飯糰"),
            product_name_fingerprint("全家", title, "廣達香肉鬆飯糰"),
        )

    def test_same_junk_field_under_different_titles_does_not_collide(self) -> None:
        # A poster who leaves 商品名稱 as bare noise ("：49") makes every such post
        # hash identically unless the title is in the key, and one label then
        # overwrites the rest — which merged four unrelated 7-11 products into one.
        self.assertNotEqual(
            product_name_fingerprint("7-11", "[商品] 711 飛燕煉乳炸銀絲卷", "：49"),
            product_name_fingerprint("7-11", "[商品] 711 這不是滷肉飯", "：49"),
        )

    def test_rule_guess_and_prompt_version_are_part_of_the_current_key(self) -> None:
        # The exported row shows the labeller the rule engine's guess, so changing
        # the rules changes the question. Leaving the guess out of the key keeps an
        # answer that was given about a different guess.
        base = ("7-11", "[商品] 7-11 炸銀絲卷", "：49")
        digest = product_name_fingerprint_v2(*base, rule_guess="炸銀絲卷#49")
        self.assertNotEqual(
            product_name_fingerprint_v2(*base, rule_guess="飛燕煉乳炸銀絲卷#49"), digest
        )
        self.assertNotEqual(
            product_name_fingerprint_v2(*base, rule_guess="炸銀絲卷#49", prompt_version="v2"),
            digest,
        )

    def test_labels_stored_under_the_legacy_key_still_apply(self) -> None:
        # Adding the rule guess to the key must not strand the 868 labels already
        # collected, which would silently drop extraction back to the rule engine.
        brand, title, raw = "全家", "[商品] 全家 甜點", "：韓式草莓大福"
        legacy = product_name_fingerprint(brand, title, raw)
        with patch(
            "cvs_radar.scoring.identity._cached_product_name_labels",
            return_value={legacy: [("韓式草莓大福", 55)]},
        ):
            self.assertEqual(
                extract_products_and_prices(raw, brand, title), [("韓式草莓大福", 55)]
            )

    def test_missing_cache_file_is_not_an_error(self) -> None:
        self.assertEqual(load_product_name_labels("data/labels/does-not-exist.csv"), {})


class ExcerptLabelCacheTest(unittest.TestCase):
    """The LLM picks a product's sentences once; the cache keeps it reproducible."""

    def _write(self, rows: str) -> str:
        path = os.path.join(tempfile.mkdtemp(), "excerpt_labels.csv")
        with open(path, "w", encoding="utf-8", newline="") as handle:
            handle.write(
                "fingerprint,post_id,brand,product_name,source_indices,rewrite,model,prompt_version\n"
                + rows
            )
        return path

    def test_fingerprint_covers_the_review_text(self) -> None:
        # A backfill that finally recovers a post body must invalidate a label that
        # was chosen when the body was empty, instead of keeping a stale excerpt.
        empty = excerpt_fingerprint("M.1", "紫薯QQ球", "")
        filled = excerpt_fingerprint("M.1", "紫薯QQ球", "外皮很紮實的Q")
        self.assertNotEqual(empty, filled)

    def test_same_post_different_products_get_different_labels(self) -> None:
        # The whole point of labelling per (post, product): one thread, two products,
        # two different excerpts.
        review = "涼麵吃起來很清爽。雪糕則是單純的鹹。"
        self.assertNotEqual(
            excerpt_fingerprint("M.2", "白醋涼麵", review),
            excerpt_fingerprint("M.2", "鹹雪糕", review),
        )

    def test_blank_excerpt_is_stored_as_a_verdict(self) -> None:
        candidates = ["只是買來抽獎"]
        digest = excerpt_fingerprint_v2(
            "M.3", "福袋", "只是買來抽獎", brand="全家", candidate_sentences=candidates
        )
        path = self._write(
            f"{digest},M.3,全家,福袋,,,codex,{CURRENT_EXCERPT_PROMPT_VERSION}\n"
        )

        labels = load_excerpt_labels(path)

        self.assertIn(digest, labels)
        self.assertEqual(labels[digest], ExcerptLabel((), ""))

    def test_partial_excerpt_cache_stays_provisional_until_all_posts_are_labelled(self) -> None:
        from cvs_radar.scoring import excerpt as excerpt_module

        first = Post(id="M.1", product_name="草莓蛋糕", review_text="奶油很輕盈。")
        second = Post(id="M.2", product_name="草莓蛋糕", review_text="蛋糕偏甜。")
        first_candidates = _body_candidates([first])
        first_key = excerpt_fingerprint_v2(
            first.id,
            first.product_name,
            first.review_text,
            candidate_sentences=first_candidates,
        )
        with patch.object(
            excerpt_module,
            "load_excerpt_labels",
            return_value={first_key: ExcerptLabel((0,), "奶油輕盈")},
        ):
            excerpt_module._cached_excerpt_labels.cache_clear()
            self.assertTrue(
                excerpt_module._review_excerpt_with_provenance([first, second])[1]
            )
        excerpt_module._cached_excerpt_labels.cache_clear()

    def test_sibling_products_are_part_of_the_current_key(self) -> None:
        # Every split item keeps the whole review_text, so the sibling list is the
        # only thing keeping a thread-mate's sentences out of this excerpt. If
        # re-parsing changes that list, the old answer was chosen while excluding
        # something else and must not be reused.
        review = "涼麵吃起來很清爽。雪糕則是單純的鹹。"
        digest = excerpt_fingerprint_v2(
            "M.2", "白醋涼麵", review, brand="全家", other_products="鹹雪糕"
        )
        self.assertNotEqual(
            excerpt_fingerprint_v2(
                "M.2", "白醋涼麵", review, brand="全家", other_products="鹹雪糕 | 芋泥球"
            ),
            digest,
        )
        self.assertNotEqual(
            excerpt_fingerprint_v2(
                "M.2", "白醋涼麵", review, brand="全家", other_products="鹹雪糕",
                candidate_sentences=("涼麵吃起來很清爽。",),
            ),
            excerpt_fingerprint_v2(
                "M.2", "白醋涼麵", review, brand="全家", other_products="鹹雪糕",
                candidate_sentences=("雪糕則是單純的鹹。",),
            ),
        )
        self.assertNotEqual(
            excerpt_fingerprint_v2(
                "M.2", "白醋涼麵", review, brand="7-11", other_products="鹹雪糕"
            ),
            digest,
        )
        self.assertNotEqual(
            excerpt_fingerprint_v2(
                "M.2", "白醋涼麵", review, brand="全家", other_products="鹹雪糕",
                prompt_version="excerpt-v2",
            ),
            digest,
        )

    def test_missing_cache_file_is_not_an_error(self) -> None:
        self.assertEqual(load_excerpt_labels("data/labels/does-not-exist.csv"), {})


class SiblingProductTest(unittest.TestCase):
    """Splitting a thread must record which products the split items share it with."""

    def test_split_items_know_their_thread_mates(self) -> None:
        # Anything that picks sentences out of the shared review_text needs this to
        # exclude the other product's sentences, and any label keyed on that choice
        # has to change when the list changes.
        post = Post(
            id="p1",
            brand="全家",
            title="[商品] 全家 白醋涼麵/鹹雪糕",
            product_name="白醋涼麵55/鹹雪糕45",
            author="a1",
            author_score=80,
            review_text="涼麵吃起來很清爽。雪糕則是單純的鹹。",
        )
        items = preprocess_posts([post])
        self.assertGreater(len(items), 1)
        for item in items:
            others = {other.product_name for other in items if other is not item}
            self.assertEqual(set(item.sibling_products), others)
            self.assertNotIn(item.product_name, item.sibling_products)

    def test_single_product_post_has_no_thread_mates(self) -> None:
        post = Post(id="p1", brand="7-11", product_name="測試飯糰", author="a1", author_score=80)
        self.assertEqual(preprocess_posts([post])[0].sibling_products, ())


class CommentPickCacheTest(unittest.TestCase):
    """The LLM picks concrete comments once; the cache keeps that choice reproducible."""

    def _with_picks(
        self,
        picks: dict[str, CommentPicks],
    ):
        from cvs_radar.scoring import excerpt as excerpt_module

        excerpt_module._cached_comment_picks.cache_clear()
        return patch("cvs_radar.scoring.excerpt.load_comment_picks", return_value=picks)

    def _post(self, *, review_text: str = "") -> Post:
        return Post(
            id="comment-picks",
            brand="7-11",
            product_name="草莓蛋糕",
            review_text=review_text,
            comments=[
                Comment("推", "one", "第一則具體好評", sentiment=0.9),
                Comment("推", "two", "第二則具體好評", sentiment=0.8),
                Comment("推", "three", "第三則具體好評", sentiment=0.7),
                Comment("噓", "four", "第一則具體負評", sentiment=-0.9),
            ],
        )

    def test_labelled_product_uses_picked_indices_in_given_order(self) -> None:
        post = self._post()
        comments = _rep_candidates([post])
        body = _body_candidates([post])
        digest = comment_picks_fingerprint_v2(post.brand, post.product_name, comments, body)

        with self._with_picks(
            {
                digest: CommentPicks(
                    (Rewrite(2, "第三則巧克力內餡好評"), Rewrite(0, "第一則草莓奶油好評")),
                    (Rewrite(3, "第一則奶油太膩負評"),),
                    (),
                    (),
                )
            }
        ):
            rep_positive, rep_negative = _rep_comments([post])

        self.assertEqual(rep_positive, ["第三則巧克力內餡好評", "第一則草莓奶油好評"])
        self.assertEqual(rep_negative, ["第一則奶油太膩負評"])

    def test_out_of_range_pick_is_rejected_by_the_cache_importer(self) -> None:
        from scripts.import_comment_picks import import_picks

        fields = (
            "fingerprint",
            "brand",
            "product_name",
            "other_products",
            "comments",
            "body_candidates",
            "positive_rewrites",
            "negative_rewrites",
            "positive_body_rewrites",
            "negative_body_rewrites",
            "model",
            "prompt_version",
        )
        comments = ["第一則", "第二則"]
        body: list[str] = []
        row = {
            "fingerprint": comment_picks_fingerprint_v2(
                "7-11", "草莓蛋糕", comments, body
            ),
            "brand": "7-11",
            "product_name": "草莓蛋糕",
            "other_products": "",
            "comments": "0. 第一則\n1. 第二則",
            "body_candidates": "",
            "positive_rewrites": '[{"source_index":99,"text":"第一則"}]',
            "negative_rewrites": "",
            "positive_body_rewrites": "",
            "negative_body_rewrites": "",
            "model": "codex",
            "prompt_version": COMMENT_PICKS_PROMPT_VERSION,
        }
        with TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.csv"
            labeled = Path(tmp) / "labeled.csv"
            cache = Path(tmp) / "cache.csv"
            for path in (source, labeled):
                with path.open("w", encoding="utf-8-sig", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=fields)
                    writer.writeheader()
                    writer.writerow(dict(row, positive_rewrites="") if path == source else row)

            with self.assertRaisesRegex(ValueError, "outside candidate pool"):
                import_picks(labeled, source, cache)
            self.assertFalse(cache.exists())

    def test_unlabelled_product_falls_back_to_top_ranked_comments(self) -> None:
        post = self._post()

        with self._with_picks({}):
            rep_positive, rep_negative = _rep_comments([post], k=2)

        self.assertEqual(rep_positive, ["第一則具體好評", "第二則具體好評"])
        self.assertEqual(rep_negative, ["第一則具體負評"])

    def test_labelled_empty_polarity_without_body_pick_does_not_use_rule_fallback(self) -> None:
        post = self._post(review_text="外皮很脆而且好吃。價格太貴而且很難吃。")
        comments = _rep_candidates([post])
        body = _body_candidates([post])
        digest = comment_picks_fingerprint_v2(post.brand, post.product_name, comments, body)

        with self._with_picks({digest: CommentPicks((), (), (), ())}):
            rep_positive, rep_negative = _rep_comments([post])

        self.assertEqual(rep_positive, [])
        self.assertEqual(rep_negative, [])

    def test_body_picks_fill_a_polarity_left_empty_by_comment_picks(self) -> None:
        post = self._post(
            review_text=(
                "口感滑順又很好吃。\n"
                "外皮很脆而且好吃。\n"
                "價格太貴而且很難吃。"
            )
        )
        comments = _rep_candidates([post])
        body = _body_candidates([post])
        digest = comment_picks_fingerprint_v2(post.brand, post.product_name, comments, body)

        with self._with_picks(
            {
                digest: CommentPicks(
                    (),
                    (),
                    (Rewrite(1, "外皮偏脆"),),
                    (Rewrite(2, "價格偏貴且難吃"),),
                )
            }
        ):
            rep_positive, rep_negative = _rep_comments(
                [post], excerpt="口感滑順又很好吃。"
            )

        self.assertEqual(rep_positive, ["外皮偏脆"])
        self.assertEqual(rep_negative, ["價格偏貴且難吃"])
        self.assertNotIn("口感滑順又很好吃", " ".join(rep_positive + rep_negative))

    def test_unlabelled_product_still_uses_body_highlights_rule_fallback(self) -> None:
        post = self._post(review_text="外皮很脆而且好吃。價格太貴而且很難吃。")

        with self._with_picks({}):
            rep_positive, rep_negative = _rep_comments([post])

        self.assertEqual(rep_positive, ["第一則具體好評", "第二則具體好評", "第三則具體好評"])
        self.assertEqual(rep_negative, ["第一則具體負評"])

        post.comments = []
        with self._with_picks({}):
            rep_positive, rep_negative = _rep_comments([post])

        self.assertEqual(rep_positive, ["外皮很脆而且好吃。"])
        self.assertEqual(rep_negative, ["價格太貴而且很難吃。"])

    def test_body_candidates_keep_contentless_category_neutral_sentences_for_model(self) -> None:
        from cvs_radar.scoring import excerpt as excerpt_module

        first = _ReviewCandidate("第一句口感很好", 1.0, frozenset({"texture"}), 0, 1)
        second = _ReviewCandidate("第二句價格太高", 99.0, frozenset({"price"}), 0, 2)
        earlier = _ReviewCandidate("更早一句奶味濃", 50.0, frozenset({"taste"}), 0, 0)
        no_aspect = _ReviewCandidate("不應列入", 100.0, frozenset(), 1, 0)

        with patch.object(excerpt_module, "_review_candidates", return_value=[first, second, earlier, no_aspect]):
            self.assertEqual(
                _body_candidates([self._post()]),
                ["更早一句奶味濃。", "第一句口感很好。", "第二句價格太高。", "不應列入。"],
            )

    def test_fingerprint_changes_when_candidate_pool_changes(self) -> None:
        original = comment_picks_fingerprint(
            "7-11", "草莓蛋糕", ["外皮很脆"], ["奶味濃"]
        )
        changed = comment_picks_fingerprint(
            "7-11", "草莓蛋糕", ["外皮很脆"], ["奶味濃", "口感滑順"]
        )

        self.assertNotEqual(original, changed)

    def test_thread_mates_are_part_of_the_current_key(self) -> None:
        args = ("7-11", "草莓蛋糕", ["外皮很脆"], ["奶味濃"])
        digest = comment_picks_fingerprint_v2(*args, other_products="巧克力可頌")
        self.assertNotEqual(
            comment_picks_fingerprint_v2(*args, other_products="巧克力可頌 | 芋泥球"), digest
        )
        self.assertNotEqual(
            comment_picks_fingerprint_v2(
                *args, other_products="巧克力可頌", prompt_version="comment-picks-v3"
            ),
            digest,
        )

    def test_blank_cells_are_kept_as_a_verdict(self) -> None:
        digest = comment_picks_fingerprint("7-11", "草莓蛋糕", ["外皮很脆"], [])
        path = os.path.join(tempfile.mkdtemp(), "comment_picks.csv")
        with open(path, "w", encoding="utf-8", newline="") as handle:
            handle.write(
                "fingerprint,brand,product_name,positive_rewrites,negative_rewrites,positive_body_rewrites,negative_body_rewrites,model,prompt_version\n"
                f"{digest},7-11,草莓蛋糕,,,,,codex,{COMMENT_PICKS_PROMPT_VERSION}\n"
            )

        self.assertEqual(load_comment_picks(path)[digest], CommentPicks((), (), (), ()))
