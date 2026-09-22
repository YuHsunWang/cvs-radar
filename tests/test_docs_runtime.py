from __future__ import annotations

import re
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
    assert (
        "`n_eff < 3` 就判為「資料不足」，前端不顯示綜合評分也不顯示正／中／負百分比"
        "——約四分之一的商品因此留白。"
    ) in normalized_readme
    for layer in (
        "sentiment labeling",
        "product-name labeling",
        "excerpt labeling",
        "representative-comment labeling",
        "category labeling",
    ):
        assert layer in normalized_ops
    assert "runs none of these five labelers" in normalized_ops
    # The sentiment rubric lives in label_sentiment_jev.py, not in
    # scripts/prompts/. Assert the doc keeps saying so: people have looked only
    # in scripts/prompts/, concluded it was lost, and rewritten it from scratch.
    assert not (ROOT / "scripts/prompts/sentiment-labeling.md").exists()
    assert (ROOT / "scripts/label_sentiment_jev.py").exists()
    assert "scripts/label_sentiment_jev.py" in normalized_ops
    assert "flush/fsync 成功後" in crawl
    assert "直接串接成單一 Comment" in crawl


def test_manual_refresh_never_seeds_private_posts_from_a_git_branch() -> None:
    workflow = (ROOT / ".github/workflows/refresh-data.yml").read_text(encoding="utf-8")
    export_workflow = (ROOT / ".github/workflows/export-llm-backfill.yml").read_text(
        encoding="utf-8"
    )

    assert "ui/mobile-redesign" not in workflow
    assert "seed-cache.yml" in workflow
    assert "docs/runbook-data-recovery.md" in workflow
    assert "Run refresh-data.yml on main first" not in export_workflow
    assert "seed-cache.yml" in export_workflow
    assert "docs/runbook-data-recovery.md" in export_workflow


def test_github_actions_are_pinned_to_commit_shas() -> None:
    uses_line = re.compile(r"^\s*-?\s*uses:\s*actions/[^@]+@(?P<ref>\S+)", re.MULTILINE)

    for workflow in (ROOT / ".github/workflows").glob("*.yml"):
        for match in uses_line.finditer(workflow.read_text(encoding="utf-8")):
            assert re.fullmatch(r"[0-9a-f]{40}", match.group("ref")), workflow
