from __future__ import annotations

import csv
import json
from pathlib import Path

from cvs_radar.models import Comment, Post
from cvs_radar.sentiment import (
    apply_sentiment_overrides,
    comment_fingerprint,
    comment_fingerprints,
    load_fingerprint_labels,
    sentiment_fingerprint,
    sentiment_fingerprint_v2,
)
from scripts.export_llm_backfill import export_unlabeled_comments
from scripts.import_llm_backfill import import_labels


def test_fingerprint_is_stable_and_does_not_need_account_name() -> None:
    first = sentiment_fingerprint(
        "https://www.ptt.cc/bbs/CVS/M.test.html",
        "→",
        "先看有沒有毒油啊!!",
    )
    second = sentiment_fingerprint(
        "https://www.ptt.cc/bbs/CVS/M.test.html",
        "→",
        "先看有沒有毒油啊",
    )

    assert first == second
    assert len(first) == 64


def test_export_only_writes_unlabeled_account_free_comments(tmp_path: Path) -> None:
    posts_path = tmp_path / "posts.jsonl"
    out_path = tmp_path / "unlabeled.csv"
    post = {
        "id": "M.test",
        "url": "https://www.ptt.cc/bbs/CVS/M.test.html",
        "brand": "全家",
        "product_name": "測試麵包",
        "title": "[商品] 全家 測試麵包",
        "comments": [
            {"tag": "推", "user": "private-user", "text": "已有人工作過"},
            {"tag": "→", "user": "another-user", "text": "香蒜奶油風味很化工"},
        ],
    }
    posts_path.write_text(json.dumps(post, ensure_ascii=False) + "\n", encoding="utf-8")

    count = export_unlabeled_comments(
        posts_path,
        out_path,
        known_texts={"已有人工作過"},
        known_fingerprints=set(),
    )

    assert count == 1
    with open(out_path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["comment_text"] == "香蒜奶油風味很化工"
    assert rows[0]["product_name"] == "測試麵包"
    assert "user" not in rows[0]
    assert "url" not in rows[0]


def test_import_validates_and_writes_privacy_safe_label_cache(tmp_path: Path) -> None:
    labeled_path = tmp_path / "labeled.csv"
    labels_path = tmp_path / "labels.csv"
    fingerprints = ["a" * 64, "b" * 64, "c" * 64]
    with open(labeled_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=(
                "fingerprint",
                "llm_score",
                "llm_label",
                "is_relevant",
                "model",
                "prompt_version",
            ),
        )
        writer.writeheader()
        writer.writerow(
            {
                "fingerprint": fingerprints[0],
                "llm_score": "-0.8",
                "llm_label": "負向",
                "is_relevant": "true",
                "model": "subscription-llm",
                "prompt_version": "sentiment-v1",
            }
        )
        writer.writerow(
            {
                "fingerprint": fingerprints[1],
                "llm_score": "",
                "llm_label": "中性",
                "is_relevant": "false",
            }
        )
        writer.writerow({"fingerprint": fingerprints[2]})

    added, replaced, skipped = import_labels(labeled_path, labels_path)

    assert (added, replaced, skipped) == (2, 0, 1)
    contents = labels_path.read_text(encoding="utf-8-sig")
    assert "comment_text" not in contents
    assert "private-user" not in contents
    labels = load_fingerprint_labels(labels_path)
    assert labels[fingerprints[0]] == (-0.8, True)
    assert labels[fingerprints[1]] == (None, False)


def test_fingerprint_labels_override_rules_and_manual_text_remains_final() -> None:
    post = Post(
        id="M.test",
        url="https://www.ptt.cc/bbs/CVS/M.test.html",
        comments=[
            Comment("→", "u1", "香蒜奶油又不是稀有東西", sentiment=0.5),
            Comment("→", "u2", "只是在討論包裝", sentiment=0.3),
        ],
    )
    negative_key = comment_fingerprint(post, post.comments[0])
    irrelevant_key = comment_fingerprint(post, post.comments[1])

    apply_sentiment_overrides(
        [post],
        overrides={},
        fingerprint_labels={
            negative_key: (-0.8, True),
            irrelevant_key: (None, False),
        },
    )

    assert post.comments[0].sentiment == -0.8
    assert post.comments[0].backend == "llm-backfill"
    assert post.comments[1].sentiment is None

    apply_sentiment_overrides(
        [post],
        overrides={},
        fingerprint_labels={negative_key: (0.6, True)},
        corrections={"香蒜奶油又不是稀有東西": -1.0},
    )
    assert post.comments[0].sentiment == -1.0
    assert post.comments[0].backend == "codex"


def test_every_context_field_the_labeller_reads_changes_the_key() -> None:
    """The exporter shows brand, product name and title; all three steer relevance.

    A field the labeller reads but the key ignores lets one answer cover posts it
    was never judged against — the same defect that merged four products under
    「飛燕煉乳炸銀絲卷」 when the title was missing from the product-name key.
    """
    base = dict(
        source_id="https://www.ptt.cc/bbs/CVS/M.test.html",
        tag="推",
        text="好油",
        brand="7-11",
        product_name="炸銀絲卷",
        post_title="[商品] 7-11 炸銀絲卷",
    )
    digest = sentiment_fingerprint_v2(**base)
    for field, other in (
        ("brand", "全家"),
        ("product_name", "美式咖啡"),
        ("post_title", "[商品] 7-11 美式咖啡"),
        ("prompt_version", "sentiment-v2"),
    ):
        assert sentiment_fingerprint_v2(**{**base, field: other}) != digest, field


def test_labels_collected_under_the_legacy_key_still_resolve() -> None:
    """Adding context to the key must not strand the labels already paid for.

    Coverage loss here means a silent fallback to rule-based sentiment across the
    whole archive, so the staged migration keeps consulting the legacy key.
    """
    post = Post(
        id="M.staged",
        url="https://www.ptt.cc/bbs/CVS/M.staged.html",
        brand="全家",
        product_name="測試麵包",
        title="[商品] 全家 測試麵包",
        comments=[Comment("→", "u1", "太甜了", sentiment=0.4)],
    )
    current, legacy = comment_fingerprints(post, post.comments[0])
    assert current != legacy

    apply_sentiment_overrides(
        [post], overrides={}, fingerprint_labels={legacy: (-0.7, True)}, corrections={}
    )
    assert post.comments[0].sentiment == -0.7
    assert post.comments[0].backend == "llm-backfill"


def test_legacy_text_label_never_overrides_a_contextual_label() -> None:
    """A legacy text label carries no article context and no relevance judgement.

    Letting it win would resurrect comments the contextual labeler ruled
    irrelevant, turning chatter such as 「謝謝分享」 into a scored opinion.
    """
    post = Post(
        id="M.legacy",
        url="https://www.ptt.cc/bbs/CVS/M.legacy.html",
        comments=[
            Comment("推", "u1", "謝謝分享", sentiment=0.4),
            Comment("推", "u2", "真的好吃", sentiment=0.4),
        ],
    )
    irrelevant_key = comment_fingerprint(post, post.comments[0])

    apply_sentiment_overrides(
        [post],
        overrides={"謝謝分享": 0.0, "真的好吃": 0.9},
        fingerprint_labels={irrelevant_key: (None, False)},
        corrections={},
    )

    # Ruled irrelevant in context: it must stay out of scoring entirely.
    assert post.comments[0].sentiment is None
    # No contextual label yet: the legacy label still applies as a fallback.
    assert post.comments[1].sentiment == 0.9
    assert post.comments[1].backend == "codex-legacy"


def test_export_still_offers_legacy_labeled_comments_for_contextual_labeling(
    tmp_path: Path,
) -> None:
    """Legacy-labeled comments must remain exportable, or they can never be fixed.

    Excluding them by text is what kept 「謝謝分享」-style rows permanently outside
    the contextual labeler.
    """
    posts_path = tmp_path / "posts.jsonl"
    out_path = tmp_path / "unlabeled.csv"
    post = {
        "id": "M.legacy",
        "url": "https://www.ptt.cc/bbs/CVS/M.legacy.html",
        "brand": "全家",
        "product_name": "測試麵包",
        "title": "[商品] 全家 測試麵包",
        "comments": [
            {"tag": "推", "user": "u1", "text": "謝謝分享"},
            {"tag": "推", "user": "u2", "text": "已人工校正過"},
        ],
    }
    posts_path.write_text(json.dumps(post, ensure_ascii=False) + "\n", encoding="utf-8")

    count = export_unlabeled_comments(
        posts_path,
        out_path,
        known_texts={"已人工校正過"},
        known_fingerprints=set(),
    )

    assert count == 1
    with open(out_path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["comment_text"] == "謝謝分享"
