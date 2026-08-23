from __future__ import annotations

from datetime import datetime, timedelta
from statistics import mean
import unittest
from unittest.mock import patch

from cvs_radar.models import Comment, Post
from cvs_radar.pipeline import run_pipeline
from cvs_radar.preference import _burst_ratio, _template_like_ratio, build_profiles
from cvs_radar.reporting import render_suspicion_detail
from cvs_radar.config import SHILL_DETECTION
from cvs_radar.scoring import (
    _author_shill_flagged,
    _decay,
    _is_shill_comment,
    _shill_stats,
    build_comment_opinions,
    score_product,
)


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

        profile = build_profiles([post], build_comment_opinions([post]))["u1"]

        self.assertEqual(profile.suspicion_features["burst"], 0)

    def test_profile_and_score_share_the_same_eligible_opinions(self) -> None:
        posted_at = datetime(2026, 6, 10, 14, 0)
        legitimate = Comment(
            "推", "u1", "我吃過很好吃會回購", posted_at, 0.9, "fingerprint-cache"
        )
        noise = [
            Comment(
                "推",
                "u1",
                "謝謝分享",
                posted_at + timedelta(minutes=index + 1),
                0.9,
                "fingerprint-cache",
            )
            for index in range(5)
        ]
        noisy_post = Post(
            id="eligibility",
            brand="全家",
            product_name="草莓蛋糕",
            author="author",
            comments=[legitimate, *noise],
        )
        control_post = Post(
            id="control",
            brand="全家",
            product_name="草莓蛋糕",
            author="author",
            comments=[legitimate],
        )

        noisy_opinions = build_comment_opinions([noisy_post])
        noisy_profiles = build_profiles([noisy_post], noisy_opinions)
        control_opinions = build_comment_opinions([control_post])
        control_profiles = build_profiles([control_post], control_opinions)

        self.assertEqual(noisy_profiles["u1"].total_comments, 1)
        self.assertEqual(
            noisy_profiles["u1"].credibility,
            control_profiles["u1"].credibility,
        )
        self.assertEqual(
            sum(opinion.include_score for opinion in noisy_opinions.values()),
            1,
        )
        self.assertEqual(
            score_product(
                [noisy_post], noisy_profiles, posted_at, noisy_opinions
            ).fair_score,
            score_product(
                [control_post], control_profiles, posted_at, control_opinions
            ).fair_score,
        )

        report = score_product(
            [noisy_post], noisy_profiles, posted_at, noisy_opinions
        )
        self.assertEqual(report.n_comments, 6)
        self.assertEqual(report.n_eligible_comments, 1)
        self.assertEqual(report.n_unique_commenters, 1)

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
        # weight = credibility × time decay: equal to credibility only after
        # dividing the decay factor back out (λ > 0 since 2026-07-20).
        # contributor.weight is stored rounded to 4 places, so dividing it by an
        # unrounded decay carries up to ~rounding/decay (~1e-4) of error; assert to
        # 3 places, which still proves credibility (0.175) down-weights vs 1.0.
        decay = mean(_decay(c.posted_at) for c in posts[0].comments)
        self.assertGreater(decay, 0.0)
        self.assertAlmostEqual(contributor.weight / decay, profile.credibility, places=3)


class ShillDetectionTest(unittest.TestCase):
    def test_shill_keyword_detected(self) -> None:
        self.assertTrue(_is_shill_comment("業配吧"))
        self.assertTrue(_is_shill_comment("這根本葉配"))

    def test_false_positive_excluded(self) -> None:
        # Single-char 業/葉 keywords used to flag ordinary words like 專業/營業.
        self.assertFalse(_is_shill_comment("專業推文"))
        self.assertFalse(_is_shill_comment("營業到幾點"))
        self.assertFalse(_is_shill_comment("畢業快樂"))
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
                    Comment("噓", "b", "葉配無誤", start + timedelta(minutes=1)),
                    Comment("噓", "c", "業配", start + timedelta(minutes=2)),
                    Comment("→", "d", "業配文吧", start + timedelta(minutes=3)),
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

    def test_shill_accusation_discounts_the_author_and_nobody_else(self) -> None:
        """The accusation is aimed at whoever wrote the review, so only that vote moves.

        Scaling every opinion instead punishes the accusers along with the accused,
        and because mu/sigma/n_eff all divide by the total weight, a uniform scale
        only pulls fair01 toward the prior — which raises the score of a product
        people are calling a paid promo. Asserting the commenters keep their exact
        weights is what makes this test fail if the penalty ever goes group-wide.
        """
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
                    Comment("噓", "b", "葉配無誤", start + timedelta(minutes=1)),
                    Comment("噓", "c", "業配", start + timedelta(minutes=2)),
                    Comment("→", "d", "業配文吧", start + timedelta(minutes=3)),
                ],
            )
        ]
        reports, _ = run_pipeline(shill_posts)
        with patch(
            "cvs_radar.scoring.compute._author_shill_flagged", return_value=False
        ):
            control_reports, _ = run_pipeline(shill_posts)

        self.assertTrue(reports[0].shill_flag)
        self.assertGreater(reports[0].shill_ratio, 0.0)

        weights = {c.user: c.weight for c in reports[0].contributors}
        control = {c.user: c.weight for c in control_reports[0].contributors}
        penalty = float(SHILL_DETECTION["post_weight_penalty"])
        self.assertAlmostEqual(weights["promo"], control["promo"] * penalty, places=4)
        for commenter in ("a", "b", "c", "d"):
            self.assertAlmostEqual(weights[commenter], control[commenter], places=4)

    def test_one_accuser_does_not_discount_the_author(self) -> None:
        """業配 is cheap to shout, so a lone accusation is not a verdict.

        12 of the 16 accused posts in the corpus carry exactly one accusation; if a
        single account could halve a reviewer's vote, the cheapest way to sink a
        review would be to shout at it once.
        """
        start = datetime(2026, 6, 10, 14, 0)
        post = Post(
            id="one-accuser",
            brand="全家",
            product_name="單人指控",
            author="reviewer",
            author_score=95,
            comments=[
                Comment("推", "a", "好吃", start),
                Comment("推", "b", "不錯吃", start + timedelta(minutes=1)),
                Comment("噓", "c", "業配", start + timedelta(minutes=2)),
            ],
        )
        self.assertFalse(_author_shill_flagged(post))

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
