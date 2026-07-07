"""Offline evaluation harness for labeled CVS Radar comments."""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

from .models import Comment
from .scoring import _comment_attribution
from .sentiment import llm_has_key, score_comment


SENTIMENT_LABELS = ("positive", "negative", "neutral")
FAVORED_LABELS = ("own", "other", "tie", "unknown")


@dataclass(frozen=True, slots=True)
class Prediction:
    """保存單筆標註預測結果。"""

    sentiment: str
    target_brand: str
    is_comparative: bool
    favored_brand: str
    raw: dict[str, object] | None = None


class Predictor(Protocol):
    """定義標註列預測器介面。"""

    name: str

    def predict_row(self, row: dict[str, str]) -> Prediction:
        """Predict labels for one CSV row."""


class RuleBasedPredictor:
    """Baseline using the current lexicon sentiment and comment attribution rules."""

    name = "rules"
    backend = "lexicon"

    def predict_row(self, row: dict[str, str]) -> Prediction:
        """預測單筆標註列。"""
        text = row.get("comment_text", "")
        tag = row.get("comment_tag", "")
        post_brand = row.get("post_brand", "")
        sentiment_score = score_comment(tag, text, backend=self.backend)
        comment = Comment(tag=tag, user=row.get("comment_user", ""), text=text, sentiment=sentiment_score)
        attribution = _comment_attribution(post_brand, comment)

        is_comparative = bool(attribution.competitor_brands and _has_comparison_signal(attribution, text))
        sentiment = _sentiment_from_score(sentiment_score)
        target_brand = _target_from_attribution(text, attribution.include_score, attribution.competitor_brands)
        favored_brand = _favored_from_attribution(is_comparative, attribution.include_score, attribution.competitor_preference)

        return Prediction(
            sentiment=sentiment,
            target_brand=target_brand,
            is_comparative=is_comparative,
            favored_brand=favored_brand,
            raw={
                "sentiment_score": sentiment_score,
                "competitor_brands": list(attribution.competitor_brands),
                "competitor_preference": attribution.competitor_preference,
                "include_score": attribution.include_score,
                "effective_sentiment": attribution.effective_sentiment,
            },
        )


class SentimentBackendPredictor(RuleBasedPredictor):
    """Rule predictor with selectable comment-text sentiment backend."""

    def __init__(self, backend: str) -> None:
        self.backend = backend
        self.name = backend


class StubPredictor:
    """Interface placeholder for future LLM or fine-tuned predictors."""

    name = "stub"

    def predict_row(self, row: dict[str, str]) -> Prediction:
        """提示尚未實作的預測器。"""
        raise NotImplementedError("Implement predict_row for an LLM or fine-tuned predictor.")


