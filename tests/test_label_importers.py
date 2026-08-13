from __future__ import annotations

import csv
import subprocess
from pathlib import Path

import pytest

from cvs_radar.product_labels import PROMPT_VERSION, product_name_fingerprint_v2
from cvs_radar.comment_labels import (
    PROMPT_VERSION as COMMENT_PROMPT_VERSION,
    comment_picks_fingerprint_v2,
)
from cvs_radar.excerpt_labels import (
    PROMPT_VERSION as EXCERPT_PROMPT_VERSION,
    excerpt_fingerprint_v2,
)
from cvs_radar.grounding_verdicts import (
    FIELDNAMES as VERDICT_FIELDNAMES,
    PROMPT_VERSION as GROUNDING_PROMPT_VERSION,
    grounding_fingerprint,
)
from cvs_radar.label_validation import MIN_MEANINGFUL_OVERLAP
from scripts import import_comment_picks as import_comment_picks_module
from scripts import import_excerpts as import_excerpts_module
from scripts.import_comment_picks import import_picks as import_comment_picks
from scripts.import_excerpts import import_labels as import_excerpts
from scripts.import_product_names import import_labels as import_product_names
from scripts.migrate_sentiment_overrides import analyze as analyze_sentiment_migration
from scripts import relabel_delta


@pytest.fixture(autouse=True)
def _never_write_into_the_repo(tmp_path, monkeypatch):
    """Redirect every importer's default output path into tmp.

    The importers write quarantine and adjudication queues next to the repo by
    default, and a test that forgets to override those paths silently drops
    fixture rows into artifacts/ — where a later adjudication run will pick them
    up as if they were real data. That happened once; this makes it impossible.
    """

    for module in (import_excerpts_module, import_comment_picks_module):
        monkeypatch.setattr(
            module, "DEFAULT_REJECTS_PATH", tmp_path / "default-rejects.csv"
        )
        monkeypatch.setattr(
            module, "DEFAULT_PENDING_PATH", tmp_path / "default-pending.csv"
        )


PRODUCT_FIELDS = (
    "fingerprint",
    "item_index",
    "brand",
    "title",
    "raw_name",
    "rule_guess",
    "product_name",
    "price",
    "model",
    "prompt_version",
)


def _write_csv(path: Path, rows: list[dict[str, str]], fields=PRODUCT_FIELDS) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _product_row(raw_name: str, product_name: str = "") -> dict[str, str]:
    row = {
        "item_index": "0",
        "brand": "全家",
        "title": f"[商品] {raw_name}",
        "raw_name": raw_name,
        "rule_guess": f"{raw_name}#49",
        "product_name": product_name,
        "price": "49" if product_name else "",
        "model": "codex" if product_name else "",
        "prompt_version": PROMPT_VERSION,
    }
    row["fingerprint"] = product_name_fingerprint_v2(
        row["brand"],
        row["title"],
        row["raw_name"],
        rule_guess=row["rule_guess"],
        prompt_version=row["prompt_version"],
    )
    return row


def test_product_import_rejects_swapped_fingerprints_before_cache_write(tmp_path: Path) -> None:
    source_rows = [_product_row("草莓蛋糕"), _product_row("抹茶布丁")]
    labeled_rows = [dict(row) for row in source_rows]
    labeled_rows[0].update(product_name="草莓蛋糕", price="49", model="codex")
    labeled_rows[1].update(product_name="抹茶布丁", price="49", model="codex")
    labeled_rows[0]["fingerprint"], labeled_rows[1]["fingerprint"] = (
        labeled_rows[1]["fingerprint"],
        labeled_rows[0]["fingerprint"],
    )
    source = tmp_path / "source.csv"
    labeled = tmp_path / "labeled.csv"
    cache = tmp_path / "cache.csv"
    _write_csv(source, source_rows)
    _write_csv(labeled, labeled_rows)

    with pytest.raises(ValueError, match="immutable field"):
        import_product_names(labeled, source, cache)

    assert not cache.exists()


def test_product_import_rejects_duplicate_item_index(tmp_path: Path) -> None:
    source_row = _product_row("草莓蛋糕/抹茶布丁")
    labeled_rows = [dict(source_row), dict(source_row)]
    labeled_rows[0].update(product_name="草莓蛋糕", price="49", model="codex")
    labeled_rows[1].update(product_name="抹茶布丁", price="55", model="codex")
    source = tmp_path / "source.csv"
    labeled = tmp_path / "labeled.csv"
    cache = tmp_path / "cache.csv"
    _write_csv(source, [source_row])
    _write_csv(labeled, labeled_rows)

    with pytest.raises(ValueError, match="duplicate fingerprint/item_index"):
        import_product_names(labeled, source, cache)

    assert not cache.exists()


