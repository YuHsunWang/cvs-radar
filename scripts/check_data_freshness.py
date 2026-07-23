#!/usr/bin/env python3
"""Freshness SLO check for the published CVS Radar dataset (review #9).

Reads the published ``web/public/data.json`` ``generatedAt`` (the data-snapshot
time, not the site build time) and fails when the data is older than the
freshness SLO. Unlike the build-time warning in ``web/build_data.py``, this runs
standalone at any time — after a local pipeline run, in CI, or from a monitor —
so a prolonged pipeline failure or a silently stale site is caught instead of
going unnoticed.

Exit codes: 0 = fresh, 1 = stale (older than the SLO), 2 = cannot determine
(missing file / no timestamp / parse error). The non-zero exit is what lets a
cron wrapper or monitor alert.

Optionally, when stale and ``--webhook``/``CVS_FRESHNESS_WEBHOOK`` is set, posts
a short JSON message to that URL (best effort; never changes the exit code).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DATA = Path(__file__).resolve().parent.parent / "web" / "public" / "data.json"
# Mirrors DATA_STALE_DAYS in web/build_data.py; override with CVS_DATA_STALE_DAYS.
DEFAULT_MAX_AGE_DAYS = 14


def data_age_days(generated_at: str, now: datetime | None = None) -> float:
    """Age in days of an ISO-8601 ``generatedAt`` timestamp.

    Raises ValueError on an empty/invalid timestamp so callers can distinguish
    "unknown" from "stale".
    """
    if not generated_at:
        raise ValueError("empty generatedAt")
    generated = datetime.fromisoformat(generated_at)
    if generated.tzinfo is None:
        raise ValueError(f"generatedAt has no timezone: {generated_at!r}")
    now = now or datetime.now(timezone.utc)
    return (now - generated).total_seconds() / 86400.0


def _post_webhook(url: str, payload: dict) -> None:
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=10)  # noqa: S310 - user-supplied ops URL
    except Exception as exc:  # best effort: never mask the freshness result
        print(f"WARNING: freshness webhook post failed: {exc}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check published data freshness SLO.")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA,
                        help="Path to the published data.json (default: web/public/data.json)")
    parser.add_argument("--max-age-days", type=float,
                        default=float(os.environ.get("CVS_DATA_STALE_DAYS", DEFAULT_MAX_AGE_DAYS)),
                        help="Freshness SLO in days (default: CVS_DATA_STALE_DAYS or 14)")
    parser.add_argument("--webhook", default=os.environ.get("CVS_FRESHNESS_WEBHOOK", ""),
                        help="Optional URL to POST to when stale (default: CVS_FRESHNESS_WEBHOOK)")
    args = parser.parse_args(argv)

    try:
        payload = json.loads(args.data.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"UNKNOWN: data file not found: {args.data}", file=sys.stderr)
        return 2
    except (OSError, json.JSONDecodeError) as exc:
        print(f"UNKNOWN: cannot read {args.data}: {exc}", file=sys.stderr)
        return 2

    generated_at = payload.get("generatedAt", "")
    try:
        age = data_age_days(generated_at)
    except ValueError as exc:
        print(f"UNKNOWN: {exc}", file=sys.stderr)
        return 2

    if age > args.max_age_days:
        msg = (f"STALE: data is {age:.1f} days old "
               f"(generatedAt={generated_at}, SLO={args.max_age_days:g} days)")
        print(msg)
        if args.webhook:
            _post_webhook(args.webhook, {
                "status": "stale", "age_days": round(age, 1),
                "generatedAt": generated_at, "slo_days": args.max_age_days,
                "text": f"⚠️ CVS Radar data stale: {age:.1f}d old (SLO {args.max_age_days:g}d)",
            })
        return 1

    print(f"FRESH: data is {age:.1f} days old "
          f"(generatedAt={generated_at}, SLO={args.max_age_days:g} days)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
