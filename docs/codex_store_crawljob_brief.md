# Codex 任務：資料持久化 + 定期爬蟲機制

> Claude 已拍板。Codex 執行，完成後 Claude 獨立驗證。**先單獨跑測試確認綠燈再 commit（勿串同條指令）。**

## 背景

目前 cvs-radar 的爬蟲資料只存在記憶體，app 關了就沒了。要讓系統能持續運行、累積資料，需要：

1. **持久化層**：把爬下來的 Post 存到 JSONL 檔案，下次啟動時載入
2. **爬蟲排程腳本**：可單獨執行或用 cron 定期跑的腳本

## 任務 A：建立 `cvs_radar/store.py`

新增 JSONL 格式的 Post 讀寫模組。

### A1：序列化

```python
"""JSONL persistence for Post objects."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .models import Comment, Post

DEFAULT_STORE_PATH = "data/posts.jsonl"


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
        "comments": [
            {
                "tag": c.tag,
                "user": c.user,
                "text": c.text,
                "posted_at": c.posted_at.isoformat() if c.posted_at else None,
                "sentiment": c.sentiment,
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
            posted_at=datetime.fromisoformat(c["posted_at"]) if c.get("posted_at") else None,
            sentiment=c.get("sentiment"),
        )
        for c in data.get("comments", [])
    ]
    return Post(
        id=data["id"],
        source=data.get("source", "PTT"),
        board=data.get("board", "CVS"),
        url=data.get("url", ""),
        title=data.get("title", ""),
        brand=data.get("brand", "其他"),
        product_name=data.get("product_name", ""),
        price=data.get("price"),
        author=data.get("author", ""),
        author_score=data.get("author_score"),
        review_text=data.get("review_text", ""),
        posted_at=datetime.fromisoformat(data["posted_at"]) if data.get("posted_at") else None,
        is_reply=data.get("is_reply", False),
        push_count=data.get("push_count"),
        comments=comments,
    )
```

### A2：讀寫函式

```python
def save_posts(posts: list[Post], path: str | Path = DEFAULT_STORE_PATH) -> int:
    """Append posts to a JSONL file. Returns number of NEW posts written (skip duplicates by id)."""
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)

    existing_ids = set()
    if file_path.exists():
        existing_ids = {post.id for post in load_posts(path)}

    new_count = 0
    with open(file_path, "a", encoding="utf-8") as f:
        for post in posts:
            if post.id in existing_ids:
                continue
            f.write(json.dumps(post_to_dict(post), ensure_ascii=False) + "\n")
            existing_ids.add(post.id)
            new_count += 1
    return new_count


def load_posts(path: str | Path = DEFAULT_STORE_PATH) -> list[Post]:
    """Load all posts from a JSONL file. Deduplicates by post id (keeps first occurrence)."""
    file_path = Path(path)
    if not file_path.exists():
        return []

    seen_ids: set[str] = set()
    posts: list[Post] = []
    for line in file_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        data = json.loads(line)
        if data["id"] in seen_ids:
            continue
        seen_ids.add(data["id"])
        posts.append(dict_to_post(data))
    return posts


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
```

## 任務 B：建立 `crawl_job.py`

在專案根目錄新增可獨立執行的爬蟲排程腳本：

```python
#!/usr/bin/env python3
"""Scheduled crawl job — run standalone or via cron.

Usage:
    # 手動執行
    python crawl_job.py

    # 指定頁數和存檔路徑
    python crawl_job.py --pages 10 --store data/posts.jsonl

    # cron 每天早上 8 點跑（加到 crontab -e）
    # 0 8 * * * cd /path/to/cvs-radar && .venv/bin/python crawl_job.py >> logs/crawl.log 2>&1
"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime
from pathlib import Path

from cvs_radar.crawler import PttCrawler
from cvs_radar.store import DEFAULT_STORE_PATH, save_posts, store_stats


def main() -> None:
    parser = argparse.ArgumentParser(description="CVS Radar scheduled crawl job")
    parser.add_argument("--pages", type=int, default=5, help="Number of PTT list pages to crawl (default: 5)")
    parser.add_argument("--store", default=DEFAULT_STORE_PATH, help=f"JSONL store path (default: {DEFAULT_STORE_PATH})")
    parser.add_argument("--recent-days", type=int, default=None, help="Only keep posts from recent N days")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger = logging.getLogger("crawl_job")

    logger.info("Starting crawl: pages=%d, store=%s", args.pages, args.store)
    start = datetime.now()

    try:
        crawler = PttCrawler()
        posts = crawler.crawl(
            max_pages=args.pages,
            recent_days=args.recent_days,
        )
    except Exception:
        logger.exception("Crawl failed")
        raise

    new_count = save_posts(posts, args.store)
    elapsed = (datetime.now() - start).total_seconds()
    stats = store_stats(args.store)

    logger.info(
        "Crawl complete: fetched=%d, new=%d, elapsed=%.1fs", len(posts), new_count, elapsed
    )
    # 總是印摘要，不管 log level
    print(
        f"[{datetime.now().isoformat(sep=' ', timespec='seconds')}] "
        f"crawled={len(posts)} new={new_count} "
        f"store_total={stats['post_count']} posts / {stats['comment_count']} comments "
        f"({elapsed:.1f}s)"
    )


if __name__ == "__main__":
    main()
```

## 任務 C：整合到 app 和 CLI

