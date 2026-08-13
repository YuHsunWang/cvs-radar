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
from ..comment_labels import (
    CommentPicks,
    comment_picks_fingerprint_v2,
    load_comment_picks,
    other_products_for_group,
)
from ..excerpt_labels import (
    excerpt_fingerprint_v2,
    ExcerptLabel,
    format_other_products,
    load_excerpt_labels,
)
from ..label_validation import Rewrite
from ..models import Post
from ..sentiment import NEGATIVE_WORDS, POSITIVE_WORDS

from ._common import (DEFAULT_REVIEW_EXCERPT_OVERRIDES_PATH, _FULL_URL_RE, _BRACKET_RE, _COMMENT_NOISE_RE, _EXCERPT_ASPECT_TERMS, _EXCERPT_CONTINUATION_RE, _EXCERPT_DECISION_TERMS, _EXCERPT_DROP_RE, _EXCERPT_FIRST_HAND_RE, _EXCERPT_INTRO_RE, _EXCERPT_LABEL_RE, _EXCERPT_PRODUCT_FORM_TERMS, _EXCERPT_REPORTED_OPINION_RE, _EXCERPT_SENTENCE_RE, _EXCERPT_SENTENCE_START_RE, _EXCERPT_SIGNATURE_RE, _OFF_TOPIC_COMMENT_RE, _URL_RE)
from .attribution import _comment_attribution, _is_reaction_echo_comment
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
    decisive: bool = False


# The pool is intentionally generous: the model, rather than a sentiment score,
# decides which items are useful. If a thread is unusually large, preserve its
# post/comment order and cap only after that mechanical ordering.
REP_CANDIDATE_LIMIT = 300
BODY_CANDIDATE_LIMIT = 300

# One rewrite per reviewing post, so a multi-post product concatenates several
# independent takes. A plain space ran them into one sentence; the rewrites use
# 「，」 internally, so 「；」 keeps the hierarchy readable: comma within one
# reviewer's summary, semicolon between reviewers.
EXCERPT_JOINER = "；"


@lru_cache(maxsize=1)
def _cached_excerpt_labels() -> dict[str, ExcerptLabel]:
    return load_excerpt_labels()


@lru_cache(maxsize=1)
def _cached_comment_picks() -> dict[str, CommentPicks]:
    return load_comment_picks()


def _labelled_excerpt(posts: list[Post], max_len: int) -> str | None:
    """Return the LLM-chosen excerpt for this product, or None if unlabelled.

    Labels are per (post, product), so in a thread covering several products the
    labeller has already decided which sentences belong to this one — the failure
    the keyword selector cannot fix. Newest post first, matching the order the
    fallback selector prefers.
    """
    labels = _cached_excerpt_labels()
    if not labels:
        return None

    ordered = sorted(
        posts,
        key=lambda post: (post.posted_at.isoformat() if post.posted_at else "", post.id),
        reverse=True,
    )
    chosen: list[str] = []
    seen_any = False
    missing_label = False
    for post in ordered:
        candidates = _body_candidates([post])
        if not candidates:
            continue
        # The current key covers the candidate pool and sibling products the
        # labeller was shown. Old verbatim-cache keys are intentionally ignored.
        label = labels.get(
            excerpt_fingerprint_v2(
                post.id,
                post.product_name,
                post.review_text or "",
                brand=post.brand,
                other_products=format_other_products(post.sibling_products),
                candidate_sentences=candidates,
            )
        )
        if label is None:
            missing_label = True
            continue
        seen_any = True
        if any(index >= len(candidates) for index in label.source_indices):
            missing_label = True
            continue
        rewrite = label.rewrite
        if not rewrite or any(_review_sentences_similar(rewrite, item) for item in chosen):
            continue
        candidate = EXCERPT_JOINER.join([*chosen, rewrite])
        if len(candidate) > max_len:
            break
        chosen.append(rewrite)

    if not seen_any or missing_label:
        return None
    return EXCERPT_JOINER.join(chosen)


