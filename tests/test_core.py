from __future__ import annotations

import json
import unittest

from cvs_radar.models import Comment, Post
from cvs_radar.parser import parse_ptt_article, parse_push_datetime, parse_score
from cvs_radar.pipeline import run_pipeline
from cvs_radar.reporting import render_json, render_text
from cvs_radar.scoring import normalize_product
from cvs_radar.sentiment import LlmBackend, score_comment


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
        self.assertEqual(comment.posted_at.isoformat(), "2026-06-01T12:01:00")

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

    def test_product_normalization_strips_noise_and_units(self) -> None:
        self.assertEqual(
            normalize_product("7-11", "鮪魚飯糰2入"),
            normalize_product("7-11", "鮪魚飯糰"),
        )
        self.assertEqual(
            normalize_product("全家", "新品 XX蛋糕 心得開箱"),
            normalize_product("全家", "XX蛋糕"),
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


class SentimentTest(unittest.TestCase):
    def test_tag_and_lexicon_mix(self) -> None:
        self.assertGreater(score_comment("推", "好吃會回購"), 0)
        self.assertLess(score_comment("噓", "難吃踩雷"), 0)
        self.assertEqual(score_comment("→", ""), 0)

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


class AppHelperTest(unittest.TestCase):
    def test_app_helpers_use_service_query_shape(self) -> None:
        from datetime import datetime
        from cvs_radar.app_helpers import ALL_BRANDS, brand_options, build_product_query, product_rows
        from cvs_radar.sample_data import load_sample
        from cvs_radar.service import query_products

        now = datetime(2026, 6, 15, 12, 0)
        posts = load_sample()

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
        self.assertIn("代表性推", rows[0])


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