EXCERPT_FIELDS = (
    "fingerprint",
    "post_id",
    "brand",
    "product_name",
    "other_products",
    "review_text",
    "body_candidates",
    "source_indices",
    "rewrite",
    "model",
    "prompt_version",
)


def _excerpt_row(review_text: str, rewrite: str = "", row_index: int = 0) -> dict[str, str]:
    body_candidates = "\n".join(
        f"{index}. {text}" for index, text in enumerate(review_text.split("\n")) if text
    )
    row = {
        "post_id": "M.1" if row_index == 0 else f"M.1.{row_index}",
        "brand": "全家",
        "product_name": "草莓蛋糕",
        "other_products": "抹茶布丁",
        "review_text": review_text,
        "body_candidates": body_candidates,
        "source_indices": "0" if rewrite else "",
        "rewrite": rewrite,
        "model": "codex" if rewrite else "",
        "prompt_version": EXCERPT_PROMPT_VERSION,
    }
    row["fingerprint"] = excerpt_fingerprint_v2(
        row["post_id"],
        row["product_name"],
        row["review_text"],
        brand=row["brand"],
        other_products=row["other_products"],
        candidate_sentences=[
            line.split(". ", 1)[1]
            for line in body_candidates.splitlines()
        ],
        prompt_version=row["prompt_version"],
    )
    return row


def _low_overlap_excerpt(tmp_path: Path) -> tuple[Path, Path, Path, dict]:
    """A rewrite the character screen cannot clear — 0 shared meaningful chars."""

    source_row = _excerpt_row("蛋糕酸甜，奶油很輕盈。")
    labeled_row = dict(
        source_row,
        source_indices="0",
        rewrite="作者說一定會回購",
        model="codex",
    )
    source = tmp_path / "source.csv"
    labeled = tmp_path / "labeled.csv"
    _write_csv(source, [source_row], EXCERPT_FIELDS)
    _write_csv(labeled, [labeled_row], EXCERPT_FIELDS)
    return source, labeled, tmp_path / "cache.csv", labeled_row


def test_excerpt_import_holds_unscreenable_rewrite_instead_of_guessing(
    tmp_path: Path,
) -> None:
    """Below the overlap threshold the screen defers; it does not reject."""

    source, labeled, cache, labeled_row = _low_overlap_excerpt(tmp_path)
    pending = tmp_path / "pending.csv"

    added, _, _, rejected, held = import_excerpts(
        labeled,
        source,
        cache,
        rejects_path=tmp_path / "rejects.csv",
        pending_path=pending,
        verdicts_path=tmp_path / "verdicts.csv",
    )
    assert (added, rejected, held) == (0, 0, 1)
    assert "作者說一定會回購" not in cache.read_text(encoding="utf-8-sig")

    queued = list(csv.DictReader(pending.open(encoding="utf-8-sig")))
    assert len(queued) == 1
    assert queued[0]["rewrite"] == "作者說一定會回購"
    assert queued[0]["source_text"] == "蛋糕酸甜，奶油很輕盈。"
    assert queued[0]["verdict"] == ""


def _write_verdict(path: Path, rewrite: str, source_text: str, verdict: str) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=VERDICT_FIELDNAMES)
        writer.writeheader()
        writer.writerow(
            {
                "fingerprint": grounding_fingerprint(rewrite, source_text),
                "rewrite": rewrite,
                "source_text": source_text,
                "verdict": verdict,
                "model": "codex",
                "prompt_version": GROUNDING_PROMPT_VERSION,
            }
        )


def test_excerpt_import_rejects_when_model_judged_it_ungrounded(tmp_path: Path) -> None:
    source, labeled, cache, _ = _low_overlap_excerpt(tmp_path)
    verdicts = tmp_path / "verdicts.csv"
    _write_verdict(verdicts, "作者說一定會回購", "蛋糕酸甜，奶油很輕盈。", "ungrounded")

    with pytest.raises(ValueError, match="judged the rewrite ungrounded"):
        import_excerpts(
            labeled,
            source,
            cache,
            rejects_path=tmp_path / "rejects.csv",
            pending_path=tmp_path / "pending.csv",
            verdicts_path=verdicts,
        )
    assert not cache.exists()