def read_gold_csv(path: str | Path) -> list[dict[str, str]]:
    """讀取人工標註的黃金 CSV。"""
    with Path(path).open("r", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    required = {"comment_text", "post_brand", "sentiment", "is_comparative", "favored_brand"}
    missing = required - set(rows[0].keys() if rows else [])
    if missing:
        raise ValueError(f"gold CSV missing columns: {', '.join(sorted(missing))}")
    return rows


def evaluate(gold_rows: list[dict[str, str]], predictor: Predictor | None = None) -> dict[str, object]:
    """評估預測器在黃金標註上的表現。"""
    predictor = predictor or RuleBasedPredictor()
    gold_predictions: list[dict[str, object]] = []
    sentiment_gold: list[str] = []
    sentiment_pred: list[str] = []
    comparative_gold: list[bool] = []
    comparative_pred: list[bool] = []
    competitor_pref_gold: list[bool] = []
    competitor_pref_pred: list[bool] = []
    favored_gold: list[str] = []
    favored_pred: list[str] = []
    target_gold: list[str] = []
    target_pred: list[str] = []

    for row in gold_rows:
        prediction = predictor.predict_row(row)
        gold_sentiment = normalize_sentiment(row.get("sentiment", ""))
        gold_is_comparative = normalize_bool(row.get("is_comparative", ""))
        gold_favored = normalize_favored(row.get("favored_brand", ""))
        gold_target = normalize_target(row.get("target_brand", ""))

        sentiment_gold.append(gold_sentiment)
        sentiment_pred.append(normalize_sentiment(prediction.sentiment))
        comparative_gold.append(gold_is_comparative)
        comparative_pred.append(prediction.is_comparative)
        competitor_pref_gold.append(gold_favored == "other")
        competitor_pref_pred.append(normalize_favored(prediction.favored_brand) == "other")
        target_gold.append(gold_target)
        target_pred.append(normalize_target(prediction.target_brand))

        if gold_is_comparative:
            favored_gold.append(gold_favored)
            favored_pred.append(normalize_favored(prediction.favored_brand))

        gold_predictions.append(
            {
                "comment_id": row.get("comment_id", ""),
                "gold": {
                    "sentiment": gold_sentiment,
                    "target_brand": gold_target,
                    "is_comparative": gold_is_comparative,
                    "favored_brand": gold_favored,
                },
                "prediction": asdict(prediction),
            }
        )

    return {
        "predictor": predictor.name,
        "n_rows": len(gold_rows),
        "tasks": {
            "sentiment_polarity": multiclass_metrics(sentiment_gold, sentiment_pred, SENTIMENT_LABELS),
            "comparative_detection": binary_metrics(comparative_gold, comparative_pred),
            "competitor_preference_detection": binary_metrics(competitor_pref_gold, competitor_pref_pred),
            "favored_direction": multiclass_metrics(favored_gold, favored_pred, FAVORED_LABELS),
            "target_brand": multiclass_metrics(target_gold, target_pred, ("own", "other", "none")),
        },
        "rows": gold_predictions,
    }


def binary_metrics(gold: list[bool], pred: list[bool]) -> dict[str, float | int]:
    """計算二元分類指標。"""
    total = len(gold)
    tp = sum(g and p for g, p in zip(gold, pred))
    tn = sum((not g) and (not p) for g, p in zip(gold, pred))
    fp = sum((not g) and p for g, p in zip(gold, pred))
    fn = sum(g and (not p) for g, p in zip(gold, pred))
    precision = _safe_div(tp, tp + fp)
    recall = _safe_div(tp, tp + fn)
    f1 = _safe_div(2 * precision * recall, precision + recall)
    return {
        "accuracy": round(_safe_div(tp + tn, total), 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "support": total,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
    }


def multiclass_metrics(gold: list[str], pred: list[str], labels: tuple[str, ...]) -> dict[str, object]:
    """計算多類別分類指標。"""
    total = len(gold)
    accuracy = _safe_div(sum(g == p for g, p in zip(gold, pred)), total)
    per_class: dict[str, dict[str, float | int]] = {}
    precisions: list[float] = []
    recalls: list[float] = []
    f1s: list[float] = []

    for label in labels:
        tp = sum(g == label and p == label for g, p in zip(gold, pred))
        fp = sum(g != label and p == label for g, p in zip(gold, pred))
        fn = sum(g == label and p != label for g, p in zip(gold, pred))
        precision = _safe_div(tp, tp + fp)
        recall = _safe_div(tp, tp + fn)
        f1 = _safe_div(2 * precision * recall, precision + recall)
        precisions.append(precision)
        recalls.append(recall)
        f1s.append(f1)
        per_class[label] = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "support": sum(g == label for g in gold),
            "tp": tp,
            "fp": fp,
            "fn": fn,
        }

    return {
        "accuracy": round(accuracy, 4),
        "precision_macro": round(sum(precisions) / len(labels), 4),
        "recall_macro": round(sum(recalls) / len(labels), 4),
        "f1_macro": round(sum(f1s) / len(labels), 4),
        "support": total,
        "per_class": per_class,
    }


def render_text_report(report: dict[str, object]) -> str:
    """輸出文字版評測報告。"""
    lines = [
        "CVS Radar 評測報告",
        f"predictor: {report['predictor']}",
        f"gold rows: {report['n_rows']}",
        "",
    ]
    tasks = report["tasks"]
    assert isinstance(tasks, dict)
    for task_name, metrics in tasks.items():
        assert isinstance(metrics, dict)
        lines.append(f"[{task_name}]")
        for key in ("accuracy", "precision", "recall", "f1", "precision_macro", "recall_macro", "f1_macro", "support"):
            if key in metrics:
                lines.append(f"{key}: {metrics[key]}")
        lines.append("")
    return "\n".join(lines).rstrip()


def write_json_report(report: dict[str, object], path: str | Path) -> None:
    """寫入 JSON 評測報告。"""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def compare_sentiment_backends(
    gold_paths: list[str | Path],
    output_path: str | Path,
    *,
    backends: list[str] | None = None,
) -> list[dict[str, object]]:
    """比較多個情感後端的評測結果。"""
    selected_backends = backends or available_comparison_backends()
    rows: list[dict[str, object]] = []

    for gold_path in gold_paths:
        gold_rows = read_gold_csv(gold_path)
        dataset = Path(gold_path).name
        for backend in selected_backends:
            report = evaluate(gold_rows, SentimentBackendPredictor(backend))
            metrics = report["tasks"]["sentiment_polarity"]
            assert isinstance(metrics, dict)
            support = int(metrics["support"])
            accuracy = float(metrics["accuracy"])
            rows.append(
                {
                    "dataset": dataset,
                    "backend": backend,
                    "n_rows": support,
                    "sentiment_polarity_accuracy": accuracy,
                    "meets_80pct_target": str(accuracy >= 0.8).lower(),
                    "sample_caveat": _sample_caveat(support),
                }
            )

    write_backend_comparison_csv(rows, output_path)
    return rows


def available_comparison_backends() -> list[str]:
    """列出可用於比較的情感後端。"""
    backends = ["lexicon", "snownlp"]
    if llm_has_key():
        backends.append("llm")
    return backends


def write_backend_comparison_csv(rows: list[dict[str, object]], path: str | Path) -> None:
    """寫入情感後端比較 CSV。"""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "dataset",
        "backend",
        "n_rows",
        "sentiment_polarity_accuracy",
        "meets_80pct_target",
        "sample_caveat",
    ]
    with output_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def normalize_sentiment(value: str) -> str:
    """正規化情感標籤。"""
    token = (value or "").strip().casefold()
    aliases = {
        "正": "positive",
        "正向": "positive",
        "positive": "positive",
        "pos": "positive",
        "+": "positive",
        "負": "negative",
        "負向": "negative",
        "negative": "negative",
        "neg": "negative",
        "-": "negative",
        "中": "neutral",
        "中性": "neutral",
        "neutral": "neutral",
        "neu": "neutral",
        "0": "neutral",
    }
    if token not in aliases:
        raise ValueError(f"unknown sentiment label: {value!r}")
    return aliases[token]


