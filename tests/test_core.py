from __future__ import annotations

import json
import unittest

from cvs_radar.models import Comment, Post
from cvs_radar.parser import parse_ptt_article, parse_push_datetime, parse_score
from cvs_radar.pipeline import run_pipeline
from cvs_radar.reporting import render_json
from cvs_radar.scoring import normalize_product
from cvs_radar.sentiment import score_comment


class ParserTest(unittest.TestCase):
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

    def test_parse_push_datetime_uses_article_year_and_rollover(self) -> None:
        from datetime import datetime

        same_year = parse_push_datetime("05/02 12:30", reference=datetime(2025, 5, 1, 10, 0))
        rollover = parse_push_datetime("01/01 00:05", reference=datetime(2025, 12, 31, 23, 50))
        previous_year = parse_push_datetime("12/31 23:55", reference=datetime(2026, 1, 1, 0, 5))

        self.assertEqual(same_year, datetime(2025, 5, 2, 12, 30))
        self.assertEqual(rollover, datetime(2026, 1, 1, 0, 5))
        self.assertEqual(previous_year, datetime(2025, 12, 31, 23, 55))

    def test_parse_push_datetime_accepts_leap_day_with_reference_year(self) -> None:
        from datetime import datetime

        parsed = parse_push_datetime("02/29 08:15", reference=datetime(2024, 2, 29, 8, 0))

        self.assertEqual(parsed, datetime(2024, 2, 29, 8, 15))


class ScoringTest(unittest.TestCase):
    def test_product_normalization_removes_brand(self) -> None:
        self.assertEqual(normalize_product("7-11", "711  測試飯糰"), "測試飯糰")

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


class SentimentTest(unittest.TestCase):
    def test_tag_and_lexicon_mix(self) -> None:
        self.assertGreater(score_comment("推", "好吃會回購"), 0)
        self.assertLess(score_comment("噓", "難吃踩雷"), 0)
        self.assertEqual(score_comment("→", ""), 0)


class TimeAndServiceTest(unittest.TestCase):
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

    def test_crawl_marks_filtered_out_articles_as_seen(self) -> None:
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
            self.assertIn("https://www.ptt.cc/bbs/CVS/M.old.html", crawler.seen_urls)


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