def test_excerpt_import_accepts_low_overlap_paraphrase_the_model_cleared(
    tmp_path: Path,
) -> None:
    """The 「太貴了」→「價格偏高」 case: zero shared characters, still faithful."""

    source, labeled, cache, _ = _low_overlap_excerpt(tmp_path)
    verdicts = tmp_path / "verdicts.csv"
    _write_verdict(verdicts, "作者說一定會回購", "蛋糕酸甜，奶油很輕盈。", "grounded")

    added, _, _, rejected, held = import_excerpts(
        labeled,
        source,
        cache,
        rejects_path=tmp_path / "rejects.csv",
        pending_path=tmp_path / "pending.csv",
        verdicts_path=verdicts,
    )
    assert (added, rejected, held) == (1, 0, 0)
    assert "作者說一定會回購" in cache.read_text(encoding="utf-8-sig")


def test_excerpt_import_enforces_prompt_limit_of_30_characters(tmp_path: Path) -> None:
    review = "酸" * 31
    source_row = _excerpt_row(review, "")
    labeled_row = dict(source_row, source_indices="0", rewrite=review, model="codex")
    source = tmp_path / "source.csv"
    labeled = tmp_path / "labeled.csv"
    cache = tmp_path / "cache.csv"
    _write_csv(source, [source_row], EXCERPT_FIELDS)
    _write_csv(labeled, [labeled_row], EXCERPT_FIELDS)

    with pytest.raises(ValueError, match="longer than 30"):
        import_excerpts(labeled, source, cache)

    assert not cache.exists()


COMMENT_FIELDS = (
    "fingerprint",
    "brand",
    "product_name",
    "other_products",
    "comments",
    "body_candidates",
    "positive_rewrites",
    "negative_rewrites",
    "positive_body_rewrites",
    "negative_body_rewrites",
    "model",
    "prompt_version",
)


def _comment_row(row_index: int = 0) -> dict[str, str]:
    comments = ["舒跑款可愛", "本體高十公分"]
    body = ["造型可愛", "尺寸不小"]
    product_name = "飲料小夥伴吊飾" if row_index == 0 else f"飲料小夥伴吊飾{row_index}"
    return {
        "fingerprint": comment_picks_fingerprint_v2(
            "7-11", product_name, comments, body, other_products="另一款吊飾"
        ),
        "brand": "7-11",
        "product_name": product_name,
        "other_products": "另一款吊飾",
        "comments": "0. 舒跑款可愛\n1. 本體高十公分",
        "body_candidates": "0. 造型可愛\n1. 尺寸不小",
        "positive_rewrites": "",
        "negative_rewrites": "",
        "positive_body_rewrites": "",
        "negative_body_rewrites": "",
        "model": "",
        "prompt_version": COMMENT_PROMPT_VERSION,
    }


def test_comment_import_accepts_grounded_non_verbatim_rewrite(tmp_path: Path) -> None:
    source_row = _comment_row()
    labeled_row = dict(
        source_row,
        positive_rewrites='[{"source_index":0,"text":"舒跑款很可愛"}]',
        model="codex",
    )
    source = tmp_path / "source.csv"
    labeled = tmp_path / "labeled.csv"
    cache = tmp_path / "cache.csv"
    _write_csv(source, [source_row], COMMENT_FIELDS)
    _write_csv(labeled, [labeled_row], COMMENT_FIELDS)

    assert import_comment_picks(labeled, source, cache) == (1, 0, 0, 0, 0)
    assert "舒跑款很可愛" in cache.read_text(encoding="utf-8-sig")


def _bulk_comment_rows(total: int, bad_indexes: set[int]) -> tuple[list[dict], list[dict]]:
    """Build ``total`` rows where ``bad_indexes`` carry an ungrounded rewrite."""

    sources, labeled = [], []
    for index in range(total):
        source_row = _comment_row(index)
        text = "另一款吊飾做工精細" if index in bad_indexes else "舒跑款很可愛"
        sources.append(source_row)
        labeled.append(
            dict(
                source_row,
                positive_rewrites=f'[{{"source_index":0,"text":"{text}"}}]',
                model="codex",
            )
        )
    return sources, labeled


def test_comment_import_quarantines_an_isolated_bad_row(tmp_path: Path) -> None:
    """One hallucination must not discard the other 59 rows of a labelling run."""

    sources, labeled_rows = _bulk_comment_rows(60, {7})
    source = tmp_path / "source.csv"
    labeled = tmp_path / "labeled.csv"
    cache = tmp_path / "cache.csv"
    rejects = tmp_path / "rejects.csv"
    _write_csv(source, sources, COMMENT_FIELDS)
    _write_csv(labeled, labeled_rows, COMMENT_FIELDS)

    result = import_comment_picks(labeled, source, cache, rejects_path=rejects)
    assert result == (59, 0, 0, 1, 0)

    cached = cache.read_text(encoding="utf-8-sig")
    assert sources[7]["fingerprint"] not in cached
    assert "另一款吊飾做工精細" not in cached

    quarantined = rejects.read_text(encoding="utf-8-sig")
    assert sources[7]["fingerprint"] in quarantined
    assert "names other product" in quarantined


