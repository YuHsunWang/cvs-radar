from __future__ import annotations

import csv
import json
from pathlib import Path

from cvs_radar.models import Comment, Post
from cvs_radar.sentiment import (
    apply_sentiment_overrides,
    comment_fingerprint,
    load_fingerprint_labels,
    sentiment_fingerprint,
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
        overrides={"香蒜奶油又不是稀有東西": -1.0},
        fingerprint_labels={negative_key: (0.6, True)},
    )
    assert post.comments[0].sentiment == -1.0
    assert post.comments[0].backend == "codex"
