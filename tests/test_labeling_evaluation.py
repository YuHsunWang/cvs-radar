from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from cvs_radar.evaluation import (
    RuleBasedPredictor,
    SentimentBackendPredictor,
    compare_sentiment_backends,
    evaluate,
    read_gold_csv,
    render_text_report,
    write_json_report,
)
from cvs_radar.labeling import build_labeling_rows, read_labeling_csv, write_labeling_csv
from cvs_radar.sample_data import load_sample


class LabelingTest(unittest.TestCase):
    def test_build_labeling_rows_from_demo_keeps_blank_label_fields(self) -> None:
        rows = build_labeling_rows(load_sample(), limit=2)

        self.assertEqual([row.comment_id for row in rows], ["sample-711-fuhang#000", "sample-711-fuhang#001"])
        self.assertEqual(rows[0].post_brand, "7-11")
        self.assertIn("貼文品牌=7-11", rows[0].context)
        self.assertEqual(rows[0].sentiment, "")
        self.assertEqual(rows[0].favored_brand, "")

    def test_write_and_read_labeling_csv(self) -> None:
        rows = build_labeling_rows(load_sample(), limit=1)
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "to_label.csv"

            write_labeling_csv(rows, path)
            loaded = read_labeling_csv(path)

        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["comment_id"], "sample-711-fuhang#000")
        self.assertEqual(loaded[0]["sentiment"], "")

    def test_demo_labeling_csv_does_not_fabricate_labels(self) -> None:
        rows = build_labeling_rows(load_sample())

        self.assertGreater(len(rows), 8)
        for row in rows:
            self.assertEqual(row.sentiment, "")
            self.assertEqual(row.target_brand, "")
            self.assertEqual(row.is_comparative, "")
            self.assertEqual(row.favored_brand, "")

    def test_prelabel_fills_all_label_columns(self) -> None:
        """prelabel_rows fills sentiment, target_brand, is_comparative, favored_brand, notes."""
        from scripts.prelabel import prelabel_rows

        row = {
            "comment_id": "test#000",
            "source": "PTT",
            "board": "CVS",
            "post_id": "test",
            "post_url": "",
            "post_title": "[商品] 7-11 測試",
            "post_brand": "7-11",
            "product_name": "測試飯糰",
            "price": "50",
            "post_tag": "商品",
            "comment_user": "tester",
            "comment_tag": "推",
            "comment_text": "好吃會回購",
            "comment_posted_at": "",
            "context": "貼文品牌=7-11",
            "sentiment": "",
            "target_brand": "",
            "is_comparative": "",
            "favored_brand": "",
            "notes": "",
        }
        result = prelabel_rows([row])
        self.assertEqual(len(result), 1)
        self.assertIn(result[0]["sentiment"], ("正", "負", "中"))
        self.assertIn(result[0]["target_brand"], ("本牌", "他牌", "無"))
        self.assertIn(result[0]["is_comparative"], ("是", "否"))
        self.assertIn(result[0]["favored_brand"], ("本牌", "他牌", "平手", "不明"))
        self.assertEqual(result[0]["notes"], "auto-prelabeled")

    def test_prelabel_positive_comment(self) -> None:
        """Positive push with clear positive text gets sentiment=正."""
        from scripts.prelabel import prelabel_rows

        row = {
            "comment_id": "pos#000",
            "source": "PTT",
            "board": "CVS",
            "post_id": "pos",
            "post_url": "",
            "post_title": "[商品] 全家 好吃雞排",
            "post_brand": "全家",
            "product_name": "好吃雞排",
            "price": "",
            "post_tag": "商品",
            "comment_user": "u1",
            "comment_tag": "推",
            "comment_text": "好吃推薦回購",
            "comment_posted_at": "",
            "context": "貼文品牌=全家",
            "sentiment": "",
            "target_brand": "",
            "is_comparative": "",
            "favored_brand": "",
            "notes": "",
        }
        result = prelabel_rows([row])
        self.assertEqual(result[0]["sentiment"], "正")

    def test_labeling_stored_source(self) -> None:
        """labeling _load_posts supports 'stored' source."""
        from cvs_radar.labeling import _load_posts

        with patch("cvs_radar.store.load_posts", return_value=[]):
            with self.assertRaises(ValueError):
                _load_posts("stored", pages=5)


class EvaluationHarnessTest(unittest.TestCase):
    def test_rule_harness_runs_on_gold_smoke_and_computes_metrics(self) -> None:
        rows = read_gold_csv("data/labels/gold_smoke.csv")

        report = evaluate(rows, RuleBasedPredictor())

        self.assertEqual(report["predictor"], "rules")
        self.assertEqual(report["n_rows"], 8)
        tasks = report["tasks"]
        self.assertIn("sentiment_polarity", tasks)
        self.assertIn("competitor_preference_detection", tasks)
        self.assertIn("favored_direction", tasks)
        self.assertGreaterEqual(tasks["sentiment_polarity"]["accuracy"], 0)
        self.assertLessEqual(tasks["sentiment_polarity"]["accuracy"], 1)
        self.assertEqual(tasks["favored_direction"]["support"], 3)

    def test_backend_predictor_runs_snownlp_on_gold_smoke(self) -> None:
        rows = read_gold_csv("data/labels/gold_smoke.csv")

        report = evaluate(rows, SentimentBackendPredictor("snownlp"))

        self.assertEqual(report["predictor"], "snownlp")
        self.assertEqual(report["n_rows"], 8)
        self.assertIn("accuracy", report["tasks"]["sentiment_polarity"])

    def test_backend_comparison_csv_runs_and_marks_small_sample(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "backend_comparison.csv"

            rows = compare_sentiment_backends(
                ["data/labels/gold_smoke.csv"],
                path,
                backends=["lexicon", "snownlp"],
            )

            loaded = path.read_text(encoding="utf-8")

        self.assertEqual([row["backend"] for row in rows], ["lexicon", "snownlp"])
        self.assertIn("statistically insufficient", loaded)

    def test_render_and_write_reports(self) -> None:
        report = evaluate(read_gold_csv("data/labels/gold_smoke.csv"))
        text = render_text_report(report)

        self.assertIn("CVS Radar 評測報告", text)
        self.assertIn("sentiment_polarity", text)

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.json"
            write_json_report(report, path)
            payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(payload["predictor"], "rules")
        self.assertIn("rows", payload)


if __name__ == "__main__":
    unittest.main()
