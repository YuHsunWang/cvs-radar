"""JSONL persistence for posts and precomputed result objects."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from fcntl import LOCK_EX, LOCK_SH, flock
from pathlib import Path

from .filters import normalize_datetime, parse_datetime
from .models import Comment, Contributor, Post, ProductReport
from .parser import infer_brand
from .preference import AccountProfile, BrandStat

DEFAULT_STORE_PATH = "data/posts.jsonl"
DEFAULT_RESULTS_PATH = "data/results.json"


class StoreReadError(ValueError):
    """The raw JSONL store contains a line no publishing stage may ignore."""


def post_to_dict(post: Post) -> dict:
    """Serialize a Post to a JSON-safe dict."""
    return {
        "id": post.id,
        "source": post.source,
        "board": post.board,
        "url": post.url,
        "title": post.title,
        "brand": post.brand,
        "product_name": post.product_name,
        "price": post.price,
        "author": post.author,
        "author_score": post.author_score,
        "review_text": post.review_text,
        "posted_at": post.posted_at.isoformat() if post.posted_at else None,
        "is_reply": post.is_reply,
        "push_count": post.push_count,
        "raw": post.raw,
        "comments": [
            {
                "tag": c.tag,
                "user": c.user,
                "text": c.text,
                "posted_at": c.posted_at.isoformat() if c.posted_at else None,
                "sentiment": c.sentiment,
                "backend": c.backend,
            }
            for c in post.comments
        ],
    }


def dict_to_post(data: dict) -> Post:
    """Deserialize a dict back to a Post."""
    comments = [
        Comment(
            tag=c["tag"],
            user=c["user"],
            text=c["text"],
            posted_at=_stored_datetime(c["posted_at"]) if c.get("posted_at") else None,
            sentiment=c.get("sentiment"),
            backend=c.get("backend", ""),
        )
        for c in data.get("comments", [])
    ]
    raw = data.get("raw") or {}
    fields = raw.get("fields") if isinstance(raw, dict) else {}
    vendor = _first_stored_field(fields or {}, "便利商店/廠商名稱", "便利商店", "廠商名稱", "商店")
    authoritative_brand = infer_brand(vendor or "", data.get("title", ""))
    brand = authoritative_brand if authoritative_brand != "其他" else data.get("brand", "其他")
    return Post(
        id=data["id"],
        source=data.get("source", "PTT"),
        board=data.get("board", "CVS"),
        url=data.get("url", ""),
        title=data.get("title", ""),
        brand=brand,
        product_name=data.get("product_name", ""),
        price=data.get("price"),
        author=data.get("author", ""),
        author_score=data.get("author_score"),
        review_text=data.get("review_text", ""),
        posted_at=_stored_datetime(data["posted_at"]) if data.get("posted_at") else None,
        is_reply=data.get("is_reply", False),
        push_count=data.get("push_count"),
        raw=raw,
        comments=comments,
    )


def _stored_datetime(value: object) -> datetime:
    parsed = parse_datetime(str(value))
    if parsed is None:
        raise ValueError(f"invalid stored datetime: {value!r}")
    return normalize_datetime(parsed)


def _first_stored_field(fields: dict, *keys: str) -> str | None:
    for key in keys:
        compact = "".join(str(key).split())
        if compact in fields and fields[compact]:
            return str(fields[compact])
    for key, value in fields.items():
        if any(token in str(key) for token in keys) and value:
            return str(value)
    return None


def save_posts(posts: list[Post], path: str | Path = DEFAULT_STORE_PATH) -> int:
    """Append posts to a JSONL file. Returns number of NEW posts written."""
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)

    with file_path.open("a+", encoding="utf-8") as handle:
        flock(handle.fileno(), LOCK_EX)
        handle.seek(0)
        existing_lines = handle.readlines()
        existing_ids = {
            str(row["id"]) for row in _load_post_rows_from_lines(existing_lines, file_path)
        }
        needs_separator = bool(existing_lines and not existing_lines[-1].endswith("\n"))
        handle.seek(0, os.SEEK_END)
        new_count = 0
        for post in posts:
            if post.id in existing_ids:
                continue
            if needs_separator:
                handle.write("\n")
                needs_separator = False
            handle.write(json.dumps(post_to_dict(post), ensure_ascii=False) + "\n")
            existing_ids.add(post.id)
            new_count += 1
        if new_count:
            handle.flush()
            os.fsync(handle.fileno())
    return new_count


def load_posts(path: str | Path = DEFAULT_STORE_PATH) -> list[Post]:
    """Load all posts from a JSONL file. Deduplicates by post id."""
    file_path = Path(path)
    if not file_path.exists():
        return []

    with file_path.open(encoding="utf-8") as handle:
        flock(handle.fileno(), LOCK_SH)
        return [
            dict_to_post(row)
            for row in _load_post_rows_from_lines(handle.readlines(), file_path)
        ]


def load_post_rows(path: str | Path = DEFAULT_STORE_PATH) -> list[dict]:
    """Strictly load validated raw rows, keeping the latest valid duplicate ID."""
    file_path = Path(path)
    if not file_path.exists():
        return []
    with file_path.open(encoding="utf-8") as handle:
        flock(handle.fileno(), LOCK_SH)
        return _load_post_rows_from_lines(handle.readlines(), file_path)


def _load_post_rows_from_lines(lines: list[str], file_path: Path) -> list[dict]:
    latest: dict[str, tuple[int, dict]] = {}
    errors: list[str] = []
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
            if not isinstance(data, dict):
                raise TypeError("row must be a JSON object")
            post_id = str(data["id"])
            dict_to_post(data)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError, AttributeError) as exc:
            truncated = line_number == len(lines) and not raw_line.endswith("\n")
            description = "truncated final" if truncated else "invalid"
            errors.append(f"line {line_number} ({description}: {exc})")
            continue
        latest[post_id] = (line_number, data)
    if errors:
        raise StoreReadError(
            f"{file_path}: invalid JSONL store; " + "; ".join(errors)
        )
    return [row for _, row in sorted(latest.values(), key=lambda item: item[0])]


def store_stats(path: str | Path = DEFAULT_STORE_PATH) -> dict:
    """Return basic stats about the stored data."""
    posts = load_posts(path)
    brands = set(p.brand for p in posts)
    date_range = None
    dates = [p.posted_at for p in posts if p.posted_at]
    if dates:
        date_range = (min(dates).isoformat(), max(dates).isoformat())
    return {
        "path": str(path),
        "post_count": len(posts),
        "comment_count": sum(len(p.comments) for p in posts),
        "brands": sorted(brands),
        "date_range": date_range,
    }


def report_to_store_dict(report: ProductReport) -> dict:
    """Serialize a ProductReport for storage."""
    return {
        "brand": report.brand,
        "product_name": report.product_name,
        "fair_score": report.fair_score,
        "consensus": report.consensus,
        "confidence": report.confidence,
        "n_eff": report.n_eff,
        "score_std": report.score_std,
        "n_posts": report.n_posts,
        "n_comments": report.n_comments,
        "n_eligible_comments": report.n_eligible_comments,
        "n_unique_commenters": report.n_unique_commenters,
        "score_weight_sum": report.score_weight_sum,
        "score_weighted_sum": report.score_weighted_sum,
        "score_weight_square_sum": report.score_weight_square_sum,
        "positive_weight": report.positive_weight,
        "neutral_weight": report.neutral_weight,
        "negative_weight": report.negative_weight,
        "contributors": [
            {"user": c.user, "role": c.role, "score": c.score, "weight": c.weight}
            for c in report.contributors
        ],
        "rep_positive": report.rep_positive,
        "rep_negative": report.rep_negative,
        "product_key": report.product_key,
        "score_mean": report.score_mean,
        "price": report.price,
        "category": report.category,
        "competitor_mention_count": report.competitor_mention_count,
        "competitor_preference_count": report.competitor_preference_count,
        "competitor_own_preference_count": report.competitor_own_preference_count,
        "competitor_brands": report.competitor_brands,
        "shill_ratio": report.shill_ratio,
        "shill_flag": report.shill_flag,
        "latest_post_date": report.latest_post_date.isoformat() if report.latest_post_date else None,
        "review_excerpt": report.review_excerpt,
        "post_urls": report.post_urls,
    }


def store_dict_to_report(data: dict) -> ProductReport:
    """Deserialize a stored dict back to ProductReport."""
    contributors = [
        Contributor(
            user=c["user"],
            role=c["role"],
            score=c["score"],
            weight=c["weight"],
        )
        for c in data.get("contributors", [])
    ]
    return ProductReport(
        brand=data["brand"],
        product_name=data["product_name"],
        fair_score=data.get("fair_score"),
        consensus=data["consensus"],
        confidence=data["confidence"],
        n_eff=data["n_eff"],
        score_std=data["score_std"],
        n_posts=data["n_posts"],
        n_comments=data["n_comments"],
        n_eligible_comments=data.get("n_eligible_comments", data["n_comments"]),
        n_unique_commenters=data.get("n_unique_commenters", data["n_comments"]),
        score_weight_sum=data.get("score_weight_sum", 0.0),
        score_weighted_sum=data.get("score_weighted_sum", 0.0),
        score_weight_square_sum=data.get("score_weight_square_sum", 0.0),
        positive_weight=data.get("positive_weight", 0.0),
        neutral_weight=data.get("neutral_weight", 0.0),
        negative_weight=data.get("negative_weight", 0.0),
        contributors=contributors,
        rep_positive=data.get("rep_positive", []),
        rep_negative=data.get("rep_negative", []),
        product_key=data.get("product_key", ""),
        score_mean=data.get("score_mean", 0.0),
        price=data.get("price"),
        category=data.get("category", ""),
        competitor_mention_count=data.get("competitor_mention_count", 0),
        competitor_preference_count=data.get("competitor_preference_count", 0),
        competitor_own_preference_count=data.get("competitor_own_preference_count", 0),
        competitor_brands=data.get("competitor_brands", []),
        shill_ratio=data.get("shill_ratio", 0.0),
        shill_flag=data.get("shill_flag", False),
        latest_post_date=_stored_datetime(data["latest_post_date"]) if data.get("latest_post_date") else None,
        review_excerpt=data.get("review_excerpt", ""),
        post_urls=data.get("post_urls", []),
    )


def profile_to_store_dict(profile: AccountProfile) -> dict:
    """Serialize an AccountProfile for storage."""
    return {
        "user": profile.user,
        "source": profile.source,
        "brand_stats": {
            brand: {"count": stat.count, "avg_sentiment": stat.avg_sentiment}
            for brand, stat in profile.brand_stats.items()
        },
        "lean_brand": profile.lean_brand,
        "suspicion_score": profile.suspicion_score,
        "suspicion_features": profile.suspicion_features,
        "credibility": profile.credibility,
        "total_comments": profile.total_comments,
    }


def store_dict_to_profile(data: dict) -> AccountProfile:
    """Deserialize a stored dict back to AccountProfile."""
    brand_stats = {
        brand: BrandStat(count=s["count"], avg_sentiment=s["avg_sentiment"])
        for brand, s in data.get("brand_stats", {}).items()
    }
    return AccountProfile(
        user=data["user"],
        source=data.get("source", "PTT"),
        brand_stats=brand_stats,
        lean_brand=data.get("lean_brand"),
        suspicion_score=data.get("suspicion_score", 0.0),
        suspicion_features=data.get("suspicion_features", {}),
        credibility=data.get("credibility", 1.0),
        total_comments=data.get("total_comments", 0),
    )


def save_results(
    reports: list[ProductReport],
    profiles: dict[str, AccountProfile],
    path: str | Path = DEFAULT_RESULTS_PATH,
) -> None:
    """Atomically save a publishable snapshot without account identities."""
    file_path = Path(path)
    public_reports = [report_to_store_dict(report) for report in reports]
    for report in public_reports:
        report["contributors"] = []
    payload = {
        "generated_at": datetime.now().isoformat(sep=" ", timespec="seconds"),
        "reports": public_reports,
        "profiles": [],
    }
    validate_publishable_results(payload)
    write_json_atomic(file_path, payload)


def validate_publishable_results(payload: dict) -> None:
    """Reject identity-bearing or malformed content before publishing results."""
    if payload.get("profiles") != [] or not isinstance(payload.get("reports"), list):
        raise ValueError("publishable results require reports and an empty profiles list")

    def visit(value: object) -> None:
        if isinstance(value, list):
            for item in value:
                visit(item)
            return
        if not isinstance(value, dict):
            return
        for key, nested in value.items():
            if key == "user" or key.startswith("suspicion_"):
                raise ValueError(f"publishable results contain identity field {key!r}")
            if key in {"contributors", "profiles"} and nested != []:
                raise ValueError(f"publishable results contain non-empty {key}")
            visit(nested)

    visit(payload)


def write_json_atomic(path: str | Path, payload: dict) -> None:
    """Write complete JSON to a sibling temp file, fsync, then replace."""
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=file_path.parent,
            prefix=f".{file_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, file_path)
    except Exception:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise


def load_results(
    path: str | Path = DEFAULT_RESULTS_PATH,
) -> tuple[list[ProductReport], dict[str, AccountProfile]] | None:
    """Load precomputed results. Returns None if file doesn't exist."""
    file_path = Path(path)
    if not file_path.exists():
        return None
    data = json.loads(file_path.read_text(encoding="utf-8"))
    reports = [store_dict_to_report(r) for r in data.get("reports", [])]
    profiles = {
        p["user"]: store_dict_to_profile(p)
        for p in data.get("profiles", [])
    }
    return reports, profiles
