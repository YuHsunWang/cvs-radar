"""PTT crawler with retry, delay, and incremental URL cache for PRD F1."""

from __future__ import annotations

import json
import logging
import time
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse

import requests

from .config import CRAWL
from .filters import build_time_window, filter_post_by_time
from .models import Post
from .parser import parse_ptt_article, parse_ptt_list, parse_push_count

logger = logging.getLogger(__name__)


class PttCrawler:
    """爬取 PTT CVS 文章並轉成貼文資料。"""

    def __init__(
        self,
        base_url: str | None = None,
        request_delay_sec: float | None = None,
        timeout_sec: float | None = None,
        retries: int | None = None,
        cache_path: str | Path | None = None,
    ) -> None:
        self.base_url = base_url or CRAWL["base_url"]
        self.request_delay_sec = float(request_delay_sec if request_delay_sec is not None else CRAWL["request_delay_sec"])
        self.timeout_sec = float(timeout_sec if timeout_sec is not None else CRAWL["timeout_sec"])
        self.retries = int(retries if retries is not None else CRAWL["retries"])
        self.cache_path = Path(cache_path or CRAWL["cache_path"])
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": str(CRAWL["user_agent"])})
        self.session.cookies.set("over18", "1", domain="www.ptt.cc")
        self._base_origin = urlparse(self.base_url)
        self.seen_urls = self._load_seen()

    def crawl(
        self,
        max_pages: int | None = None,
        board: str | None = None,
        *,
        start_date: str | date | datetime | None = None,
        end_date: str | date | datetime | None = None,
        recent_days: int | None = None,
        now: datetime | None = None,
    ) -> list[Post]:
        """爬取指定頁數內的商品貼文。"""
        board = board or str(CRAWL["board"])
        max_pages = int(max_pages if max_pages is not None else CRAWL["max_pages"])
        window = build_time_window(
            start_date=start_date,
            end_date=end_date,
            recent_days=recent_days,
            now=now,
        )
        url = f"{self.base_url}/bbs/{board}/index.html"
        posts: list[Post] = []

        for _ in range(max_pages):
            html = self._get(url)
            items, prev_url = parse_ptt_list(html, self.base_url)
            for item in items:
                article_url = item["url"]
                if not self._is_allowed_url(article_url):
                    logger.warning("skipping off-site article URL: %s", article_url)
                    continue
                if article_url in self.seen_urls:
                    continue
                try:
                    article = self._get(article_url)
                    post = parse_ptt_article(article, article_url, board)
                except Exception as exc:  # keep batch running when one article fails
                    logger.warning("failed to parse %s: %s", article_url, exc)
                    continue
                if post is None:
                    self.seen_urls.add(article_url)
                    continue
                post.push_count = parse_push_count(item.get("push_count"))
                filtered_post = filter_post_by_time(post, window)
                if filtered_post is not None:
                    self.seen_urls.add(article_url)
                    posts.append(filtered_post)
            if not prev_url:
                break
            if not self._is_allowed_url(prev_url):
                logger.warning("stopping crawl at off-site pagination URL: %s", prev_url)
                break
            url = prev_url

        self._save_seen()
        return posts

    def _get(self, url: str) -> str:
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            if attempt > 0:
                time.sleep(min(30.0, self.request_delay_sec * (2 ** attempt)))
            try:
                response = self.session.get(url, timeout=self.timeout_sec)
                response.raise_for_status()
                time.sleep(self.request_delay_sec)
                return response.text
            except requests.RequestException as exc:
                last_error = exc
                logger.warning("request failed (%s/%s) %s: %s", attempt + 1, self.retries + 1, url, exc)
        assert last_error is not None
        raise last_error

    def _is_allowed_url(self, url: str) -> bool:
        parsed = urlparse(url)
        return (
            parsed.scheme in {"http", "https"}
            and parsed.netloc == self._base_origin.netloc
            and parsed.path.startswith("/bbs/")
        )

    def _load_seen(self) -> set[str]:
        if not self.cache_path.exists():
            return set()
        try:
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
            return set(data if isinstance(data, list) else [])
        except (OSError, json.JSONDecodeError):
            logger.warning("cannot read cache %s; starting with empty cache", self.cache_path)
            return set()

    def _save_seen(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(
            json.dumps(sorted(self.seen_urls), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
