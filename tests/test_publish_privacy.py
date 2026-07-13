from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_published_results_do_not_contain_account_profiles() -> None:
    """The committed results snapshot must not expose account-level profiles."""
    results = json.loads((ROOT / "data" / "results.json").read_text(encoding="utf-8"))

    assert results["profiles"] == []