### C1：修改 `cvs_radar/app_helpers.py`

在 `SourceName` 加入 `"stored"`：

```python
SourceName = Literal["demo", "crawl", "stored"]
```

在 `load_posts()` 加入 `stored` 分支：

```python
if source == "stored":
    from .store import load_posts as load_stored
    return load_stored()
```

### C2：修改 `app.py`

在 `_render_sidebar()` 的 `source_label` radio 加入第三個選項：

```python
source_label = st.radio("資料來源", ["demo 離線樣本", "stored 已爬取資料", "crawl PTT CVS"], index=0)
source = "demo" if source_label.startswith("demo") else ("stored" if source_label.startswith("stored") else "crawl")
```

當 source 是 `"stored"` 時，顯示 store stats：

```python
if source == "stored":
    from cvs_radar.store import store_stats
    stats = store_stats()
    st.info(f"已載入 {stats['post_count']} 篇文 / {stats['comment_count']} 則留言")
```

### C3：修改 `run.py`

在 source group 加入 `--stored`：

```python
source.add_argument("--stored", action="store_true", help="Use stored crawl data from JSONL")
```

在 `_load_posts()` 加入 stored 分支：

```python
if args.stored:
    from cvs_radar.store import load_posts as load_stored
    posts = load_stored()
    print(f"Loaded {len(posts)} posts from store")
    return posts
```

## 任務 D：建立 `data/` 目錄和 .gitignore

```bash
mkdir -p data
```

建立 `data/.gitignore`：

```
# 爬蟲資料不進 git（太大且含帳號資料）
*.jsonl
!.gitignore
```

## 任務 E：測試

在 `tests/test_core.py` 或新建 `tests/test_store.py` 新增：

```python
class StoreTest(unittest.TestCase):
    def test_roundtrip_post_with_comments(self) -> None:
        """Post → dict → Post preserves all fields."""
        from cvs_radar.store import post_to_dict, dict_to_post
        from cvs_radar.models import Post, Comment
        from datetime import datetime

        original = Post(
            id="test-1",
            source="PTT",
            brand="7-11",
            product_name="測試飯糰",
            author="tester",
            author_score=85,
            posted_at=datetime(2026, 6, 1, 12, 0),
            comments=[
                Comment("推", "alice", "好吃", datetime(2026, 6, 1, 12, 10)),
                Comment("噓", "bob", "普通", None),
            ],
        )
        restored = dict_to_post(post_to_dict(original))
        self.assertEqual(restored.id, original.id)
        self.assertEqual(restored.brand, original.brand)
        self.assertEqual(restored.author_score, original.author_score)
        self.assertEqual(restored.posted_at, original.posted_at)
        self.assertEqual(len(restored.comments), 2)
        self.assertEqual(restored.comments[0].text, "好吃")
        self.assertIsNone(restored.comments[1].posted_at)

    def test_save_and_load_deduplicates(self) -> None:
        """save_posts skips duplicates; load_posts deduplicates by id."""
        from tempfile import TemporaryDirectory
        from pathlib import Path
        from cvs_radar.store import save_posts, load_posts
        from cvs_radar.models import Post

        post = Post(id="dup-1", brand="7-11", product_name="Test", author="a")

        with TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "test.jsonl"
            n1 = save_posts([post], store_path)
            n2 = save_posts([post], store_path)  # duplicate
            loaded = load_posts(store_path)

            self.assertEqual(n1, 1)
            self.assertEqual(n2, 0)
            self.assertEqual(len(loaded), 1)

    def test_save_creates_parent_directory(self) -> None:
        from tempfile import TemporaryDirectory
        from pathlib import Path
        from cvs_radar.store import save_posts
        from cvs_radar.models import Post

        with TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "nested" / "deep" / "test.jsonl"
            save_posts([Post(id="dir-1", brand="7-11", product_name="Test", author="a")], store_path)
            self.assertTrue(store_path.exists())

    def test_load_from_nonexistent_returns_empty(self) -> None:
        from cvs_radar.store import load_posts
        self.assertEqual(load_posts("/tmp/does_not_exist_xyz.jsonl"), [])

    def test_stored_posts_flow_through_pipeline(self) -> None:
        """Posts saved and loaded from store produce valid pipeline output."""
        from tempfile import TemporaryDirectory
        from pathlib import Path
        from cvs_radar.store import save_posts, load_posts
        from cvs_radar.pipeline import run_pipeline
        from cvs_radar.models import Post, Comment

        post = Post(
            id="pipe-1", brand="全家", product_name="雞肉飯糰",
            author="u1", author_score=80,
            comments=[Comment("推", "u2", "好吃會回購")],
        )

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.jsonl"
            save_posts([post], path)
            loaded = load_posts(path)
            reports, profiles = run_pipeline(loaded)

            self.assertEqual(len(reports), 1)
            self.assertIsNotNone(reports[0].fair_score)
```

## 驗收

- 所有既有測試 + 新測試全過
- `store.py` 的 roundtrip 正確（Post → JSONL → Post 無損）
- `save_posts` 不重複寫入相同 id
- `crawl_job.py` 可用 `--help` 正常顯示（不需真正爬 PTT）
- app.py 的 `stored` 選項不會 crash（即使 data/posts.jsonl 不存在也能 graceful handle）
- `data/.gitignore` 存在且排除 JSONL
- 只改指定的檔案，不動其他模組
- 先跑測試確認綠燈再 commit，不要 push
