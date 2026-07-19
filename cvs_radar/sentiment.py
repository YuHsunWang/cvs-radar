"""Pluggable sentiment backends for PRD F3."""

from __future__ import annotations

import csv
import hashlib
import logging
import os
import re
import unicodedata
from pathlib import Path
from typing import Protocol

from .config import SENTIMENT
from .models import Comment, Post

logger = logging.getLogger(__name__)

DEFAULT_OVERRIDES_PATH = "data/labels/sentiment_overrides.csv"
SUPPLEMENTAL_OVERRIDES_PATH = "data/labels/sentiment_corrections.csv"
FINGERPRINT_LABELS_PATH = "data/labels/sentiment_fingerprint_labels.csv"

POSITIVE_WORDS = {
    "好吃": 1.0,
    "好喝": 1.0,
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
    "難喝": -1.0,
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

# Compound nouns in which a sentiment character is part of a product/food name,
# not an opinion (乾 in 餅乾, 油 in 麻油, 香 in 香草…). A lexicon hit whose span
# falls inside one of these compounds is skipped.
LEXICON_BLOCKED_COMPOUNDS: dict[str, tuple[str, ...]] = {
    "乾": ("餅乾", "肉乾", "豆乾", "果乾", "乾麵", "乾拌"),
    "油": ("麻油", "奶油", "醬油", "油雞", "油飯", "油條", "油蔥", "油漆"),
    "香": ("香草", "香蕉", "香菇", "香腸", "香料", "香檳", "香芋", "香菜"),
    "鹹": ("鹹酥雞", "鹹水雞", "鹹蛋", "鹹食"),
    "濃": ("濃湯",),
    "雷": ("打雷", "雷神"),
    "貴": ("貴妃",),
}


def _in_blocked_compound(text: str, word: str, start: int) -> bool:
    for compound in LEXICON_BLOCKED_COMPOUNDS.get(word, ()):
        offset = compound.find(word)
        while offset != -1:
            begin = start - offset
            if begin >= 0 and text[begin : begin + len(compound)] == compound:
                return True
            offset = compound.find(word, offset + 1)
    return False


class SentimentBackend(Protocol):
    """定義文字情感後端介面。"""

    name: str

    def text_score(self, text: str) -> float:
        """Return text-only sentiment in [-1, 1]."""


class LlmSentimentClient(Protocol):
    """定義 LLM 情感客戶端介面。"""

    def score_text(self, text: str, *, provider: str, model: str, api_key: str) -> float:
        """Return text-only sentiment in [-1, 1]."""


class OpenAiSentimentClient:
    """LlmSentimentClient implementation using OpenAI chat completions."""

    def score_text(self, text: str, *, provider: str, model: str, api_key: str) -> float:
        """呼叫 OpenAI 取得文字情感分數。"""
        import openai

        client = openai.OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=model or "gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是一個台灣超商食品評論的情感分析器。"
                        "使用者會給你一則 PTT CVS 版的留言，請判斷情感分數。"
                        "規則：\n"
                        "- 回傳一個浮點數，範圍 -1.0（極負面）到 1.0（極正面）\n"
                        "- 0.0 表示中性\n"
                        "- 注意反諷語氣（例如「好棒喔，貴到可以當精品」是負面）\n"
                        "- 注意 PTT 用語（例如「雷」=負面、「回購」=正面）\n"
                        "- 只回傳數字，不要其他文字"
                    ),
                },
                {"role": "user", "content": text},
            ],
            temperature=0.0,
            max_tokens=10,
        )
        raw = (response.choices[0].message.content or "").strip()
        return float(raw)


class LexiconBackend:
    """使用詞典規則計算情感分數。"""

    name = "lexicon"

    def text_score(self, text: str) -> float:
        """計算文字情感分數。"""
        return lexicon_score(text)


class SnowNlpBackend:
    """使用 SnowNLP 計算情感分數。"""

    name = "snownlp"

    def __init__(self, fallback: SentimentBackend | None = None) -> None:
        self.fallback = fallback or LexiconBackend()

    def text_score(self, text: str) -> float:
        """計算文字情感分數。"""
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
        if client is None:
            try:
                client = OpenAiSentimentClient()
            except Exception:
                client = None
        self.client = client
        self.fallback = fallback or _backend_from_name(_llm_config().get("fallback_backend", "snownlp"), allow_llm=False)

    def text_score(self, text: str) -> float:
        """計算 LLM 文字情感分數。"""
        text = (text or "").strip()
        if not text:
            return 0.0

        llm_config = _llm_config()
        api_key = _llm_api_key(llm_config)
        enabled = bool(llm_config.get("enabled"))
        if not enabled:
            logger.warning("LLM sentiment disabled by config; using %s backend", self.fallback.name)
            return self.fallback.text_score(text)
        if not api_key:
            logger.warning("LLM sentiment API key missing; using %s backend", self.fallback.name)
            return self.fallback.text_score(text)
        if self.client is None:
            return self.fallback.text_score(text)

        try:
            score = self.client.score_text(
                text,
                provider=str(llm_config.get("provider", "")),
                model=str(llm_config.get("model", "")),
                api_key=api_key,
            )
        except Exception as exc:
            logger.warning("LLM sentiment API call failed; using %s backend: %s", self.fallback.name, exc)
            return self.fallback.text_score(text)
        return clamp(float(score))


