"""Lexicon sentiment backend for PRD F3."""

from __future__ import annotations

import re

from .config import SENTIMENT
from .models import Post

POSITIVE_WORDS = {
    "好吃": 1.0,
    "喜歡": 0.8,
    "推薦": 0.9,
    "回購": 1.0,
    "香": 0.6,
    "濃": 0.5,
    "脆": 0.4,
    "嫩": 0.6,
    "划算": 0.7,
    "不錯": 0.6,
    "可以": 0.3,
    "讚": 0.9,
    "優": 0.7,
    "滿意": 0.8,
}

NEGATIVE_WORDS = {
    "難吃": -1.0,
    "失望": -0.8,
    "不推": -0.9,
    "雷": -0.9,
    "踩雷": -1.0,
    "乾": -0.5,
    "膩": -0.6,
    "油": -0.4,
    "鹹": -0.5,
    "貴": -0.5,
    "空虛": -0.7,
    "普通": -0.2,
    "沒味道": -0.7,
    "糟": -0.9,
}

NEGATIONS = ("不", "沒", "無", "沒有", "別")
INTENSIFIERS = {"超": 1.3, "很": 1.2, "蠻": 1.1, "有點": 0.8, "稍微": 0.7, "太": 1.2}


def clamp(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def tag_prior(tag: str) -> float:
    tag = tag.strip()
    if tag.startswith("推"):
        return 1.0
    if tag.startswith("噓"):
        return -1.0
    return 0.0


def lexicon_score(text: str) -> float:
    text = (text or "").strip()
    if not text:
        return 0.0

    hits: list[float] = []
    for word, value in {**POSITIVE_WORDS, **NEGATIVE_WORDS}.items():
        for match in re.finditer(re.escape(word), text):
            start = max(0, match.start() - 4)
            prefix = text[start:match.start()]
            sign = -1.0 if any(n in prefix for n in NEGATIONS) else 1.0
            amp = 1.0
            for token, factor in INTENSIFIERS.items():
                if token in prefix:
                    amp = max(amp, factor)
            hits.append(clamp(value * sign * amp))

    if not hits:
        return 0.0
    return clamp(sum(hits) / max(1.0, len(hits)))


def score_comment(tag: str, text: str) -> float:
    alpha = float(SENTIMENT["tag_prior_weight"])
    score = alpha * tag_prior(tag) + (1.0 - alpha) * lexicon_score(text)
    return round(clamp(score), 4)


def annotate_posts(posts: list[Post]) -> list[Post]:
    for post in posts:
        for comment in post.comments:
            comment.sentiment = score_comment(comment.tag, comment.text)
    return posts
