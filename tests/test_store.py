from __future__ import annotations

import json
import unittest
import warnings
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

from cvs_radar.models import Comment, Post
from cvs_radar.pipeline import run_pipeline
from cvs_radar.store import dict_to_post, load_posts, post_to_dict, save_posts, store_stats


class StoreTest(unittest.TestCase):
    def test_roundtrip_post_with_comments(self) -> None:
        """Post -> dict -> Post preserves all fields."""
        original = Post(
            id="test-1",
            source="PTT",
            brand="7-11",
            product_name="測試飯糰",
            author="tester",
            author_score=85,
            posted_at=datetime(2026, 6, 1, 12, 0, tzinfo=ZoneInfo("Asia/Taipei")),
            comments=[
                Comment(
                    "推",
                    "alice",
                    "好吃",
                    datetime(2026, 6, 1, 12, 10, tzinfo=ZoneInfo("Asia/Taipei")),
                ),
                Comment("噓", "bob", "普通", None),
            ],
        )
        restored = dict_to_post(post_to_dict(original))
        self.assertEqual(restored.id, original.id)
        self.assertEqual(restored.brand, original.brand)
        self.assertEqual(restored.author_score, original.author_score)
        self.assertEqual(restored.posted_at, original.posted_at)
        self.assertEqual(len(restored.comments), 2)
        self.assertEqual(restored.comments[0].text, "好吃")
        self.assertIsNone(restored.comments[1].posted_at)

    def test_save_and_load_deduplicates(self) -> None:
        """save_posts skips duplicates; load_posts deduplicates by id."""
        post = Post(id="dup-1", brand="7-11", product_name="Test", author="a")

        with TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "test.jsonl"
            n1 = save_posts([post], store_path)
            n2 = save_posts([post], store_path)
            loaded = load_posts(store_path)

            self.assertEqual(n1, 1)
            self.assertEqual(n2, 0)
            self.assertEqual(len(loaded), 1)

    def test_save_creates_parent_directory(self) -> None:
        with TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "nested" / "deep" / "test.jsonl"
            save_posts([Post(id="dir-1", brand="7-11", product_name="Test", author="a")], store_path)
            self.assertTrue(store_path.exists())

    def test_load_from_nonexistent_returns_empty(self) -> None:
        self.assertEqual(load_posts("/tmp/does_not_exist_xyz.jsonl"), [])

    def test_load_skips_corrupt_middle_and_truncated_final_lines_with_diagnostics(self) -> None:
        good_posts = [
            Post(id="good-1", brand="7-11", product_name="One"),
            Post(id="good-2", brand="全家", product_name="Two"),
        ]
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "posts.jsonl"
            path.write_text(
                json.dumps(post_to_dict(good_posts[0]), ensure_ascii=False)
                + "\n{corrupt middle\n"
                + json.dumps(post_to_dict(good_posts[1]), ensure_ascii=False)
                + '\n{"id":"truncated"',
                encoding="utf-8",
            )

            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                loaded = load_posts(path)

        self.assertEqual([post.id for post in loaded], ["good-1", "good-2"])
        diagnostics = "\n".join(str(warning.message) for warning in caught)
        self.assertIn(f"{path}:2", diagnostics)
        self.assertIn(f"{path}:4", diagnostics)
        self.assertIn("skipped 2 invalid JSONL lines", diagnostics)

    def test_append_after_truncated_line_preserves_new_record(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "posts.jsonl"
            path.write_text(
                json.dumps(post_to_dict(Post(id="good-1", product_name="One")))
                + '\n{"id":"truncated"',
                encoding="utf-8",
            )

            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                self.assertEqual(save_posts([Post(id="good-2", product_name="Two")], path), 1)
                reloaded = load_posts(path)

        self.assertEqual([post.id for post in reloaded], ["good-1", "good-2"])

    def test_store_stats_summarizes_posts_comments_brands_and_dates(self) -> None:
        posts = [
            Post(
                id="stats-1",
                brand="7-11",
                product_name="Coffee",
                posted_at=datetime(2026, 6, 1, 12, 0),
                comments=[Comment("推", "u1", "好喝")],
            ),
            Post(
                id="stats-2",
                brand="全家",
                product_name="Tea",
                posted_at=datetime(2026, 6, 2, 12, 0),
            ),
        ]

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "posts.jsonl"
            save_posts(posts, path)
            stats = store_stats(path)

        self.assertEqual(stats["path"], str(path))
        self.assertEqual(stats["post_count"], 2)
        self.assertEqual(stats["comment_count"], 1)
        self.assertEqual(stats["brands"], ["7-11", "全家"])
        self.assertEqual(
            stats["date_range"],
            ("2026-06-01T12:00:00+08:00", "2026-06-02T12:00:00+08:00"),
        )

    def test_stored_posts_flow_through_pipeline(self) -> None:
        """Posts saved and loaded from store produce valid pipeline output."""
        post = Post(
            id="pipe-1",
            brand="全家",
            product_name="雞肉飯糰",
            author="u1",
            author_score=80,
            comments=[Comment("推", "u2", "好吃會回購")],
        )

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.jsonl"
            save_posts([post], path)
            loaded = load_posts(path)
            reports, profiles = run_pipeline(loaded)

            self.assertEqual(len(reports), 1)
            self.assertIsNotNone(reports[0].fair_score)

    def test_report_roundtrip(self) -> None:
        """ProductReport -> dict -> ProductReport preserves all fields."""
        from cvs_radar.models import Contributor, ProductReport
        from cvs_radar.store import report_to_store_dict, store_dict_to_report

        original = ProductReport(
            brand="7-11",
            product_name="測試飯糰",
            fair_score=72.5,
            consensus="褒貶不一",
            confidence="中",
            n_eff=5.2,
            score_std=0.18,
            n_posts=3,
            n_comments=15,
            contributors=[Contributor("u1", "commenter", 0.8, 0.9)],
            rep_positive=["好吃"],
            rep_negative=["太貴"],
            product_key="7-11:測試飯糰",
            score_mean=0.65,
            competitor_mention_count=2,
            competitor_preference_count=1,
            competitor_brands=["全家"],
            shill_flag=True,
            shill_ratio=0.375,
        )
        restored = store_dict_to_report(report_to_store_dict(original))
        self.assertEqual(restored.brand, original.brand)
        self.assertEqual(restored.fair_score, original.fair_score)
        self.assertEqual(restored.consensus, original.consensus)
        self.assertEqual(len(restored.contributors), 1)
        self.assertEqual(restored.contributors[0].user, "u1")
        self.assertEqual(restored.rep_positive, ["好吃"])
        self.assertEqual(restored.competitor_brands, ["全家"])
        self.assertTrue(restored.shill_flag)
        self.assertEqual(restored.shill_ratio, 0.375)

    def test_old_report_schema_defaults_shill_fields(self) -> None:
        from cvs_radar.models import ProductReport
        from cvs_radar.store import report_to_store_dict, store_dict_to_report

        old_schema = report_to_store_dict(
            ProductReport("7-11", "舊資料", 70.0, "褒貶不一", "低", 1.0, 0.2, 1, 2)
        )
        old_schema.pop("shill_flag", None)
        old_schema.pop("shill_ratio", None)

        restored = store_dict_to_report(old_schema)

        self.assertFalse(restored.shill_flag)
        self.assertEqual(restored.shill_ratio, 0.0)

    def test_profile_roundtrip(self) -> None:
        """AccountProfile -> dict -> AccountProfile preserves all fields."""
        from cvs_radar.preference import AccountProfile, BrandStat
        from cvs_radar.store import profile_to_store_dict, store_dict_to_profile

        original = AccountProfile(
            user="test_user",
            brand_stats={"7-11": BrandStat(count=10, avg_sentiment=0.75)},
            lean_brand="7-11",
            suspicion_score=0.42,
            suspicion_features={"one_sided": 0.3, "single_brand": 0.8},
            credibility=0.58,
            total_comments=10,
        )
        restored = store_dict_to_profile(profile_to_store_dict(original))
        self.assertEqual(restored.user, original.user)
        self.assertEqual(restored.suspicion_score, original.suspicion_score)
        self.assertEqual(restored.brand_stats["7-11"].count, 10)
        self.assertEqual(restored.credibility, 0.58)

    def test_save_and_load_results(self) -> None:
        """Full results save/load roundtrip."""
        from cvs_radar.models import ProductReport
        from cvs_radar.preference import AccountProfile
        from cvs_radar.store import load_results, save_results

        reports = [
            ProductReport(
                brand="7-11",
                product_name="Test",
                fair_score=70.0,
                consensus="褒貶不一",
                confidence="中",
                n_eff=4.0,
                score_std=0.2,
                n_posts=2,
                n_comments=8,
            )
        ]
        profiles = {"u1": AccountProfile(user="u1", total_comments=5)}

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "results.json"
            save_results(reports, profiles, path)
            loaded = load_results(path)

            self.assertIsNotNone(loaded)
            loaded_reports, loaded_profiles = loaded
            self.assertEqual(len(loaded_reports), 1)
            self.assertEqual(loaded_reports[0].fair_score, 70.0)
            self.assertIn("u1", loaded_profiles)

    def test_load_results_nonexistent_returns_none(self) -> None:
        from cvs_radar.store import load_results

        self.assertIsNone(load_results("/tmp/does_not_exist_results.json"))