def _review_excerpt_with_provenance(
    posts: list[Post], max_len: int = 180, max_sentences: int = 3
) -> tuple[str, bool]:
    """Return (text, provisional) for model labels or the rule fallback."""

    labelled = _labelled_excerpt(posts, max_len)
    if labelled is not None:
        return labelled, False

    return _rule_review_excerpt(posts, max_len=max_len, max_sentences=max_sentences), True


def _review_excerpt(posts: list[Post], max_len: int = 180, max_sentences: int = 3) -> str:
    """Select a model rewrite, or a clearly provisional rule fallback."""

    return _review_excerpt_with_provenance(posts, max_len, max_sentences)[0]


def _rule_review_excerpt(
    posts: list[Post], max_len: int = 180, max_sentences: int = 3
) -> str:
    """Legacy selector retained only for newly crawled, unlabelled products."""

    candidates = _rule_review_candidates(posts)
    # Prefer sentences that either describe the product or state a verdict. Only
    # fall back to contentless praise when the post offers nothing else —
    # merchandise reviews (福袋, 鑰匙圈) have no taste/texture/portion to report.
    substantive = [
        candidate for candidate in candidates if candidate.aspects or candidate.decisive
    ]
    if substantive:
        candidates = substantive
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
            # Keep a detailed, first-hand description ahead of an older sentence
            # that only repeats an already-covered aspect.
            if (
                selected
                and candidate.post_index < selected[0].post_index
                and candidate.aspects <= covered_aspects
                and not candidate.decisive
                and len(selected[0].aspects) >= 2
                and _EXCERPT_FIRST_HAND_RE.search(selected[0].text)
            ):
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
    """Build every mechanically cleaned author-sentence candidate.

    Aspects and sentiment remain metadata for the provisional fallback only. They
    never decide whether a sentence reaches the model's candidate pool.
    """

    return _build_review_candidates(posts, suppress=False)


def _rule_review_candidates(posts: list[Post]) -> list[_ReviewCandidate]:
    """Use heuristic suppression only for the clearly provisional fallback."""

    strict = _build_review_candidates(posts, suppress=True)
    return strict if strict else _build_review_candidates(posts, suppress=False)


def _build_review_candidates(posts: list[Post], *, suppress: bool) -> list[_ReviewCandidate]:
    candidates: list[_ReviewCandidate] = []
    ordered_posts = sorted(
        posts,
        key=lambda post: (post.posted_at.isoformat() if post.posted_at else "", post.id),
        reverse=True,
    )

    for post_index, post in enumerate(ordered_posts):
        for sentence_index, sentence in enumerate(_review_sentences(post.review_text)):
            compact = re.sub(r"\s+", "", sentence).casefold()
            if suppress and _mentions_different_product_form(compact, post.product_name):
                continue
            aspects = frozenset(
                aspect
                for aspect, terms in _EXCERPT_ASPECT_TERMS.items()
                if (
                    _has_descriptive_aspect(compact, post.product_name, terms)
                    if suppress
                    else any(term.casefold() in compact for term in terms)
                )
            )
            decision_hits = 0 if _EXCERPT_REPORTED_OPINION_RE.search(sentence) else sum(
                term.casefold() in compact for term in _EXCERPT_DECISION_TERMS
            )
            sentiment_hits = sum(
                term.casefold() in compact
                for term in {*POSITIVE_WORDS, *NEGATIVE_WORDS}
                if len(term) >= 2
            )
            if suppress and not aspects and not decision_hits and not sentiment_hits:
                continue
            score = 3.0 * len(aspects) + 2.5 * min(decision_hits, 2) + 1.25 * min(sentiment_hits, 3)
            # Contentless praise ("超級好吃", "我很愛") tells a reader nothing about the
            # product. Penalise rather than drop it: merchandise posts (福袋, 鑰匙圈)
            # often have no describable aspect at all, and a weak excerpt still beats
            # an empty one.
            if not aspects:
                score -= 2.0
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
                    decisive=bool(decision_hits),
                )
            )
    return candidates


def _has_descriptive_aspect(compact: str, product_name: str, terms: tuple[str, ...]) -> bool:
    return any(
        term.casefold() in compact
        and not _aspect_term_only_in_product_name(compact, product_name, term.casefold())
        for term in terms
    )


