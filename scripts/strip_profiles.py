#!/usr/bin/env python3
"""Remove account-level identity from a publishable results snapshot."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cvs_radar.store import validate_publishable_results, write_json_atomic  # noqa: E402


DEFAULT_RESULTS_PATH = ROOT / "data" / "results.json"


def _strip_identity(value: object) -> None:
    if isinstance(value, list):
        for item in value:
            _strip_identity(item)
        return
    if not isinstance(value, dict):
        return

    for key in list(value):
        if key in {"contributors", "profiles"}:
            value[key] = []
        elif key == "user" or key.startswith("suspicion_"):
            del value[key]
        else:
            _strip_identity(value[key])


def strip_profiles(path: Path) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["profiles"] = []
    _strip_identity(payload)
    validate_publishable_results(payload)
    write_json_atomic(path, payload)


def main() -> None:
    parser = argparse.ArgumentParser(description="Remove profiles from a results JSON file")
    parser.add_argument("path", nargs="?", type=Path, default=DEFAULT_RESULTS_PATH)
    args = parser.parse_args()

    strip_profiles(args.path)
    print(f"Stripped profiles from {args.path}")


if __name__ == "__main__":
    main()
