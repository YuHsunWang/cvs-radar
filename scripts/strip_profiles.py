#!/usr/bin/env python3
"""Remove account profiles from a publishable results snapshot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RESULTS_PATH = ROOT / "data" / "results.json"


def strip_profiles(path: Path) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["profiles"] = []
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Remove profiles from a results JSON file")
    parser.add_argument("path", nargs="?", type=Path, default=DEFAULT_RESULTS_PATH)
    args = parser.parse_args()

    strip_profiles(args.path)
    print(f"Stripped profiles from {args.path}")


if __name__ == "__main__":
    main()
