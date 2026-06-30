"""PTT CVS parser for PRD F2 and §7 edge cases."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta

from bs4 import BeautifulSoup

from .config import BRANDS
from .models import Comment, Post

FIELD_RE = re.compile(r"【\s*(?P<key>[^】\n]+?)\s*】\s*(?P<value>.*?)(?=\n\s*【|\Z)", re.S)


def is_product_title(title: str) -> bool:
    """判斷標題是否為商品文。"""
    return "[商品]" in title or "［商品］" in title


def infer_brand(*texts: str) -> str:
    """從文字推斷便利商店品牌。"""
    haystack = " ".join(t for t in texts if t).lower()
    for brand, keywords in BRANDS.items():
        for keyword in keywords:
            if keyword.lower() in haystack:
                return brand
    return "其他"


def parse_score(raw: str | None) -> float | None:
    """解析心得分數為百分制。"""
    if not raw:
        return None
    text = raw.strip()
    match = re.search(r"(\d+(?:\.\d+)?)\s*/\s*10", text)
    if match:
        return _score_range(float(match.group(1)) * 10.0)
    match = re.search(r"(\d+(?:\.\d+)?)\s*/\s*5", text)
    if match:
        return _score_range(float(match.group(1)) * 20.0)
    stars = len(re.findall(r"[★⭐]", text))
    if stars:
        return _score_range(float(stars * 20))
    match = re.search(r"(\d+(?:\.\d+)?)", text)
    if not match:
        return None
    value = float(match.group(1))
    if 0 <= value <= 10 and re.search(r"分|/10|十分", text):
        value *= 10.0
    return _score_range(value)


def parse_push_count(raw: str | None) -> int | None:
    """解析 PTT 推文數。"""
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        return 0
    if text == "爆":
        return 100
    if text.startswith("X"):
        try:
            return -10 if text == "XX" else -int(text[1:] or 1)
        except ValueError:
            return None
    try:
        return int(text)
    except ValueError:
        return None


def parse_ptt_article(html: str, url: str = "", board: str = "CVS") -> Post | None:
    """解析 PTT 文章 HTML。"""
    soup = BeautifulSoup(html, "html.parser")
    metadata = _parse_metadata(soup)
    title = metadata.get("title", "")
    if not is_product_title(title):
        return None

    posted_at = parse_ptt_datetime(metadata.get("date"))
    comments = _parse_comments(soup, posted_at)
    body_text = _body_text_without_pushes(soup)
    fields = _parse_fields(body_text)
    product_name = _first_field(fields, "商品名稱", "商品", default=_title_product_name(title))
    vendor = _first_field(fields, "便利商店/廠商名稱", "便利商店", "廠商名稱", "商店")
    review_text = _first_field(fields, "心得", "心得分享", default="")
    brand = infer_brand(vendor, title, body_text)

    post_id = _post_id(url, title, metadata.get("author", ""))
    return Post(
        id=post_id,
        source="PTT",
        board=board,
        url=url,
        title=title,
        brand=brand,
        product_name=product_name or title,
        price=_first_field(fields, "商品價格", "價格"),
        author=metadata.get("author", ""),
        author_score=parse_score(_first_field(fields, "評分", "分數")),
        review_text=review_text,
        posted_at=posted_at,
        is_reply=title.lower().startswith("re:"),
        push_count=None,
        comments=comments,
        raw={"fields": fields},
    )


def parse_ptt_list(html: str, base_url: str = "https://www.ptt.cc") -> tuple[list[dict[str, str]], str | None]:
    """解析 PTT 列表頁商品文章。"""
    soup = BeautifulSoup(html, "html.parser")
    rows: list[dict[str, str]] = []
    for ent in soup.select(".r-ent"):
        title_el = ent.select_one(".title")
        link = title_el.select_one("a") if title_el else None
        if not link:
            continue
        title = link.get_text(strip=True)
        if not is_product_title(title):
            continue
        href = link.get("href", "")
        rows.append(
            {
                "title": title,
                "url": _absolute_url(href, base_url),
                "author": _text(ent.select_one(".author")),
                "date": _text(ent.select_one(".date")),
                "push_count": _text(ent.select_one(".nrec")),
            }
        )

    prev_url = None
    for button in soup.select("a.btn.wide"):
        if "上頁" in button.get_text(strip=True):
            prev_url = _absolute_url(button.get("href", ""), base_url)
            break
    return rows, prev_url


def _parse_metadata(soup: BeautifulSoup) -> dict[str, str]:
    keys = [el.get_text(strip=True) for el in soup.select(".article-metaline .article-meta-tag")]
    values = [el.get_text(strip=True) for el in soup.select(".article-metaline .article-meta-value")]
    mapping = dict(zip(keys, values))
    return {
        "author": _clean_author(mapping.get("作者", "")),
        "title": mapping.get("標題", ""),
        "date": mapping.get("時間", ""),
    }


def _parse_comments(soup: BeautifulSoup, reference: datetime | None = None) -> list[Comment]:
    comments: list[Comment] = []
    current_run: list[Comment] = []

    def flush_run() -> None:
        if not current_run:
            return
        first = current_run[0]
        tag = next((comment.tag for comment in current_run if comment.tag.strip() != "→"), first.tag)
        comments.append(
            Comment(
                tag=tag,
                user=first.user,
                text="".join(comment.text for comment in current_run),
                posted_at=first.posted_at,
            )
        )
        current_run.clear()

    for push in soup.select("div.push"):
        tag = _text(push.select_one(".push-tag"))
        user = _text(push.select_one(".push-userid"))
        content = _text(push.select_one(".push-content")).lstrip(":：").strip()
        comment = Comment(
            tag=tag,
            user=user,
            text=content,
            posted_at=parse_push_datetime(_text(push.select_one(".push-ipdatetime")), reference=reference),
        )
        if current_run and current_run[-1].user != user:
            flush_run()
        current_run.append(comment)
    flush_run()
    return comments


def _body_text_without_pushes(soup: BeautifulSoup) -> str:
    copied = BeautifulSoup(str(soup), "html.parser")
    for selector in [".article-metaline", ".article-metaline-right", "div.push", "span.f2"]:
        for node in copied.select(selector):
            node.decompose()
    main = copied.select_one("#main-content") or copied
    return main.get_text("\n", strip=False)


def _parse_fields(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    for match in FIELD_RE.finditer(normalized):
        key = re.sub(r"\s+", "", match.group("key"))
        value = match.group("value").strip()
        fields[key] = value
    return fields


def _first_field(fields: dict[str, str], *keys: str, default: str | None = None) -> str | None:
    for key in keys:
        compact = re.sub(r"\s+", "", key)
        if compact in fields and fields[compact]:
            return fields[compact]
    for key, value in fields.items():
        if any(token in key for token in keys) and value:
            return value
    return default


def _title_product_name(title: str) -> str:
    return re.sub(r"^\s*(Re:\s*)?[\[［]商品[\]］]\s*", "", title, flags=re.I).strip()


def _clean_author(raw: str) -> str:
    return re.sub(r"\s*\(.*?\)\s*$", "", raw).strip()


def _text(node) -> str:
    return node.get_text(strip=True) if node else ""


def _score_range(value: float) -> float | None:
    if value < 0:
        return None
    return max(0.0, min(100.0, value))


def _absolute_url(href: str, base_url: str) -> str:
    if href.startswith("http"):
        return href
    return base_url.rstrip("/") + "/" + href.lstrip("/")


def _post_id(url: str, title: str, author: str) -> str:
    if url:
        return url.rsplit("/", 1)[-1].replace(".html", "")
    digest = hashlib.sha1(f"{title}|{author}".encode("utf-8")).hexdigest()[:12]
    return f"local-{digest}"


def parse_ptt_datetime(raw: str | None) -> datetime | None:
    """解析 PTT 文章時間。"""
    if not raw:
        return None
    for fmt in ("%a %b %d %H:%M:%S %Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw.strip(), fmt)
        except ValueError:
            pass
    return None


def parse_push_datetime(raw: str | None, reference: datetime | None = None) -> datetime | None:
    """解析 PTT 推文時間。"""
    if not raw:
        return None
    text = raw.strip()
    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        pass

    match = re.fullmatch(r"(?P<month>\d{1,2})/(?P<day>\d{1,2})\s+(?P<hour>\d{1,2}):(?P<minute>\d{2})", text)
    if match:
        year = reference.year if reference is not None else datetime.now().year
        try:
            parsed = datetime(
                year,
                int(match.group("month")),
                int(match.group("day")),
                int(match.group("hour")),
                int(match.group("minute")),
            )
        except ValueError:
            return None
        if reference is not None and parsed < reference - timedelta(days=180):
            parsed = _replace_year(parsed, year + 1)
        elif reference is not None and parsed > reference + timedelta(days=180):
            parsed = _replace_year(parsed, year - 1)
        return parsed
    return None


def _replace_year(value: datetime, year: int) -> datetime | None:
    try:
        return value.replace(year=year)
    except ValueError:
        return None
