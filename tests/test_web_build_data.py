from pathlib import Path

import pytest
from types import SimpleNamespace

from web.build_data import (
    apply_product_override,
    calibrate_recommendation_score,
    calibrate_recommendation_scores,
    display_confidence,
    load_product_overrides,
)


def report(key: str, score: float | None, *, confidence: str = "中", consensus: str = "褒貶不一") -> SimpleNamespace:
    return SimpleNamespace(
        product_key=key,
        fair_score=score,
        confidence=confidence,
        consensus=consensus,
    )


def test_recommendation_score_calibration_is_monotonic_and_reaches_nineties() -> None:
    reports = [
        report(f"product-{score}", float(score))
        for score in range(20, 81)
    ]

    calibrated = calibrate_recommendation_scores(reports)
    scores = [calibrated[report.product_key] for report in reports]

    assert scores == sorted(scores)
    assert scores[-1] >= 90
    assert all(0 <= score <= 100 for score in scores)


def test_recommendation_score_calibration_gives_ties_the_same_score() -> None:
    reports = [
        report("lower", 50.0),
        report("tie-a", 75.0),
        report("tie-b", 75.0),
    ]

    calibrated = calibrate_recommendation_scores(reports)

    assert calibrated["tie-a"] == calibrated["tie-b"]
    assert calibrated["lower"] < calibrated["tie-a"]


def test_recommendation_score_calibration_handles_no_scores() -> None:
    reports = [report("missing", None)]

    assert calibrate_recommendation_scores(reports) == {}


def test_recommendation_score_uses_stable_fixed_anchors() -> None:
    assert calibrate_recommendation_score(0) == 0
    assert calibrate_recommendation_score(50) == 60
    assert calibrate_recommendation_score(80) == 93
    assert calibrate_recommendation_score(100) == 100

    original = [report("middle", 60), report("high", 80)]
    before = calibrate_recommendation_scores(original)
    after = calibrate_recommendation_scores(original + [report(f"new-{index}", 20) for index in range(100)])

    assert {key: after[key] for key in before} == before


def test_recommendation_score_omits_low_confidence_reports() -> None:
    reports = [
        report("low", 75, confidence="低", consensus="資料不足"),
        report("enough", 75),
    ]

    assert calibrate_recommendation_scores(reports) == {"enough": 88}


def test_single_post_high_confidence_is_capped_only_for_public_display() -> None:
    single_post = SimpleNamespace(confidence="高", n_posts=1)
    multi_post = SimpleNamespace(confidence="高", n_posts=2)

    assert display_confidence(single_post) == "中"
    assert display_confidence(multi_post) == "高"



def test_load_and_apply_product_overrides(tmp_path: Path) -> None:
    path = tmp_path / "overrides.csv"
    path.write_text(
        "product_id,brand,productName,category,price,excerpt,exclude,reason\n"
        "全家::錯誤名稱,,正確名稱,麵包,49,__CLEAR__,,人工確認\n",
        encoding="utf-8",
    )
    product = {
        "id": "全家::錯誤名稱",
        "brand": "全家",
        "productName": "錯誤名稱",
        "category": "飲料",
        "price": 99,
        "excerpt": "錯誤摘錄",
    }

    corrected = apply_product_override(product, load_product_overrides(path)[product["id"]])

    assert corrected == {
        "id": "全家::正確名稱",
        "brand": "全家",
        "productName": "正確名稱",
        "category": "麵包",
        "price": 49,
        "excerpt": "",
    }
    assert product["productName"] == "錯誤名稱"


def test_blank_override_fields_preserve_generated_values(tmp_path: Path) -> None:
    path = tmp_path / "overrides.csv"
    path.write_text(
        "product_id,brand,productName,category,price,excerpt,exclude,reason\n"
        "7-11::商品,,,鹹食,,,,只改分類\n",
        encoding="utf-8",
    )
    product = {
        "id": "7-11::商品",
        "brand": "7-11",
        "productName": "商品",
        "category": "其他",
        "price": 59,
        "excerpt": "原始摘錄",
    }

    corrected = apply_product_override(product, load_product_overrides(path)[product["id"]])

    assert corrected["category"] == "鹹食"
    assert corrected["price"] == 59
    assert corrected["excerpt"] == "原始摘錄"



def test_exclude_override_removes_confirmed_invalid_record(tmp_path: Path) -> None:
    path = tmp_path / "overrides.csv"
    path.write_text(
        "product_id,brand,productName,category,price,excerpt,exclude,reason\n"
        "萊爾富::合併商品,,,,,,true,兩項商品誤合併\n",
        encoding="utf-8",
    )
    product = {
        "id": "萊爾富::合併商品",
        "brand": "萊爾富",
        "productName": "合併商品",
    }

    assert apply_product_override(product, load_product_overrides(path)[product["id"]]) is None



def test_brand_override_rebuilds_public_id(tmp_path: Path) -> None:
    path = tmp_path / "overrides.csv"
    path.write_text(
        "product_id,brand,productName,category,price,excerpt,exclude,reason\n"
        "7-11::錯品牌,全家,正確商品,,,,,來源確認\n",
        encoding="utf-8",
    )
    product = {"id": "7-11::錯品牌", "brand": "7-11", "productName": "錯品牌"}

    corrected = apply_product_override(product, load_product_overrides(path)[product["id"]])

    assert corrected is not None
    assert corrected["brand"] == "全家"
    assert corrected["productName"] == "正確商品"
    assert corrected["id"] == "全家::正確商品"



def test_invalid_override_price_fails_fast(tmp_path: Path) -> None:
    path = tmp_path / "overrides.csv"
    path.write_text(
        "product_id,brand,productName,category,price,excerpt,exclude,reason\n"
        "全家::商品,,,,錯置摘錄,,,欄位錯位\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="invalid product override price"):
        load_product_overrides(path)