def normalize_bool(value: str) -> bool:
    """正規化布林標籤。"""
    token = (value or "").strip().casefold()
    if token in {"是", "true", "t", "yes", "y", "1"}:
        return True
    if token in {"否", "false", "f", "no", "n", "0"}:
        return False
    raise ValueError(f"unknown boolean label: {value!r}")


def normalize_favored(value: str) -> str:
    """正規化偏好品牌標籤。"""
    token = (value or "").strip().casefold()
    aliases = {
        "本牌": "own",
        "own": "own",
        "post": "own",
        "他牌": "other",
        "競品": "other",
        "other": "other",
        "competitor": "other",
        "平手": "tie",
        "差不多": "tie",
        "tie": "tie",
        "draw": "tie",
        "不明": "unknown",
        "未知": "unknown",
        "無": "unknown",
        "none": "unknown",
        "unknown": "unknown",
        "": "unknown",
    }
    if token not in aliases:
        raise ValueError(f"unknown favored_brand label: {value!r}")
    return aliases[token]


def normalize_target(value: str) -> str:
    """正規化目標品牌標籤。"""
    token = (value or "").strip().casefold()
    if token in {"本牌", "own", "post"}:
        return "own"
    if token.startswith("他牌") or token in {"other", "competitor", "競品"}:
        return "other"
    if token in {"無", "none", "unknown", ""}:
        return "none"
    return "other"


def _sentiment_from_score(score: float) -> str:
    if score > 0.2:
        return "positive"
    if score < -0.2:
        return "negative"
    return "neutral"


def _target_from_attribution(text: str, include_score: bool, competitor_brands: tuple[str, ...]) -> str:
    if not text.strip():
        return "none"
    if competitor_brands:
        return "own" if include_score else "other"
    return "own"


def _favored_from_attribution(is_comparative: bool, include_score: bool, competitor_preference: bool) -> str:
    if not is_comparative:
        return "unknown"
    if competitor_preference:
        return "other"
    if include_score:
        return "own"
    return "unknown"


def _has_comparison_signal(attribution, text: str) -> bool:
    return attribution.include_score or attribution.competitor_preference or any(
        term in text for term in ("比", "比較", "較", "輸", "贏", "勝過", "不如", "屌打", "還是", "沒有", "沒")
    )


def _safe_div(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def _sample_caveat(support: int) -> str:
    if support <= 8:
        return "gold_smoke has only 8 rows; statistically insufficient for representative validation"
    return ""


def main(argv: list[str] | None = None) -> None:
    """執行評測命令列入口。"""
    parser = argparse.ArgumentParser(description="Evaluate CVS Radar comment-label predictions")
    parser.add_argument("--gold", required=True, help="Gold CSV path")
    parser.add_argument("--json", dest="json_path", help="Write JSON report to this path")
    parser.add_argument("--text", dest="text_path", help="Write text report to this path")
    parser.add_argument("--predictor", choices=["rules", "lexicon", "snownlp", "llm"], default="rules")
    parser.add_argument("--backend-comparison-csv", help="Write lexicon/snownlp/(llm with key) comparison CSV")
    args = parser.parse_args(argv)

    predictor: Predictor = RuleBasedPredictor() if args.predictor == "rules" else SentimentBackendPredictor(args.predictor)
    report = evaluate(read_gold_csv(args.gold), predictor)
    text = render_text_report(report)
    print(text)
    if args.json_path:
        write_json_report(report, args.json_path)
    if args.text_path:
        output_path = Path(args.text_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text + "\n", encoding="utf-8")
    if args.backend_comparison_csv:
        compare_sentiment_backends([args.gold], args.backend_comparison_csv)


if __name__ == "__main__":
    main()
