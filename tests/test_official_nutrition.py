from cvs_radar.official_kcal import KcalLookup
from cvs_radar.official_nutrition import NutritionLookup, parse_detail_text

# Visible text of /Web_FFD_2022/product/0612008 as of 2026-10-15.
PAGE = """鮪魚飯糰
每份熱量193大卡
每份規格109公克
(本包裝含1份)
商品簡歷
成分來源
每份營養素
碳水化合物
32.9公克
蛋白質
5.1公克
脂肪
4.5公克
飽和脂肪
0.9公克
反式脂肪
0公克
鈉
201毫克
糖
0.9公克
過敏原
"""


def test_reads_every_nutrient_and_keeps_fat_apart_from_saturated_fat():
    row = parse_detail_text(PAGE)
    assert row == {
        "kcal": "193", "serving_size": "109 公克", "package_servings": "1", "carbohydrate": "32.9", "protein": "5.1", "fat": "4.5",
        "saturatedFat": "0.9", "transFat": "0", "sodium": "201", "sugar": "0.9",
    }


def test_drink_keeps_millilitres_and_label_keeps_its_own_serving_count():
    row = parse_detail_text(PAGE.replace("109公克", "330毫升").replace("(本包裝含1份)", "(本包裝含6份)"))
    assert row["serving_size"] == "330 毫升"
    assert row["package_servings"] == "6"


def test_partial_label_is_dropped_not_shown_with_gaps():
    # A missing 鈉 row would render as an empty cell that reads as zero sodium.
    assert parse_detail_text(PAGE.replace("鈉\n201毫克\n", "")) is None
    assert parse_detail_text("本產品「營養標示」非強制標示項目") is None


def official(name, kcal, servings):
    return {"brand": "全家", "official_name": name, "kcal": str(kcal), "servings": str(servings),
            "first_seen": "d", "last_seen": "d"}


def nutrition(name):
    return {"brand": "全家", "official_name": name, "cmno": "1", **parse_detail_text(PAGE), "fetched": "d"}


def test_lookup_follows_the_calorie_match_and_its_servings():
    rows = [official("鮪魚飯糰", 386, 2), official("晶華-港式油雞臘味飯", 600, 1)]
    kcal = KcalLookup(rows, {"全家::港式油雞臘味飯": {"official_name": "晶華-港式油雞臘味飯", "verdict": "same"}})
    lookup = NutritionLookup(kcal, rows, [nutrition("鮪魚飯糰")])
    result = lookup.nutrition_for("全家", "鮪魚 飯糰")
    assert result["servings"] == 2
    assert result["perServing"]["sodium"] == 201.0
    # Reviewed match without a fetched label, and a name with no calorie match: nothing.
    assert lookup.nutrition_for("全家", "港式油雞臘味飯") is None
    assert lookup.nutrition_for("全家", "不存在") is None


def test_label_contradicting_the_catalogue_calories_is_dropped():
    rows = [official("鮪魚飯糰", 230, 1)]  # page says 193 per serving, 1 serving
    lookup = NutritionLookup(KcalLookup(rows, {}), rows, [nutrition("鮪魚飯糰")])
    assert lookup.nutrition_for("全家", "鮪魚飯糰") is None


def test_ambiguous_name_gets_no_label():
    # Two catalogue rows normalise to one name: calories already refuse to guess,
    # and the label must not pick one of them either.
    rows = [official("鮪魚飯糰", 193, 1), official("鮪魚-飯糰", 193, 1)]
    lookup = NutritionLookup(KcalLookup(rows, {}), rows, [nutrition("鮪魚飯糰")])
    assert lookup.nutrition_for("全家", "鮪魚飯糰") is None