def _aspect_term_only_in_product_name(compact: str, product_name: str, term: str) -> bool:
    """Do not treat a form word in the product name as a review attribute."""

    product_names = {
        re.sub(r"\s+", "", name).casefold()
        for name in (product_name, canonical_product_name("", product_name))
        if len(name) >= 2
    }
    positions = [match.start() for match in re.finditer(re.escape(term), compact)]
    if not product_names or not positions:
        return False
    return all(
        any(_matches_product_name_context(compact, name, term, position) for name in product_names)
        for position in positions
    )


def _matches_product_name_context(compact: str, product_name: str, term: str, position: int) -> bool:
    start = product_name.find(term)
    while start >= 0:
        before_matches = start > 0 and position > 0 and product_name[start - 1] == compact[position - 1]
        end = start + len(term)
        sentence_end = position + len(term)
        after_matches = end < len(product_name) and sentence_end < len(compact) and product_name[end] == compact[sentence_end]
        if before_matches or after_matches or product_name == term == compact:
            return True
        start = product_name.find(term, start + 1)
    return False


def _mentions_different_product_form(compact: str, product_name: str) -> bool:
    product_compact = re.sub(r"\s+", "", product_name).casefold()
    target_forms = {term.casefold() for term in _EXCERPT_PRODUCT_FORM_TERMS if term.casefold() in product_compact}
    mentioned_forms = {term.casefold() for term in _EXCERPT_PRODUCT_FORM_TERMS if term.casefold() in compact}
    return bool(
        target_forms
        and any(
            re.search(rf"(?:這|那|一).{{0,8}}(?:支|個|款).{{0,12}}{re.escape(form)}|(?:買|吃).{{0,16}}{re.escape(form)}", compact)
            for form in mentioned_forms - target_forms
        )
    )


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
        if line:
            block.append(line)
    flush_block()

    for lines in blocks:
        sources = ["".join(lines)] if _looks_hard_wrapped(lines) else _merge_wrapped_review_lines(lines)
        for source in sources:
            for match in _EXCERPT_SENTENCE_RE.finditer(source):
                fragment = re.sub(r"\s+", " ", match.group(0)).strip(" ：:、-—─")
                for sentence in _chunk_review_fragment(fragment):
                    if sentence:
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
        terminal = re.search(r"[。！？!?；;)）]$", previous)
        continues = previous.endswith((",", "，", "、", ":", "：")) or (
            not terminal and (
                len(previous) >= 28
                or (len(previous) >= 6 and len(line) <= 8 and _EXCERPT_CONTINUATION_RE.search(line))
            )
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


def _comment_pool(posts: list[Post]) -> list[str]:
    """Return the single polarity-neutral, mechanically cleaned comment pool."""

    selected: list[str] = []
    seen: set[str] = set()
    for post in posts:
        for comment in post.comments:
            attribution = _comment_attribution(post.brand, comment)
            # Attribution answers only whether the text belongs to this product
            # (for example, not a clearly favoured competing brand). It does not
            # decide whether the comment is useful or which polarity it has.
            if not attribution.include_score:
                continue
            text = _clean_representative_comment(post.brand, comment.text)
            if not text or _is_structural_comment_noise(text):
                continue
            key = re.sub(r"\s+", "", unicodedata.normalize("NFKC", text).casefold())
            if key in seen:
                continue
            seen.add(key)
            selected.append(text)
            if len(selected) >= REP_CANDIDATE_LIMIT:
                return selected
    return selected


def _rule_comment_candidates_with_sentiment(
    posts: list[Post],
) -> list[tuple[str, float | None]]:
    """Attach polarity only after pool construction for the provisional fallback."""

    pool = _comment_pool(posts)
    pool_keys = {
        re.sub(r"\s+", "", unicodedata.normalize("NFKC", text).casefold())
        for text in pool
    }
    selected: list[tuple[str, float | None]] = []
    seen: set[str] = set()
    for post in posts:
        for comment in post.comments:
            attribution = _comment_attribution(post.brand, comment)
            if not attribution.include_score:
                continue
            raw_text = _clean_representative_comment(post.brand, comment.text)
            text = _COMMENT_NOISE_RE.sub(" ", raw_text).strip()
            key = re.sub(r"\s+", "", unicodedata.normalize("NFKC", text).casefold())
            if (
                re.sub(r"\s+", "", unicodedata.normalize("NFKC", raw_text).casefold())
                not in pool_keys
                or key in seen
                or not text
                or _OFF_TOPIC_COMMENT_RE.search(text)
                or _is_reaction_echo_comment(text)
            ):
                continue
            seen.add(key)
            selected.append((text, attribution.effective_sentiment))
    return selected


def _rep_candidates(posts: list[Post]) -> list[str]:
    """Build the complete, polarity-neutral comment pool for the labeler."""

    return _comment_pool(posts)


def _body_candidates(posts: list[Post]) -> list[str]:
    """Build every stable, mechanically cleaned author-sentence candidate."""

    selected: list[str] = []
    for candidate in sorted(
        _review_candidates(posts),
        key=lambda item: (item.post_index, item.sentence_index),
    ):
        rendered = _render_review_sentences([candidate])
        if not rendered or any(_review_sentences_similar(rendered, item) for item in selected):
            continue
        selected.append(rendered)
        if len(selected) >= BODY_CANDIDATE_LIMIT:
            break
    return selected


def _is_structural_comment_noise(text: str) -> bool:
    """Drop only empty, pure-symbol, or explicit board-admin comment noise."""

    without_emoji = re.sub(r"[\U0001F000-\U0001FAFF\u2600-\u27BF]", "", text)
    if not re.search(r"[\u3400-\u9fffA-Za-z0-9]", without_emoji):
        return True
    return bool(re.fullmatch(r"(?:板務|版務|公告|置底|板規|版規|推文標記)", text))


def _body_highlights(
    posts: list[Post],
    *,
    positive: bool,
    exclude: list[str],
    excerpt: str,
    k: int,
) -> list[str]:
    """Return provisional rule-selected author sentences for one polarity.

    This rule fallback can select a sentence about a thread-mate because split
    products retain the whole post body. The per-product body label is the fix;
    this remains only for newly crawled, unlabelled products.
    """
    if k <= 0:
        return []
    highlights: list[str] = []
    for candidate in sorted(
        _rule_review_candidates(posts),
        key=lambda item: (-item.score, item.post_index, item.sentence_index, item.text),
    ):
        text = candidate.text
        positive_hits = sum(
            text.casefold().count(word.casefold())
            for word in POSITIVE_WORDS
            if len(word) >= 2
        )
        negative_hits = sum(
            text.casefold().count(word.casefold())
            for word in NEGATIVE_WORDS
            if len(word) >= 2
        )
        if positive_hits == negative_hits or (positive_hits > negative_hits) != positive:
            continue
        if _review_sentences_similar(text, excerpt) or any(
            _review_sentences_similar(text, item) for item in exclude + highlights
        ):
            continue
        rendered = _render_review_sentences([candidate])
        if rendered:
            highlights.append(rendered)
        if len(highlights) >= k:
            break
    return highlights


def _picked_sentences(
    candidates: list[str],
    picks: tuple[int, ...],
    *,
    excerpt: str,
    exclude: list[str],
) -> list[str]:
    """Map stored indices while suppressing excerpt and cross-polarity repeats."""
    selected: list[str] = []
    excluded_keys = {
        re.sub(r"\s+", "", unicodedata.normalize("NFKC", item).casefold())
        for item in exclude
    }
    for index in picks:
        if not 0 <= index < len(candidates):
            continue
        text = candidates[index]
        key = re.sub(r"\s+", "", unicodedata.normalize("NFKC", text).casefold())
        if _review_sentences_similar(text, excerpt) or key in excluded_keys:
            continue
        selected.append(text)
        excluded_keys.add(key)
    return selected


def _rule_comment_highlights(
    posts: list[Post],
    *,
    positive: bool,
    exclude: list[str],
    excerpt: str,
    k: int,
) -> list[str]:
    """Choose comments by sentiment only as a provisional no-label fallback."""

    if k <= 0:
        return []
    highlights: list[str] = []
    excluded_keys = {
        re.sub(r"\s+", "", unicodedata.normalize("NFKC", item).casefold())
        for item in exclude
    }
    for text, sentiment in _rule_comment_candidates_with_sentiment(posts):
        if sentiment is None or sentiment == 0 or (sentiment > 0) != positive:
            continue
        key = re.sub(r"\s+", "", unicodedata.normalize("NFKC", text).casefold())
        if _review_sentences_similar(text, excerpt) or key in excluded_keys:
            continue
        highlights.append(text)
        excluded_keys.add(key)
        if len(highlights) >= k:
            break
    return highlights


def _rewritten_texts(
    rewrites: tuple[Rewrite, ...], *, excerpt: str, exclude: list[str]
) -> list[str]:
    """Render validated model rewrites while keeping UI de-duplication."""

    selected: list[str] = []
    for item in rewrites:
        text = item.text
        if not text or _review_sentences_similar(text, excerpt) or any(
            _review_sentences_similar(text, other) for other in exclude + selected
        ):
            continue
        selected.append(text)
    return selected


def _rep_comments_with_provenance(
    posts: list[Post],
    k: int = 3,
    *,
    excerpt: str = "",
) -> tuple[list[str], list[str], bool]:
    comments = _rep_candidates(posts)
    body = _body_candidates(posts)
    brand = posts[0].brand if posts else ""
    product_name = representative_product_name(posts)
    cache = _cached_comment_picks()
    picks = cache.get(
        comment_picks_fingerprint_v2(
            brand,
            product_name,
            comments,
            body,
            other_products=other_products_for_group(posts),
        )
    )

    if picks is not None:
        rep_positive = _rewritten_texts(picks.positive, excerpt=excerpt, exclude=[])
        rep_negative = _rewritten_texts(
            picks.negative, excerpt=excerpt, exclude=rep_positive
        )
        if not rep_positive:
            rep_positive = _rewritten_texts(
                picks.positive_body, excerpt=excerpt, exclude=rep_negative
            )
        if not rep_negative:
            rep_negative = _rewritten_texts(
                picks.negative_body,
                excerpt=excerpt,
                exclude=rep_positive,
            )
        return rep_positive, rep_negative, False

    rep_positive = _rule_comment_highlights(
        posts, positive=True, exclude=[], excerpt=excerpt, k=k
    )
    rep_negative = _rule_comment_highlights(
        posts, positive=False, exclude=rep_positive, excerpt=excerpt, k=k
    )
    if not rep_positive:
        rep_positive = _body_highlights(
            posts, positive=True, exclude=rep_negative, excerpt=excerpt, k=k
        )
    if not rep_negative:
        rep_negative = _body_highlights(
            posts, positive=False, exclude=rep_positive, excerpt=excerpt, k=k
        )
    return rep_positive, rep_negative, True


def _rep_comments(
    posts: list[Post],
    k: int = 3,
    *,
    excerpt: str = "",
) -> tuple[list[str], list[str]]:
    return _rep_comments_with_provenance(posts, k=k, excerpt=excerpt)[:2]


def representative_product_name(posts: list[Post]) -> str:
    """選出代表性商品名稱。"""
    if not posts:
        return "unknown"
    names = [canonical_product_name(posts[0].brand, post.product_name) for post in posts]
    counts = Counter(names)
    return min(counts, key=lambda name: (-counts[name], -len(name), name))


def _clean_representative_comment(brand: str, text: str) -> str:
    s = unicodedata.normalize("NFKC", text or "").strip()
    # Strip links here rather than at publish time: the candidate pool is what the
    # labeller reads and what the pick fingerprint is computed over, so a comment
    # that is nothing but an image link has to collapse to "" and drop out now,
    # instead of being pickable and then rendering as a blank bullet.
    s = _FULL_URL_RE.sub(" ", s)
    for kw in sorted(set([*BRANDS.get(brand, []), brand]), key=len, reverse=True):
        if kw:
            # Only remove a store name when it is a label-like prefix. Brand names
            # inside a sentence carry meaning (e.g. "全家的甜品" / "我買全家的時候").
            pattern = rf"^{re.escape(kw)}(?=[\s:：])[\s:：]*"
            s = re.sub(pattern, "", s, count=1, flags=re.IGNORECASE)
    s = _BRACKET_RE.sub(" ", s)
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
