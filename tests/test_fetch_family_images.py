from scripts.fetch_family_images import wanted_cmnos


def test_only_imageless_unreviewed_familymart_products_with_a_cmno():
    # Why: the daily run must not re-fetch photos for products that already
    # have one or were already decided (incl. removals), nor touch other brands.
    products = [
        {"id": "全家::要", "brand": "全家", "productName": "要", "image": None},
        {"id": "全家::有圖", "brand": "全家", "productName": "有圖", "image": {"imageUrl": "x"}},
        {"id": "全家::已審", "brand": "全家", "productName": "已審", "image": None},
        {"id": "全家::沒編號", "brand": "全家", "productName": "沒編號", "image": None},
        {"id": "7-11::要", "brand": "7-11", "productName": "要", "image": None},
    ]
    cmno = {"官方要": "001", "官方有圖": "002", "官方已審": "003"}

    def official_name_for(brand, name):
        return "官方" + name

    got = wanted_cmnos(products, {"全家::已審"}, official_name_for, cmno)
    assert got == {"全家::要": "001"}
