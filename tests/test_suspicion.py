from __future__ import annotations

from datetime import datetime, timedelta
import unittest

from cvs_radar.models import Comment, Post
from cvs_radar.pipeline import run_pipeline
from cvs_radar.preference import _burst_ratio, _template_like_ratio, build_profiles
from cvs_radar.reporting import render_suspicion_detail
from cvs_radar.scoring import _is_shill_comment, _shill_stats


class SuspicionSignalTest(unittest.TestCase):
    def test_burst_ratio_detects_same_brand_window(self) -> None:
        start = datetime(2026, 6, 1, 10, 0)
        timestamps = [start + timedelta(minutes=20 * index) for index in range(5)]

        self.assertGreater(_burst_ratio({"7-11": timestamps}), 0)

    def test_burst_ratio_ignores_spread_out_comments(self) -> None:
        start = datetime(2026, 6, 1, 10, 0)
        timestamps = [start + timedelta(days=index) for index in range(5)]

        self.assertEqual(_burst_ratio({"7-11": timestamps}), 0)

    def test_build_profiles_skips_none_posted_at_for_burst(self) -> None:
        post = Post(
            id="none-time",
            brand="7-11",
            product_name="測試",
            comments=[
                Comment("推", "u1", "很好吃會回購", None, 0.9),
                Comment("推", "u1", "真的很好吃", None, 0.9),
                Comment("推", "u1", "推薦大家買", None, 0.9),
                Comment("推", "u1", "口味很穩", None, 0.9),
                Comment("推", "u1", "價格可以", None, 0.9),
            ],
        )

        profile = build_profiles([post])["u1"]

        self.assertEqual(profile.suspicion_features["burst"], 0)

    def test_template_like_ratio_detects_identical_text(self) -> None:
        texts = ["這款真的很好吃會回購"] * 3

        self.assertEqual(_template_like_ratio(texts), 1.0)

    def test_template_like_ratio_detects_near_duplicate_text(self) -> None:
        texts = [
            "這款真的很好吃會回購冰過以後口感更好",
            "這款真的很好吃會再回購冰過以後口感更好",
            "這款真的很好吃會回購，冰過以後口感更好！",
        ]

        self.assertEqual(_template_like_ratio(texts), 1.0)

    def test_template_like_ratio_ignores_different_text(self) -> None:
        texts = ["這款真的很好吃會回購", "價格偏高不推薦", "包裝方便但味道普通"]

        self.assertEqual(_template_like_ratio(texts), 0)

    def test_template_like_ratio_excludes_short_generic_text(self) -> None:
        texts = ["推", "讚", "好吃", "這款真的很好吃會回購"]

        self.assertEqual(_template_like_ratio(texts), 0)

    def test_render_suspicion_detail_includes_all_feature_names(self) -> None:
        start = datetime(2026, 6, 1, 10, 0)
        post = Post(
            id="detail",
            brand="7-11",
            product_name="測試",
            comments=[
                Comment("推", "u1", "這款真的很好吃會回購", start + timedelta(minutes=10 * index))
                for index in range(5)
            ],
        )
        _, profiles = run_pipeline([post])

        detail = render_suspicion_detail(profiles["u1"], [post])

        for name in ["one_sided", "single_brand", "extreme", "template_like", "burst"]:
            self.assertIn(name, detail)

    def test_credibility_still_reduces_comment_weight_after_feature_rename(self) -> None:
        start = datetime(2026, 6, 1, 10, 0)
        posts = [
            Post(
                id="weighted",
                brand="7-11",
                product_name="測試",
                comments=[
                    Comment("推", "u1", "這款真的很好吃會回購", start + timedelta(minutes=10 * index))
                    for index in range(5)
                ],
            )
        ]

        reports, profiles = run_pipeline(posts)
        profile = profiles["u1"]
        contributor = next(c for c in reports[0].contributors if c.user == "u1")

        self.assertIn("template_like", profile.suspicion_features)
        self.assertNotIn("repeated_text", profile.suspicion_features)
        self.assertLess(profile.credibility, 1.0)
        self.assertAlmostEqual(contributor.weight, profile.credibility, places=4)


class ShillDetectionTest(unittest.TestCase):
    def test_shill_keyword_detected(self) -> None:
        self.assertTrue(_is_shill_comment("葉"))
        self.assertTrue(_is_shill_comment("業配吧"))
        self.assertTrue(_is_shill_comment("業"))
        self.assertTrue(_is_shill_comment("滿滿的葉味"))

    def test_false_positive_excluded(self) -> None:
        self.assertFalse(_is_shill_comment("茶葉蛋好吃"))
        self.assertFalse(_is_shill_comment("好吃"))
        self.assertFalse(_is_shill_comment(""))

    def test_shill_stats_flags_high_ratio(self) -> None:
        start = datetime(2026, 6, 10, 14, 0)
        posts = [
            Post(
                id="shill-test",
                brand="7-11",
                product_name="測試",
                comments=[
                    Comment("推", "a", "好吃", start),
                    Comment("噓", "b", "葉", start + timedelta(minutes=1)),
                    Comment("噓", "c", "業配", start + timedelta(minutes=2)),
                    Comment("→", "d", "業", start + timedelta(minutes=3)),
                ],
            )
        ]
        ratio, flag = _shill_stats(posts)
        self.assertTrue(flag)
        self.assertAlmostEqual(ratio, 0.75, places=2)

    def test_shill_stats_no_flag_below_threshold(self) -> None:
        start = datetime(2026, 6, 10, 14, 0)
        posts = [
            Post(
                id="normal-test",
                brand="7-11",
                product_name="測試",
                comments=[
                    Comment("推", "a", "好吃", start),
                    Comment("推", "b", "不錯", start + timedelta(minutes=1)),
                    Comment("推", "c", "會回購", start + timedelta(minutes=2)),
                    Comment("→", "d", "普通", start + timedelta(minutes=3)),
                ],
            )
        ]
        ratio, flag = _shill_stats(posts)
        self.assertFalse(flag)
        self.assertEqual(ratio, 0.0)

    def test_shill_flag_reduces_score_via_pipeline(self) -> None:
        start = datetime(2026, 6, 10, 14, 0)
        shill_posts = [
            Post(
                id="shill-pipe",
                brand="全家",
                product_name="業配商品",
                author="promo",
                author_score=95,
                comments=[
                    Comment("推", "a", "好吃", start),
                    Comment("噓", "b", "葉", start + timedelta(minutes=1)),
                    Comment("噓", "c", "業配", start + timedelta(minutes=2)),
                    Comment("→", "d", "業", start + timedelta(minutes=3)),
                ],
            )
        ]
        reports, _ = run_pipeline(shill_posts)
        self.assertTrue(reports[0].shill_flag)
        self.assertGreater(reports[0].shill_ratio, 0.0)

    def test_shill_stats_ignores_too_few_comments(self) -> None:
        posts = [
            Post(
                id="few",
                brand="7-11",
                product_name="測試",
                comments=[
                    Comment("噓", "a", "葉", datetime(2026, 6, 10, 14, 0)),
                ],
            )
        ]
        ratio, flag = _shill_stats(posts)
        self.assertFalse(flag)
        self.assertEqual(ratio, 0.0)


if __name__ == "__main__":
    unittest.main()
