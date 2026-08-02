from __future__ import annotations

from pathlib import Path

from cvs_radar.config import CONFIDENCE_BANDS, CONSENSUS, SCORING


ROOT = Path(__file__).resolve().parents[1]


def test_prd_parameter_table_matches_runtime_config() -> None:
    prd = (ROOT / "CVS-Radar-PRD-v0.2.md").read_text(encoding="utf-8")

    assert "**歷史文件。**" in prd
    assert f"| `scoring.role_weight.author` | {SCORING['role_weight']['author']} |" in prd
    assert f"| `scoring.prior_strength` (C) | {SCORING['prior_strength']} |" in prd
    assert f"| `scoring.time_decay_lambda` (λ) | {SCORING['time_decay_lambda']} |" in prd
    assert (
        f"| `consensus.high_mean / low_mean` | {CONSENSUS['high_mean']} / "
        f"{CONSENSUS['low_mean']} |"
    ) in prd
    assert (
        f"| `consensus.low_std / high_std` | {CONSENSUS['low_std']} / "
        f"{CONSENSUS['high_std']} |"
    ) in prd
    assert CONFIDENCE_BANDS == [(3.0, "低"), (8.0, "中")]


def test_operational_docs_match_active_entry_points() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    ops = (ROOT / "docs/ops-pipeline.md").read_text(encoding="utf-8")
    crawl = (ROOT / "docs/crawl_plan.md").read_text(encoding="utf-8")
    normalized_readme = " ".join(readme.split())
    normalized_ops = " ".join(ops.split())

    assert "公開快照每日自動更新" not in readme
    assert "repository 本身不包含或證明該主機的 crontab" in normalized_readme
    for layer in (
        "sentiment labeling",
        "product-name labeling",
        "excerpt labeling",
        "representative-comment labeling",
    ):
        assert layer in normalized_ops
    assert "runs none of these four labelers" in normalized_ops
    assert "flush/fsync 成功後" in crawl
    assert "直接串接成單一 Comment" in crawl