def test_comment_import_refuses_file_when_failures_look_systematic(tmp_path: Path) -> None:
    """Above the ceiling the model output is broken, not unlucky — refuse everything."""

    sources, labeled_rows = _bulk_comment_rows(60, set(range(10)))
    source = tmp_path / "source.csv"
    labeled = tmp_path / "labeled.csv"
    cache = tmp_path / "cache.csv"
    _write_csv(source, sources, COMMENT_FIELDS)
    _write_csv(labeled, labeled_rows, COMMENT_FIELDS)

    with pytest.raises(ValueError, match="exceeds the 2% ceiling"):
        import_comment_picks(labeled, source, cache, rejects_path=tmp_path / "r.csv")
    assert not cache.exists()


def test_excerpt_import_quarantines_an_isolated_bad_row(tmp_path: Path) -> None:
    review = "菠蘿皮是軟的\n內餡奶酥很好吃"
    sources, labeled_rows = [], []
    for index in range(60):
        source_row = _excerpt_row(review, row_index=index)
        rewrite = "抹茶布丁綿密" if index == 3 else "菠蘿皮偏軟"
        sources.append(source_row)
        labeled_rows.append(
            dict(source_row, source_indices="0", rewrite=rewrite, model="codex")
        )
    source = tmp_path / "source.csv"
    labeled = tmp_path / "labeled.csv"
    cache = tmp_path / "cache.csv"
    rejects = tmp_path / "rejects.csv"
    _write_csv(source, sources, EXCERPT_FIELDS)
    _write_csv(labeled, labeled_rows, EXCERPT_FIELDS)

    assert import_excerpts(labeled, source, cache, rejects_path=rejects) == (59, 0, 0, 1, 0)
    assert sources[3]["fingerprint"] not in cache.read_text(encoding="utf-8-sig")
    assert sources[3]["fingerprint"] in rejects.read_text(encoding="utf-8-sig")


def test_comment_import_rejects_hallucinated_rewrite_before_cache_write(tmp_path: Path) -> None:
    source_row = _comment_row()
    labeled_row = dict(
        source_row,
        positive_rewrites='[{"source_index":0,"text":"另一款吊飾做工精細"}]',
        model="codex",
    )
    source = tmp_path / "source.csv"
    labeled = tmp_path / "labeled.csv"
    cache = tmp_path / "cache.csv"
    _write_csv(source, [source_row], COMMENT_FIELDS)
    _write_csv(labeled, [labeled_row], COMMENT_FIELDS)

    with pytest.raises(ValueError, match="other product|insufficient source overlap"):
        import_comment_picks(labeled, source, cache)
    assert not cache.exists()


def test_comment_import_rejects_one_source_in_both_polarities(tmp_path: Path) -> None:
    source_row = _comment_row()
    labeled_row = dict(
        source_row,
        positive_rewrites='[{"source_index":0,"text":"舒跑款很可愛"}]',
        negative_rewrites='[{"source_index":0,"text":"舒跑款不夠可愛"}]',
        model="codex",
    )
    source = tmp_path / "source.csv"
    labeled = tmp_path / "labeled.csv"
    cache = tmp_path / "cache.csv"
    _write_csv(source, [source_row], COMMENT_FIELDS)
    _write_csv(labeled, [labeled_row], COMMENT_FIELDS)

    with pytest.raises(ValueError, match="both polarities"):
        import_comment_picks(labeled, source, cache)
    assert not cache.exists()


def test_importers_document_the_permissive_grounding_threshold() -> None:
    assert MIN_MEANINGFUL_OVERLAP == 0.25


def test_label_scripts_forward_optional_effort_to_runner() -> None:
    for name in ("label_comment_picks.sh", "label_excerpts.sh"):
        script = (Path(__file__).parents[1] / "scripts" / name).read_text()
        assert 'effort_args=(--effort "$EFFORT")' in script
        assert '"${effort_args[@]}"' in script


