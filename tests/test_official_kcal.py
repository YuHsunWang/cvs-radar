import csv

import pytest

from cvs_radar.official_kcal import (
    KcalLookup,
    OfficialItem,
    load_matches,
    load_official,
    merge_official,
    normalize_name,
    parse_family_list,
    parse_seven_xml,
    write_official,
)

SEVEN_XML = """<?xml version="1.0" encoding="utf-8"?><BD>
<Item><name>肉鬆玉子新極大飯糰</name><kcal>311</kcal></Item>
<Item><name>關東煮蘿蔔</name><kcal>8kcal/個</kcal></Item>
<Item><name>雙色火龍果切片</name><kcal></kcal></Item>
<Item><name>點心</name><kcal>.</kcal></Item>
<Item><name>雞胸沙拉</name><kcal>164.6</kcal></Item>
</BD>"""


def family(*rows, code="00", category="5"):
    items = [{"PRODNAME": n, "NOTE": note} for n, note in rows]
    return {"RESULT_CODE": code, "LIST": [{"CATEGORY_ID": category, "ITEM": items}]}


def official_row(brand, name, kcal):
    return {"brand": brand, "official_name": name, "kcal": str(kcal), "servings": "", "first_seen": "d", "last_seen": "d"}


def test_seven_keeps_numeric_calories_and_skips_blanks():
    items = parse_seven_xml(SEVEN_XML)
    assert [(i.official_name, i.kcal) for i in items] == [
        ("肉鬆玉子新極大飯糰", 311),
        ("關東煮蘿蔔", 8),
        ("雞胸沙拉", 165),
    ]


def test_family_calories_are_per_package_not_per_serving():
    # The site states 106 kcal per serving and 3 servings; a shopper eats the box.
    items = parse_family_list(family(("招牌高麗菜鍋貼", "熱量106大卡，本包裝含3份")))
    assert items == [OfficialItem("全家", "招牌高麗菜鍋貼", 318, 3)]


def test_family_counter_items_are_one_serving_not_the_bulk_bag():
    # A 葡式千層蛋塔 is sold as one tart; x6 would publish 1,498 kcal for it.
    items = parse_family_list(family(("葡式千層蛋塔", "熱量249.7大卡，本包裝含6份"), category="11"))
    assert [i.kcal for i in items] == [250]


def test_family_egg_packs_with_several_servings_get_no_value():
    assert parse_family_list(family(("伊勢幸福鮮蛋10入", "熱量77.2大卡，本包裝含10份"), category="13")) == []
    assert [i.kcal for i in parse_family_list(family(("茶葉蛋", "熱量75大卡，本包裝含1份"), category="13"))] == [75]


def test_family_skips_rows_without_a_calorie_statement():
    assert parse_family_list(family(("咖啡豆", "本產品「營養標示」非強制標示項目"))) == []


def test_family_api_error_raises_instead_of_returning_an_empty_catalogue():
    with pytest.raises(ValueError):
        parse_family_list(family(code="99"))


def test_normalize_ignores_spacing_dashes_and_bracketed_notes():
    assert normalize_name("潮粵坊-蝦仁 韭菜餅(植覺生活)") == normalize_name("潮粵坊蝦仁韭菜餅")


def test_merge_keeps_delisted_rows_and_refreshes_seen_ones():
    existing = [official_row("7-11", "舊飯糰", 200), official_row("7-11", "新飯糰", 300)]
    merged = merge_official(existing, [OfficialItem("7-11", "新飯糰", 310)], "2026-09-27")
    rows = {row["official_name"]: row for row in merged}
    assert rows["舊飯糰"]["kcal"] == "200"
    assert rows["新飯糰"]["kcal"] == "310"
    assert rows["新飯糰"]["last_seen"] == "2026-09-27"
    assert rows["新飯糰"]["first_seen"] == "d"


def test_lookup_exact_match_is_per_brand():
    lookup = KcalLookup([official_row("全家", "鮪魚飯糰", 193)], {})
    assert lookup.kcal_for("全家", "鮪魚 飯糰") == 193
    assert lookup.kcal_for("7-11", "鮪魚飯糰") is None


def test_lookup_refuses_a_name_shared_by_two_different_calorie_rows():
    # Two sizes of one dish normalise to the same name; guessing would publish a wrong number.
    lookup = KcalLookup([official_row("全家", "拿鐵(中)", 120), official_row("全家", "拿鐵(大)", 180)], {})
    assert lookup.kcal_for("全家", "拿鐵") is None


def test_lookup_applies_only_reviewed_same_verdicts():
    official = [official_row("7-11", "晶華-港式油雞臘味飯", 650), official_row("7-11", "紐奧良風味烤雞", 400)]
    matches = {
        "7-11::港式油雞臘味飯": {"product_id": "7-11::港式油雞臘味飯", "official_name": "晶華-港式油雞臘味飯", "verdict": "same"},
        "7-11::紐奧良風味烤雞堡": {"product_id": "7-11::紐奧良風味烤雞堡", "official_name": "紐奧良風味烤雞", "verdict": "different"},
    }
    lookup = KcalLookup(official, matches)
    assert lookup.kcal_for("7-11", "港式油雞臘味飯") == 650
    assert lookup.kcal_for("7-11", "紐奧良風味烤雞堡") is None


def test_written_cache_round_trips_with_bom_and_crlf(tmp_path):
    path = tmp_path / "official_kcal.csv"
    rows = merge_official([], [OfficialItem("全家", "鮪魚飯糰", 193, 1)], "2026-09-26")
    write_official(rows, path)
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf") and b"\r\n" in raw
    assert load_official(path) == rows


def test_unknown_verdict_is_rejected(tmp_path):
    path = tmp_path / "kcal_matches.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerows([("product_id", "official_name", "verdict"), ("全家::a", "a", "maybe")])
    with pytest.raises(ValueError):
        load_matches(path)
