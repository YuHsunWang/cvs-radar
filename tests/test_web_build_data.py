import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from types import SimpleNamespace

import web.build_data as build_data
from web.build_data import (
    apply_product_override,
    assert_unique_product_ids,
    calibrate_recommendation_score,
    calibrate_recommendation_scores,
    display_confidence,
    existing_site_built_at,
    load_product_overrides,
    merge_products,
    resolve_data_timestamps,
    to_product,
)


def report(key: str, score: float | None, *, confidence: str = "中", consensus: str = "褒貶不一") -> SimpleNamespace:
    return SimpleNamespace(
        product_key=key,
        fair_score=score,
        confidence=confidence,
        consensus=consensus,
    )


def test_source_snapshot_time_is_distinct_from_site_build_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "results.json"
    output = tmp_path / "data.json"
    source.write_text(json.dumps({"generated_at": "2026-07-22 08:34:28"}), encoding="utf-8")
    site_built_at = datetime(2026, 7, 23, 4, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(build_data, "ROOT", tmp_path)
    monkeypatch.setattr(build_data, "load_results", lambda _source: ([], []))
    monkeypatch.setattr(build_data, "load_product_overrides", lambda: {})

    build_data.main(source=source, output=output, site_built_at=site_built_at)
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert payload["generatedAt"] == "2026-07-22T08:34:28+08:00"
    assert payload["siteBuiltAt"] == "2026-07-23T04:00:00+00:00"
    assert payload["generatedAt"] != payload["siteBuiltAt"]


def test_missing_source_snapshot_time_falls_back_to_site_build_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "results.json"
    output = tmp_path / "data.json"
    source.write_text(json.dumps({"reports": []}), encoding="utf-8")
    site_built_at = datetime(2026, 7, 23, 4, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(build_data, "ROOT", tmp_path)
    monkeypatch.setattr(build_data, "load_results", lambda _source: ([], []))
    monkeypatch.setattr(build_data, "load_product_overrides", lambda: {})

    build_data.main(source=source, output=output, site_built_at=site_built_at)
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert payload["generatedAt"] == site_built_at.isoformat()
    assert payload["siteBuiltAt"] == site_built_at.isoformat()
    assert "WARNING: source data has no generated_at" in capsys.readouterr().out


def test_rebuild_reuses_existing_site_timestamp_for_a_reproducible_artifact(tmp_path: Path) -> None:
    output = tmp_path / "data.json"
    output.write_text(
        json.dumps({"siteBuiltAt": "2026-07-23T02:15:21.663714+00:00"}),
        encoding="utf-8",
    )

    assert existing_site_built_at(output) == datetime(2026, 7, 23, 2, 15, 21, 663714, tzinfo=timezone.utc)


def test_stale_source_snapshot_prints_build_warning(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "results.json"
    source.write_text(json.dumps({"generated_at": "2026-07-01 12:00:00"}), encoding="utf-8")
    site_built_at = datetime(2026, 7, 23, 4, 0, tzinfo=timezone.utc)

    resolve_data_timestamps(source, site_built_at)

    warning = capsys.readouterr().out
    assert "WARNING: source data is stale" in warning
    assert "threshold: 14 days" in warning


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


def test_override_collision_merges_into_one_public_product() -> None:
    products = [
        {
            "id": "7-11::促銷商品49第二件",
            "brand": "7-11",
            "productName": "促銷商品49第二件",
            "category": "冰品",
            "nPosts": 1,
            "nComments": 2,
            "_nEff": 2,
            "_fairScoreRaw": 80.0,
            "fairScore": 80,
            "recommendationScore": 93,
            "latestDate": "2026-06-01",
            "firstDate": "2026-05-01",
            "likes": ["甲", "共同"],
            "cautions": ["太甜"],
        },
        {
            "id": "7-11::促銷商品",
            "brand": "7-11",
            "productName": "促銷商品",
            "category": "甜點",
            "nPosts": 3,
            "nComments": 6,
            "_nEff": 6,
            "_fairScoreRaw": 40.0,
            "fairScore": 40,
            "recommendationScore": 48,
            "latestDate": "2026-06-20",
            "firstDate": "2026-05-10",
            "likes": ["共同", "乙", "丙"],
            "cautions": ["偏貴", "份量少", "易融"],
        },
    ]
    overrides = {
        "7-11::促銷商品49第二件": {"productName": "促銷商品"},
    }
    corrected = [apply_product_override(item, overrides.get(item["id"])) for item in products]

    merged = merge_products([item for item in corrected if item is not None])

    assert len(merged) == 1
    assert merged[0]["id"] == "7-11::促銷商品"
    assert merged[0]["nPosts"] == 4
    assert merged[0]["nComments"] == 8
    assert merged[0]["fairScore"] == 50
    assert merged[0]["recommendationScore"] == 60
    assert merged[0]["latestDate"] == "2026-06-20"
    assert merged[0]["firstDate"] == "2026-05-01"
    assert merged[0]["likes"] == ["甲", "共同", "乙"]
    assert merged[0]["cautions"] == ["太甜", "偏貴", "份量少"]
    assert merged[0]["category"] == "甜點"
    assert "_nEff" not in merged[0]
    assert "_fairScoreRaw" not in merged[0]


def test_duplicate_public_product_ids_fail_fast() -> None:
    products = [{"id": "全家::重複商品"}, {"id": "全家::重複商品"}]

    with pytest.raises(ValueError, match="duplicate public product ids after merge"):
        assert_unique_product_ids(products)


def test_data_build_fails_if_duplicate_ids_reach_the_public_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "results.json"
    source.write_text("{}", encoding="utf-8")
    reports = [
        SimpleNamespace(product_key="one", n_eff=1, fair_score=None),
        SimpleNamespace(product_key="two", n_eff=1, fair_score=None),
    ]
    monkeypatch.setattr(build_data, "load_results", lambda _source: (reports, []))
    monkeypatch.setattr(build_data, "calibrate_recommendation_scores", lambda _reports: {})
    monkeypatch.setattr(build_data, "load_product_overrides", lambda: {})
    monkeypatch.setattr(
        build_data,
        "to_product",
        lambda _report, _score: {"id": "全家::重複商品"},
    )
    monkeypatch.setattr(build_data, "merge_products", lambda products: products)

    with pytest.raises(ValueError, match="duplicate public product ids after merge"):
        build_data.main(source=source, output=tmp_path / "data.json")


def test_public_score_fixture_keeps_fair_and_recommendation_scores_distinct(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public_report = SimpleNamespace(
        brand="全家",
        product_name="測試商品",
        price=45,
        category="飲料",
        fair_score=47.4,
        confidence="中",
        consensus="褒貶不一",
        n_posts=2,
        n_comments=3,
        rep_positive=[],
        rep_negative=[],
        review_excerpt="",
        post_urls=[],
        latest_post_date=None,
    )
    monkeypatch.setattr(build_data, "consensus_distribution", lambda _report: (50, 25, 25))

    product = to_product(public_report, recommendation_score=57)

    assert product["fairScore"] == 47
    assert product["recommendationScore"] == 57
