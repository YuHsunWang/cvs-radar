from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def objects_in(value: object):
    if isinstance(value, dict):
        yield value
        for nested in value.values():
            yield from objects_in(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from objects_in(nested)


def test_published_results_do_not_contain_account_profiles() -> None:
    """The committed results snapshot must not expose account-level identity."""
    results = json.loads((ROOT / "data" / "results.json").read_text(encoding="utf-8"))

    assert results["profiles"] == []
    for item in objects_in(results):
        assert not item.get("contributors")
        assert not item.get("profiles")
        assert "user" not in item
        assert not any(key.startswith("suspicion_") for key in item)


def test_strip_profiles_removes_nested_account_identity(tmp_path: Path) -> None:
    from scripts.strip_profiles import strip_profiles

    path = tmp_path / "results.json"
    path.write_text(
        json.dumps(
            {
                "profiles": [{"user": "canary-handle", "suspicion_score": 0.9}],
                "reports": [
                    {
                        "contributors": [
                            {
                                "user": "canary-handle",
                                "role": "author",
                                "score": 0.8,
                                "weight": 0.5,
                            }
                        ],
                        "nested": {"user": "nested-canary", "suspicion_flag": True},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    strip_profiles(path)

    stripped = json.loads(path.read_text(encoding="utf-8"))
    assert stripped["profiles"] == []
    assert stripped["reports"][0]["contributors"] == []
    assert stripped["reports"][0]["nested"] == {}
    assert "canary-handle" not in path.read_text(encoding="utf-8")
