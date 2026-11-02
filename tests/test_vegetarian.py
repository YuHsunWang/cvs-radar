import json
from pathlib import Path

import pytest

from web import build_data


def test_every_vegetarian_label_reaches_a_published_product() -> None:
    # Product IDs drift when name extraction changes (TRAPS.md #1); a label that
    # stops matching would silently drop a vegetarian mark from the site.
    labels = build_data.load_vegetarian_labels()
    products = json.loads((Path(__file__).parents[1] / "web/public/data.json").read_text())["products"]
    published = {product["id"]: product["vegetarian"] for product in products}
    assert labels
    assert {product_id: published.get(product_id) for product_id in labels} == labels


@pytest.mark.parametrize("source", ["", "https://i.imgur.com/UiyZFCc.jpg"])
def test_a_label_without_its_ptt_evidence_post_is_rejected(tmp_path: Path, source: str) -> None:
    path = tmp_path / "vegetarian.csv"
    path.write_text(f"product_id,label,source_page_url,checked_at\n全家::測試,全素,{source},2026-11-03\n", encoding="utf-8")
    with pytest.raises(ValueError, match="evidence"):
        build_data.load_vegetarian_labels(path)
