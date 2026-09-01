import json
from unittest.mock import Mock, patch

import pytest
import requests

from cvs_radar.family_food_crawler import (
    FamilyFoodCrawler,
    parse_api_response,
    parse_list_html,
    parse_product_html,
)


LIST = """
<a href="/Web_FFD_2022/product/101">飯糰</a>
<a href="/Web_FFD_2022/product/102">沙拉</a>
<a rel="next" href="/Web_FFD_2022/results/2">下一頁</a>
"""
DETAIL = """
<h1>鮪魚飯糰</h1><img src="/media/a.jpg"><img src="/media/b.png">
<table><tr><th>每一份量</th><td>100公克</td></tr>
<tr><th>本包裝含</th><td>1份</td></tr><tr><th>熱量</th><td>210大卡</td></tr>
<tr><th>蛋白質</th><td>5.2公克</td></tr><tr><th>鈉</th><td>350毫克</td></tr>
<tr><th>原料成分</th><td>米、鮪魚</td></tr><tr><th>過敏原</th><td>魚類</td></tr></table>
"""


def response(text="", content_type="text/html", status=200):
    result = Mock(spec=requests.Response)
    result.text = text
    result.content = text.encode()
    result.headers = {"Content-Type": content_type}
    result.raise_for_status.side_effect = requests.HTTPError() if status >= 400 else None
    result.json.side_effect = lambda: json.loads(text)
    return result


def test_list_pagination_and_detail_links():
    items, next_url = parse_list_html(LIST, "https://foodsafety.family.com.tw/Web_FFD_2022/results/1")
    assert [x["product_id"] for x in items] == ["101", "102"]
    assert next_url.endswith("/results/2")


def test_dynamic_api_response():
    items, next_url = parse_api_response({"data": {"items": [
        {"productId": 7, "productName": "布丁", "detailUrl": "/Web_FFD_2022/product/7"}
    ], "nextPageUrl": "/Web_FFD_2022/results/2"}})
    assert items[0]["name"] == "布丁"
    assert next_url.endswith("results/2")


def test_chinese_nutrients_missing_fields_and_images():
    item = parse_product_html(DETAIL, "https://foodsafety.family.com.tw/Web_FFD_2022/product/101")
    assert item.calories.value == 210
    assert item.calories.unit == "kcal"
    assert item.calories.raw_text == "210大卡"
    assert item.protein.value == 5.2
    assert item.sodium.unit == "mg"
    assert item.sugar is None
    assert len(item.image_urls) == 2
    assert item.ingredients == "米、鮪魚"


def test_offsite_url_is_rejected():
    with pytest.raises(ValueError, match="off-site"):
        FamilyFoodCrawler(session=Mock())._get("https://evil.example/a")
    items, _ = parse_list_html('<a href="https://evil.example/product/1">x</a>',
                               "https://foodsafety.family.com.tw/Web_FFD_2022/results/1")
    assert items == []


def test_duplicate_products_are_only_fetched_once():
    session = Mock()
    session.headers = {}
    session.get.side_effect = [response(LIST.replace("product/102", "product/101")), response(DETAIL)]
    crawler = FamilyFoodCrawler(session=session, request_delay=0)
    products = crawler.crawl(max_pages=1)
    assert len(products) == 1
    assert session.get.call_count == 2


def test_timeout_is_retried_then_succeeds():
    session = Mock()
    session.headers = {}
    session.get.side_effect = [requests.Timeout(), response(LIST)]
    crawler = FamilyFoodCrawler(session=session, request_delay=0, retries=1)
    assert crawler._get("https://foodsafety.family.com.tw/Web_FFD_2022/results/1").text == LIST
    assert session.get.call_count == 2


def test_http_error_exhausts_retries():
    session = Mock()
    session.headers = {}
    session.get.return_value = response(status=500)
    with pytest.raises(requests.HTTPError):
        FamilyFoodCrawler(session=session, request_delay=0, retries=1)._get(
            "https://foodsafety.family.com.tw/Web_FFD_2022/results/1"
        )
    assert session.get.call_count == 2


def test_malformed_html_and_json_are_safe_or_reported():
    assert parse_list_html("<div><a", "https://foodsafety.family.com.tw/Web_FFD_2022/results/1") == ([], None)
    with pytest.raises(json.JSONDecodeError):
        parse_api_response("not-json")


def test_image_content_type_and_size(tmp_path):
    session = Mock()
    session.headers = {}
    session.get.side_effect = [response("not image", "text/html"), response("x" * 10, "image/png")]
    crawler = FamilyFoodCrawler(session=session, request_delay=0)
    product = parse_product_html(DETAIL, "https://foodsafety.family.com.tw/Web_FFD_2022/product/101")
    with patch.object(crawler, "_get", side_effect=session.get):
        assert crawler.download_images(product, tmp_path, max_bytes=5) == []
