from __future__ import annotations

import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from cvs_radar.models import Comment, Post
from cvs_radar.pipeline import run_pipeline
from cvs_radar.store import dict_to_post, load_posts, post_to_dict, save_posts


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
            posted_at=datetime(2026, 6, 1, 12, 0),
            comments=[
                Comment("推", "alice", "好吃", datetime(2026, 6, 1, 12, 10)),
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
