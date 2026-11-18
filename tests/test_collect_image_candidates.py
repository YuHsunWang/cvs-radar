import csv
import json

from scripts.collect_image_candidates import article_links, collect, todo_products


def test_article_links_keeps_photo_pages_and_short_links_but_not_ptt_or_signature():
    # Why: 2026-11-18 posts had photos as postimg.cc pages and myppt.cc short
    # links, which the old image-extension filter dropped.
    text = (
        "圖 https://i.meee.com.tw/a.jpg\n頁 https://postimg.cc/gnNQRr1D\n"
        "短 https://myppt.cc/P171U\n文 https://www.ptt.cc/bbs/CVS/x.html\n"
        "--\n部落格 https://blog.example/me\n"
    )
    assert [u for u, _ in article_links(text)] == [
        "https://i.meee.com.tw/a.jpg", "https://postimg.cc/gnNQRr1D", "https://myppt.cc/P171U",
    ]


def test_todo_skips_products_with_image_or_a_manifest_decision(tmp_path):
    # Why: a product someone already reviewed (even a removal row) must not
    # come back into the queue, and only image-less products need photos.
    data = tmp_path / "data.json"
    data.write_text(json.dumps({"products": [
        {"id": "7-11::新品", "image": None, "postUrls": ["u1"]},
        {"id": "7-11::已審", "image": None, "postUrls": ["u2"]},
        {"id": "7-11::有圖", "image": {"imageUrl": "x"}, "postUrls": ["u3"]},
    ]}), encoding="utf-8")
    manifest = tmp_path / "product_images.csv"
    with manifest.open("w", encoding="utf-8-sig", newline="") as f:
        csv.writer(f).writerows([["product_id", "enabled"], ["7-11::已審", "0"]])

    todo = todo_products(data, manifest)
    rows = collect(todo, lambda url: [("https://p.example/1.jpg", "near")] if url == "u1" else [])
    assert [(r["product_id"], r["post_url"]) for r in rows] == [("7-11::新品", "u1")]
