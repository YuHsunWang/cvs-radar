from __future__ import annotations

import json
import unittest

from cvs_radar.models import Comment, Post
from cvs_radar.parser import parse_ptt_article, parse_score
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


if __name__ == "__main__":
    unittest.main()