@pytest.mark.parametrize(
    ("failed_script", "expected_calls"),
    [
        ("label_product_names.sh", ["label_product_names.sh"]),
        (
            "label_excerpts.sh",
            ["label_product_names.sh", "label_excerpts.sh"],
        ),
        (
            "label_comment_picks.sh",
            [
                "label_product_names.sh",
                "label_excerpts.sh",
                "label_comment_picks.sh",
            ],
        ),
    ],
)
def test_required_label_failure_stops_before_later_layers(
    tmp_path: Path,
    failed_script: str,
    expected_calls: list[str],
) -> None:
    call_log = tmp_path / "calls"
    for name in (
        "label_product_names.sh",
        "label_excerpts.sh",
        "label_comment_picks.sh",
    ):
        status = 1 if name == failed_script else 0
        (tmp_path / name).write_text(
            f"#!/usr/bin/env bash\nprintf '%s\\n' {name} >> {call_log}\nexit {status}\n",
            encoding="utf-8",
        )

    result = subprocess.run(
        ["bash", "scripts/ops/run_required_label_layers.sh"],
        env={"SCRIPTS_DIR": str(tmp_path), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert call_log.read_text(encoding="utf-8").splitlines() == expected_calls


def test_rebackfill_requires_all_label_layers_before_recompute() -> None:
    script = Path("scripts/ops/rebackfill.sh").read_text(encoding="utf-8")

    gate = script.index(
        'bash scripts/ops/run_required_label_layers.sh || die "required semantic labeling"'
    )
    recompute = script.index('log "recompute results from posts + labels"')
    assert gate < recompute
    assert "publishing on" not in script


def test_legacy_relabel_merge_rejects_runtime_normalized_score_collision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "sentiment_overrides.csv"
    labeled = tmp_path / "labeled.csv"
    _write_csv(
        cache,
        [{"留言內容": "好吃", "llm分數": "0.8", "llm判定": "正向"}],
        ("留言內容", "llm分數", "llm判定"),
    )
    _write_csv(
        labeled,
        [{"留言內容": "好吃!!", "llm分數": "0.6", "llm判定": "正向"}],
        ("留言內容", "llm分數", "llm判定"),
    )
    before = cache.read_bytes()
    monkeypatch.setattr(relabel_delta, "OVERRIDES_PATH", cache)

    with pytest.raises(ValueError, match="conflicting normalized key '好吃'"):
        relabel_delta.merge(labeled)

    assert cache.read_bytes() == before


def test_sentiment_migration_takes_the_majority_not_the_last_row(tmp_path: Path) -> None:
    """Collapsing punctuation variants must not hand the key to whichever row is last.

    Runtime strips trailing punctuation, so these three rows are one key. Last-row-
    wins is import order, not a judgement: it scored 「好吃」 — the most common comment
    in the cache — at 0.6 while two rows agreed on 0.8.
    """
    cache = tmp_path / "sentiment_overrides.csv"
    _write_csv(
        cache,
        [
            {"留言內容": "好吃", "llm分數": "0.8", "llm判定": "正向"},
            {"留言內容": "好吃!", "llm分數": "0.8", "llm判定": "正向"},
            {"留言內容": "好吃。", "llm分數": "0.6", "llm判定": "正向"},
        ],
        ("留言內容", "llm分數", "llm判定"),
    )

    rows, collisions, conflicts = analyze_sentiment_migration(cache)

    assert rows == [("好吃", "0.8", "正向")]
    assert collisions == 2
    assert conflicts == 1


def test_sentiment_migration_breaks_a_tie_on_the_unpunctuated_form(tmp_path: Path) -> None:
    """With no majority, the form the key actually represents wins.

    Six of the eight real conflicts are two-row ties, so the tie-break decides most
    of them; falling back to file order would reintroduce the arbitrariness.
    """
    cache = tmp_path / "sentiment_overrides.csv"
    _write_csv(
        cache,
        [
            {"留言內容": "好貴!!", "llm分數": "-0.5", "llm判定": "負向"},
            {"留言內容": "好貴", "llm分數": "-0.25", "llm判定": "負向"},
        ],
        ("留言內容", "llm分數", "llm判定"),
    )

    rows, _, conflicts = analyze_sentiment_migration(cache)

    assert rows == [("好貴", "-0.25", "負向")]
    assert conflicts == 1


def test_sentiment_migration_keeps_original_row_order(tmp_path: Path) -> None:
    """Sorting the file would bury the handful of real changes in 4,795 moved lines."""
    cache = tmp_path / "sentiment_overrides.csv"
    _write_csv(
        cache,
        [
            {"留言內容": "很雷", "llm分數": "-0.8", "llm判定": "負向"},
            {"留言內容": "好吃", "llm分數": "0.8", "llm判定": "正向"},
            {"留言內容": "普通", "llm分數": "0.0", "llm判定": "中性"},
        ],
        ("留言內容", "llm分數", "llm判定"),
    )

    rows, collisions, conflicts = analyze_sentiment_migration(cache)

    assert [row[0] for row in rows] == ["很雷", "好吃", "普通"]
    assert (collisions, conflicts) == (0, 0)
