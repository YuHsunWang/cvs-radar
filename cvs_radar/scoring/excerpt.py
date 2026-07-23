from __future__ import annotations

from __future__ import annotations
import csv
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from ..config import (
    BRANDS,
)
from ..models import Post
from ..sentiment import NEGATIVE_WORDS, POSITIVE_WORDS

from ._common import (DEFAULT_REVIEW_EXCERPT_OVERRIDES_PATH, _BRACKET_RE, _COMMENT_NOISE_RE, _EXCERPT_ASPECT_TERMS, _EXCERPT_DECISION_TERMS, _EXCERPT_DROP_RE, _EXCERPT_FIRST_HAND_RE, _EXCERPT_INTRO_RE, _EXCERPT_LABEL_RE, _EXCERPT_SENTENCE_RE, _EXCERPT_SENTENCE_START_RE, _EXCERPT_SIGNATURE_RE, _OFF_TOPIC_COMMENT_RE, _URL_RE)
from .attribution import (_comment_attribution, _is_reaction_echo_comment)
from .identity import (canonical_product_name)


@lru_cache(maxsize=4)
def _load_review_excerpt_overrides(path: str = DEFAULT_REVIEW_EXCERPT_OVERRIDES_PATH) -> dict[str, str]:
    """載入 Codex 節錄覆寫表（product_key -> 節錄）。檔案不存在時回傳空字典。"""
    file_path = Path(path)
    if not file_path.exists():
        return {}
    overrides: dict[str, str] = {}
    with open(file_path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            key = (row.get("product_key") or "").strip()
            excerpt = (row.get("節錄") or "").strip()
            if key and excerpt:
                overrides[key] = excerpt
    return overrides


@dataclass(frozen=True, slots=True)
class _ReviewCandidate:
    text: str
    score: float
    aspects: frozenset[str]
    post_index: int
    sentence_index: int


def _review_excerpt(posts: list[Post], max_len: int = 180, max_sentences: int = 3) -> str:
    """Select diverse, purchase-relevant sentences from every author review."""

    candidates = _review_candidates(posts)
    selected: list[_ReviewCandidate] = []
    covered_aspects: set[str] = set()

    while candidates and len(selected) < max_sentences:
        ranked = sorted(
            candidates,
            key=lambda item: (
                -(item.score + 2.0 * len(item.aspects - covered_aspects)),
                item.post_index,
                item.sentence_index,
                item.text,
            ),
        )
        chosen = None
        for candidate in ranked:
            if any(_review_sentences_similar(candidate.text, item.text) for item in selected):
                continue
            rendered = _render_review_sentences([*selected, candidate])
            if len(rendered) <= max_len:
                chosen = candidate
                break
        if chosen is None:
            break
        selected.append(chosen)
        covered_aspects.update(chosen.aspects)
        candidates.remove(chosen)

    return _render_review_sentences(selected)


def _review_candidates(posts: list[Post]) -> list[_ReviewCandidate]:
    candidates: list[_ReviewCandidate] = []
    ordered_posts = sorted(
        posts,
        key=lambda post: (post.posted_at.isoformat() if post.posted_at else "", post.id),
        reverse=True,
    )

    for post_index, post in enumerate(ordered_posts):
        for sentence_index, sentence in enumerate(_review_sentences(post.review_text)):
            compact = re.sub(r"\s+", "", sentence).casefold()
            aspects = frozenset(
                aspect
                for aspect, terms in _EXCERPT_ASPECT_TERMS.items()
                if any(term.casefold() in compact for term in terms)
            )
            decision_hits = sum(term.casefold() in compact for term in _EXCERPT_DECISION_TERMS)
            sentiment_hits = sum(
                term.casefold() in compact
                for term in {*POSITIVE_WORDS, *NEGATIVE_WORDS}
                if len(term) >= 2
            )
            if not aspects and not decision_hits and not sentiment_hits:
                continue

            score = 3.0 * len(aspects) + 2.5 * min(decision_hits, 2) + 1.25 * min(sentiment_hits, 3)
            if 12 <= len(sentence) <= 80:
                score += 1.0
            if _EXCERPT_FIRST_HAND_RE.search(sentence):
                score += 0.75
            if _EXCERPT_INTRO_RE.search(sentence):
                score -= 2.5
            if post.author_score is not None:
                score += min(abs(post.author_score - 50) / 50, 1.0)
            score += min(sentence_index, 10) * 0.05
            candidates.append(
                _ReviewCandidate(
                    text=sentence,
                    score=score,
                    aspects=aspects,
                    post_index=post_index,
                    sentence_index=sentence_index,
                )
            )
    return candidates


def _review_sentences(review_text: str) -> list[str]:
    sentences: list[str] = []
    text = unicodedata.normalize("NFKC", review_text or "")
    blocks: list[list[str]] = []
    block: list[str] = []

    def flush_block() -> None:
        if block:
            blocks.append(block.copy())
            block.clear()

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if _EXCERPT_SIGNATURE_RE.search(line):
            flush_block()
            break
        if not line:
            continue
        if _URL_RE.search(line) or _EXCERPT_DROP_RE.search(line):
            flush_block()
            continue
        line = _EXCERPT_LABEL_RE.sub("", line).strip()
        line = re.sub(r"\(\s*[?!？]?\s*\)", "", line)
        if len(line) >= 4:
            block.append(line)
    flush_block()

    for lines in blocks:
        sources = ["".join(lines)] if _looks_hard_wrapped(lines) else _merge_wrapped_review_lines(lines)
        for source in sources:
            for match in _EXCERPT_SENTENCE_RE.finditer(source):
                fragment = re.sub(r"\s+", " ", match.group(0)).strip(" ：:、-—─")
                for sentence in _chunk_review_fragment(fragment):
                    if 6 <= len(sentence) <= 140:
                        sentences.append(sentence)
    return sentences


def _looks_hard_wrapped(lines: list[str]) -> bool:
    if len(lines) < 4:
        return False
    common_length, count = Counter(len(line) for line in lines).most_common(1)[0]
    return common_length >= 10 and count >= 3 and count / len(lines) >= 0.5


def _merge_wrapped_review_lines(lines: list[str]) -> list[str]:
    if not lines:
        return []
    merged: list[str] = []
    current = lines[0]
    previous = lines[0]
    for line in lines[1:]:
        continues = previous.endswith((",", "，", "、", ":", "：")) or (
            len(previous) >= 28 and not re.search(r"[。！？!?；;)）]$", previous)
        )
        if continues:
            separator = "。" if _EXCERPT_SENTENCE_START_RE.search(line) else ""
            current += separator + line
        else:
            merged.append(current)
            current = line
        previous = line
    merged.append(current)
    return merged


def _chunk_review_fragment(fragment: str, target_len: int = 70) -> list[str]:
    if len(fragment) <= target_len:
        return [fragment]

    clauses = [clause.strip() for clause in re.split(r"[,，]", fragment) if clause.strip()]
    if len(clauses) <= 1:
        return [fragment]
    if len(clauses) >= 3 and _EXCERPT_INTRO_RE.search(clauses[0]):
        clauses = clauses[1:]

    chunks: list[str] = []
    current = ""
    for clause in clauses:
        candidate = f"{current},{clause}" if current else clause
        if current and len(candidate) > target_len and len(current) >= 18:
            chunks.append(current)
            current = clause
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def _review_sentences_similar(left: str, right: str) -> bool:
    left_key = re.sub(r"[^\w\u4e00-\u9fff]+", "", left).casefold()
    right_key = re.sub(r"[^\w\u4e00-\u9fff]+", "", right).casefold()
    if not left_key or not right_key:
        return False
    if left_key in right_key or right_key in left_key:
        return True
    return SequenceMatcher(None, left_key, right_key).ratio() >= 0.78


def _remove_unmatched_parentheses(text: str) -> str:
    """Drop stray parentheses while preserving the review text around them."""

    open_indexes: list[int] = []
    remove_indexes: set[int] = set()
    for index, char in enumerate(text):
        if char == "(":
            open_indexes.append(index)
        elif char == ")":
            if open_indexes:
                open_indexes.pop()
            else:
                remove_indexes.add(index)
    remove_indexes.update(open_indexes)
    return "".join(char for index, char in enumerate(text) if index not in remove_indexes)


def _render_review_sentences(candidates: list[_ReviewCandidate]) -> str:
    rendered = []
    for candidate in sorted(candidates, key=lambda item: (item.post_index, item.sentence_index)):
        sentence = _remove_unmatched_parentheses(candidate.text)
        sentence = sentence.replace(",", "，").strip("。！？!?；; ，")
        if sentence:
            rendered.append(f"{sentence}。")
    return " ".join(rendered)


def _rep_comments(posts: list[Post], k: int = 3) -> tuple[list[str], list[str]]:
    positive: list[tuple[float, str]] = []
    negative: list[tuple[float, str]] = []
    for post in posts:
        for comment in post.comments:
            if comment.sentiment is None or not comment.text.strip():
                continue
            attribution = _comment_attribution(post.brand, comment)
            if not attribution.include_score or attribution.effective_sentiment is None:
                continue
            if _OFF_TOPIC_COMMENT_RE.search(comment.text):
                continue
            if _is_reaction_echo_comment(comment.text):
                continue
            text = _clean_representative_comment(post.brand, comment.text)
            if not text:
                continue
            item = (attribution.effective_sentiment, text)
            if attribution.effective_sentiment > 0.2:
                positive.append(item)
            elif attribution.effective_sentiment < -0.2:
                negative.append(item)
    positive.sort(key=lambda item: -item[0])
    negative.sort(key=lambda item: item[0])
    return _dedupe_ranked_comments(positive, k), _dedupe_ranked_comments(negative, k)


def representative_product_name(posts: list[Post]) -> str:
    """選出代表性商品名稱。"""
    if not posts:
        return "unknown"
    names = [canonical_product_name(posts[0].brand, post.product_name) for post in posts]
    counts = Counter(names)
    return min(counts, key=lambda name: (-counts[name], -len(name), name))


def _clean_representative_comment(brand: str, text: str) -> str:
    s = unicodedata.normalize("NFKC", text or "").strip()
    for kw in sorted(set([*BRANDS.get(brand, []), brand]), key=len, reverse=True):
        if kw:
            # Only remove a store name when it is a label-like prefix. Brand names
            # inside a sentence carry meaning (e.g. "全家的甜品" / "我買全家的時候").
            pattern = rf"^{re.escape(kw)}(?=[\s:：])[\s:：]*"
            s = re.sub(pattern, "", s, count=1, flags=re.IGNORECASE)
    s = _BRACKET_RE.sub(" ", s)
    s = _COMMENT_NOISE_RE.sub(" ", s)
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"^[\s:：,，.。!！?？~～\-]+|[\s:：,，.。!！?？~～\-]+$", "", s)
    return s.strip()


def _dedupe_ranked_comments(items: list[tuple[float, str]], k: int) -> list[str]:
    selected: list[str] = []
    seen: set[str] = set()
    for _, text in items:
        key = re.sub(r"\s+", "", unicodedata.normalize("NFKC", text).casefold())
        if key in seen:
            continue
        seen.add(key)
        selected.append(text)
        if len(selected) >= k:
            break
    return selected
