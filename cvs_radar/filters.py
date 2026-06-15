"""Reusable time-window filtering for posts and comments."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta

from .models import Comment, Post


@dataclass(frozen=True, slots=True)
class TimeWindow:
    """Inclusive datetime window used by crawler, pipeline, and services."""

    start: datetime | None = None
    end: datetime | None = None

    @property
    def enabled(self) -> bool:
        return self.start is not None or self.end is not None

    def contains(self, value: datetime | None) -> bool:
        if not self.enabled:
            return True
        if value is None:
            return False
        if self.start is not None and _datetime_lt(value, self.start):
            return False
        if self.end is not None and _datetime_gt(value, self.end):
            return False
        return True


def parse_datetime(value: str | date | datetime | None, *, end_of_day: bool = False) -> datetime | None:
    """Parse common CLI/API date inputs.

    Date-only values are expanded to the start of day by default, or the end of
    day when ``end_of_day`` is true so end-date filters are inclusive.
    """

    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time.max if end_of_day else time.min)

    text = str(value).strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        for fmt in ("%Y/%m/%d", "%Y%m%d"):
            try:
                parsed_date = datetime.strptime(text, fmt).date()
                return datetime.combine(parsed_date, time.max if end_of_day else time.min)
            except ValueError:
                continue
        raise ValueError(f"invalid date/datetime: {value!r}") from None

    if parsed.hour == parsed.minute == parsed.second == parsed.microsecond == 0 and "T" not in text and " " not in text:
        return datetime.combine(parsed.date(), time.max if end_of_day else time.min)
    return parsed


def build_time_window(
    *,
    start_date: str | date | datetime | None = None,
    end_date: str | date | datetime | None = None,
    recent_days: int | None = None,
    now: datetime | None = None,
) -> TimeWindow:
    """Build an inclusive time window from explicit dates or recent N days."""

    if recent_days is not None:
        if recent_days < 0:
            raise ValueError("recent_days must be non-negative")
        anchor = now or datetime.now()
        return TimeWindow(start=anchor - timedelta(days=recent_days), end=anchor)

    start = parse_datetime(start_date, end_of_day=False)
    end = parse_datetime(end_date, end_of_day=True)
    if start is not None and end is not None and _datetime_gt(start, end):
        raise ValueError("start_date must be earlier than or equal to end_date")
    return TimeWindow(start=start, end=end)


def filter_posts_by_time(
    posts: list[Post],
    *,
    start_date: str | date | datetime | None = None,
    end_date: str | date | datetime | None = None,
    recent_days: int | None = None,
    now: datetime | None = None,
) -> list[Post]:
    """Return cloned posts with comments constrained to the requested window.

    A post is retained when the post itself is in the window, or when at least
    one of its comments is in the window. If only comments match, author score is
    cleared so an old review does not affect the selected time range.
    """

    window = build_time_window(
        start_date=start_date,
        end_date=end_date,
        recent_days=recent_days,
        now=now,
    )
    if not window.enabled:
        return [_clone_post(post) for post in posts]
    return [post for post in (filter_post_by_time(post, window) for post in posts) if post is not None]


def filter_post_by_time(post: Post, window: TimeWindow) -> Post | None:
    if not window.enabled:
        return _clone_post(post)

    post_in_range = window.contains(post.posted_at)
    comments = [
        comment
        for comment in post.comments
        if window.contains(comment.posted_at) or (post_in_range and comment.posted_at is None)
    ]
    if not post_in_range and not comments:
        return None

    cloned_comments = [_clone_comment(comment) for comment in comments]
    if post_in_range:
        return replace(post, comments=cloned_comments)

    return replace(
        post,
        author_score=None,
        review_text="",
        comments=cloned_comments,
    )


def _clone_post(post: Post) -> Post:
    return replace(post, comments=[_clone_comment(comment) for comment in post.comments])


def _clone_comment(comment: Comment) -> Comment:
    return replace(comment)


def _datetime_lt(left: datetime, right: datetime) -> bool:
    left_value, right_value = _comparable_datetimes(left, right)
    return left_value < right_value


def _datetime_gt(left: datetime, right: datetime) -> bool:
    left_value, right_value = _comparable_datetimes(left, right)
    return left_value > right_value


def _comparable_datetimes(left: datetime, right: datetime) -> tuple[datetime, datetime]:
    if _is_aware(left) and _is_aware(right):
        return left, right
    return _drop_tz(left), _drop_tz(right)


def _is_aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _drop_tz(value: datetime) -> datetime:
    return value.replace(tzinfo=None)