def clamp(value: float, low: float = -1.0, high: float = 1.0) -> float:
    """限制數值落在指定範圍。"""
    return max(low, min(high, value))


def tag_prior(tag: str) -> float:
    """依推文標籤給予先驗分數。"""
    tag = tag.strip()
    if tag.startswith("推"):
        return 1.0
    if tag.startswith("噓"):
        return -1.0
    return 0.0


def lexicon_score(text: str) -> float:
    """使用詞典計算文字情感分數。"""
    text = (text or "").strip()
    if not text:
        return 0.0

    hits: list[float] = []
    for word, value in {**POSITIVE_WORDS, **NEGATIVE_WORDS}.items():
        for match in re.finditer(re.escape(word), text):
            if _in_blocked_compound(text, word, match.start()):
                continue
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
    """合併標籤與文字情感分數。"""
    alpha = float(SENTIMENT["tag_prior_weight"])
    text_backend = resolve_backend(backend)
    score = alpha * tag_prior(tag) + (1.0 - alpha) * text_backend.text_score(text)
    return round(clamp(score), 4)


def annotate_posts(posts: list[Post]) -> list[Post]:
    """為貼文留言標註情感分數。"""
    backend = resolve_backend()
    for post in posts:
        for comment in post.comments:
            comment.sentiment = score_comment(comment.tag, comment.text, backend=backend)
            comment.backend = backend.name
    return posts


def _normalize_override_text(text: str) -> str:
    s = unicodedata.normalize("NFKC", str(text or ""))
    s = s.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return re.sub(r"[!！?？。．.]+$", "", s).strip()


def sentiment_fingerprint(source_id: str, tag: str, text: str) -> str:
    """Build a stable, account-free identifier for one comment in one article."""
    source = unicodedata.normalize("NFKC", str(source_id or "")).strip()
    normalized_tag = unicodedata.normalize("NFKC", str(tag or "")).strip()
    normalized_text = _normalize_override_text(text)
    payload = "\x1f".join((source, normalized_tag, normalized_text))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def comment_fingerprint(post: Post, comment: Comment) -> str:
    """Fingerprint a parsed comment without storing its account name."""
    return sentiment_fingerprint(post.url or post.id, comment.tag, comment.text)


def load_sentiment_overrides(path: str | Path = DEFAULT_OVERRIDES_PATH) -> dict[str, float]:
    """載入人工/LLM 覆寫的留言情感分數（文字 -> 分數）。檔案不存在時回傳空字典。"""
    overrides: dict[str, float] = {}
    paths = [Path(path)]
    supplemental = Path(SUPPLEMENTAL_OVERRIDES_PATH)
    if supplemental != paths[0]:
        paths.append(supplemental)
    for file_path in paths:
        if not file_path.exists():
            continue
        with open(file_path, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                key = _normalize_override_text(row.get("留言內容", ""))
                if not key:
                    continue
                try:
                    overrides[key] = clamp(float(row.get("llm分數", "")))
                except (TypeError, ValueError):
                    continue
    return overrides


def load_fingerprint_labels(
    path: str | Path = FINGERPRINT_LABELS_PATH,
) -> dict[str, tuple[float | None, bool]]:
    """Load privacy-safe LLM labels keyed by comment fingerprint."""
    file_path = Path(path)
    if not file_path.exists():
        return {}
    labels: dict[str, tuple[float | None, bool]] = {}
    with open(file_path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            fingerprint = str(row.get("fingerprint") or "").strip().lower()
            if not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
                continue
            relevant_raw = str(row.get("is_relevant") or "true").strip().casefold()
            is_relevant = relevant_raw in {"1", "true", "yes", "y"}
            if not is_relevant:
                labels[fingerprint] = (None, False)
                continue
            try:
                score = clamp(float(row.get("llm_score", "")))
            except (TypeError, ValueError):
                continue
            labels[fingerprint] = (score, True)
    return labels


def apply_sentiment_overrides(
    posts: list[Post],
    overrides: dict[str, float] | None = None,
    fingerprint_labels: dict[str, tuple[float | None, bool]] | None = None,
) -> list[Post]:
    """Apply context-specific LLM labels, then legacy/manual text overrides."""
    if overrides is None:
        overrides = load_sentiment_overrides()
    if fingerprint_labels is None:
        fingerprint_labels = load_fingerprint_labels()
    if not overrides and not fingerprint_labels:
        return posts
    for post in posts:
        for comment in post.comments:
            fingerprint = comment_fingerprint(post, comment)
            if fingerprint in fingerprint_labels:
                score, is_relevant = fingerprint_labels[fingerprint]
                comment.sentiment = round(score, 4) if is_relevant and score is not None else None
                comment.backend = "llm-backfill"

            # Text corrections remain the final authority for reviewed edge cases.
            key = _normalize_override_text(comment.text)
            if key in overrides:
                comment.sentiment = round(overrides[key], 4)
                comment.backend = "codex"
    return posts


def resolve_backend(backend: str | SentimentBackend | None = None) -> SentimentBackend:
    """解析情感後端設定。"""
    if backend is None:
        return _backend_from_name(str(SENTIMENT.get("backend", "lexicon")))
    if isinstance(backend, str):
        return _backend_from_name(backend)
    return backend


def llm_has_key() -> bool:
    """判斷是否存在 LLM API 金鑰。"""
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
