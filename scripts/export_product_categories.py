#!/usr/bin/env python3
"""Export scored products that have no LLM category label yet, for a labelling run."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cvs_radar.product_categories import (  # noqa: E402
    FIELDNAMES,
    PRODUCT_CATEGORY_LABELS_PATH,
    PROMPT_VERSION,
    load_product_category_labels,
    product_category_fingerprint,
)
from cvs_radar.store import load_results  # noqa: E402

DEFAULT_RESULTS_PATH = ROOT / "data" / "results.json"
DEFAULT_OUT_PATH = ROOT / "artifacts" / "unlabeled-product-categories.csv"


def export_unlabeled_product_categories(
    results_path: Path,
    out_path: Path,
    labels_path: Path,
) -> int:
    """Write one row per distinct unlabelled product. Returns the row count.

    Products are read from the scored report set rather than the raw posts:
    the name a product is labelled under has to be the name the pipeline
    settled on, or the fingerprint keys an answer to a product nobody
    publishes. That is also why this layer runs after the product-name layer.
    """
    labelled = load_product_category_labels(labels_path)
    loaded = load_results(results_path)
    if loaded is None:
        raise FileNotFoundError(results_path)
    reports, _profiles = loaded

    # Sorted so the delta — and therefore the chunk boundaries a labelling run
    # sees — is reproducible from the same inputs.
    seen: set[str] = set()
    rows: list[dict[str, str]] = []
    for report in sorted(reports, key=lambda item: (item.brand, item.product_name)):
        if not (report.product_name or "").strip():
            continue
        fingerprint = product_category_fingerprint(report.brand, report.product_name)
        if fingerprint in labelled or fingerprint in seen:
            continue
        seen.add(fingerprint)
        rows.append(
            {
                "fingerprint": fingerprint,
                "brand": report.brand,
                "product_name": report.product_name,
                "rule_guess": report.category or "",
                "category": "",
                "model": "",
                "prompt_version": PROMPT_VERSION,
            }
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS_PATH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_PATH)
    parser.add_argument("--labels", type=Path, default=ROOT / PRODUCT_CATEGORY_LABELS_PATH)
    args = parser.parse_args()

    count = export_unlabeled_product_categories(args.results, args.out, args.labels)
    print(f"exported {count} unlabeled product categories -> {args.out}")


if __name__ == "__main__":
    main()
