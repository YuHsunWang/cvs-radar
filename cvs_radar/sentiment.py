"""Pluggable sentiment backends for PRD F3."""

from __future__ import annotations

import os
import re
from typing import Protocol

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


class SentimentBackend(Protocol):
    name: str

    def text_score(self, text: str) -> float:
        """Return text-only sentiment in [-1, 1]."""


class LlmSentimentClient(Protocol):
    def score_text(self, text: str, *, provider: str, model: str, api_key: str) -> float:
        """Return text-only sentiment in [-1, 1]."""


class LexiconBackend:
    name = "lexicon"

    def text_score(self, text: str) -> float:
        return lexicon_score(text)


class SnowNlpBackend:
    name = "snownlp"

    def __init__(self, fallback: SentimentBackend | None = None) -> None:
        self.fallback = fallback or LexiconBackend()

    def text_score(self, text: str) -> float:
        text = (text or "").strip()
        if not text:
            return 0.0
        try:
            from snownlp import SnowNLP
        except ImportError:
            return self.fallback.text_score(text)

        probability = float(SnowNLP(text).sentiments)
        return clamp((probability * 2.0) - 1.0)


class LlmBackend:
    """LLM sentiment interface with local fallback when disabled or unavailable."""

    name = "llm"

    def __init__(
        self,
        *,
        client: LlmSentimentClient | None = None,
        fallback: SentimentBackend | None = None,
    ) -> None:
        self.client = client
        self.fallback = fallback or _backend_from_name(_llm_config().get("fallback_backend", "snownlp"), allow_llm=False)

    def text_score(self, text: str) -> float:
        text = (text or "").strip()
        if not text:
            return 0.0

        llm_config = _llm_config()
        api_key = _llm_api_key(llm_config)
        enabled = bool(llm_config.get("enabled"))
        if not enabled or not api_key or self.client is None:
            return self.fallback.text_score(text)

        try:
            score = self.client.score_text(
                text,
                provider=str(llm_config.get("provider", "")),
                model=str(llm_config.get("model", "")),
                api_key=api_key,
            )
        except Exception:
            return self.fallback.text_score(text)
        return clamp(float(score))


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


def score_comment(tag: str, text: str, *, backend: str | SentimentBackend | None = None) -> float:
    alpha = float(SENTIMENT["tag_prior_weight"])
    text_backend = resolve_backend(backend)
    score = alpha * tag_prior(tag) + (1.0 - alpha) * text_backend.text_score(text)
    return round(clamp(score), 4)


def annotate_posts(posts: list[Post]) -> list[Post]:
    backend = resolve_backend()
    for post in posts:
        for comment in post.comments:
            comment.sentiment = score_comment(comment.tag, comment.text, backend=backend)
    return posts


def resolve_backend(backend: str | SentimentBackend | None = None) -> SentimentBackend:
    if backend is None:
        return _backend_from_name(str(SENTIMENT.get("backend", "lexicon")))
    if isinstance(backend, str):
        return _backend_from_name(backend)
    return backend


def llm_has_key() -> bool:
    return bool(_llm_api_key(_llm_config()))


def _backend_from_name(name: str, *, allow_llm: bool = True) -> SentimentBackend:
    normalized = (name or "lexicon").strip().casefold()
    if normalized == "lexicon":
        return LexiconBackend()
    if normalized == "snownlp":
        return SnowNlpBackend()
    if normalized == "llm" and allow_llm:
        return LlmBackend()
    raise ValueError(f"unknown sentiment backend: {name!r}")


def _llm_config() -> dict[str, object]:
    raw = SENTIMENT.get("llm", {})
    return raw if isinstance(raw, dict) else {}


def _llm_api_key(llm_config: dict[str, object]) -> str:
    inline_key = str(llm_config.get("api_key", "") or "")
    if inline_key:
        return inline_key
    env_name = str(llm_config.get("api_key_env", "CVS_RADAR_LLM_API_KEY") or "")
    return os.environ.get(env_name, "") if env_name else ""
