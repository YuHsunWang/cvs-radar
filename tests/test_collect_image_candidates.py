import csv
import json

from scripts.collect_image_candidates import collect, image_urls


def test_image_urls_keeps_photos_and_drops_other_links():
    text = "看圖 https://i.mopix.cc/a.jpg 和 https://imgur.com/abc 文章 https://www.ptt.cc/bbs/CVS/x.html"
    assert [u for u, _ in image_urls(text)] == ["https://i.mopix.cc/a.jpg", "https://imgur.com/abc"]


def test_collect_skips_products_with_image_or_a_manifest_decision(tmp_path):
    # Why: a product someone already reviewed (even a removal row) must not
    # come back into the queue, and only image-less products need photos.
    posts = tmp_path / "posts.jsonl"
    posts.write_text("\n".join(json.dumps(p) for p in [
        {"url": "u1", "review_text": "https://i.mopix.cc/new.jpg"},
        {"url": "u2", "review_text": "https://i.mopix.cc/decided.jpg"},
        {"url": "u3", "review_text": "https://i.mopix.cc/has.jpg"},
    ]), encoding="utf-8")
    data = tmp_path / "data.json"
    data.write_text(json.dumps({"products": [
        {"id": "7-11::新品", "image": None, "postUrls": ["u1"]},
        {"id": "7-11::已審", "image": None, "postUrls": ["u2"]},
        {"id": "7-11::有圖", "image": {"imageUrl": "x"}, "postUrls": ["u3"]},
    ]}), encoding="utf-8")
    manifest = tmp_path / "product_images.csv"
    with manifest.open("w", encoding="utf-8-sig", newline="") as f:
        csv.writer(f).writerows([["product_id", "enabled"], ["7-11::已審", "0"]])

    rows = collect(posts, data, manifest)
    assert [(r["product_id"], r["image_url"]) for r in rows] == [("7-11::新品", "https://i.mopix.cc/new.jpg")]
