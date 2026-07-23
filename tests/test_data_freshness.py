"""Tests for the data-freshness SLO check (review #9).

These encode WHY the check exists: a stale published dataset must fail loudly
(non-zero exit) so a prolonged pipeline outage is caught, while a fresh dataset
must pass and an unreadable/undated one must be reported as unknown — never
silently treated as fresh.
"""
from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone

from scripts.check_data_freshness import DEFAULT_MAX_AGE_DAYS, data_age_days, main


def _iso(days_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


class DataAgeDaysTest(unittest.TestCase):
    def test_recent_timestamp_is_young(self) -> None:
        self.assertLess(data_age_days(_iso(0.5)), 1.0)

    def test_old_timestamp_reports_its_age(self) -> None:
        self.assertAlmostEqual(data_age_days(_iso(20)), 20.0, places=1)

    def test_offset_timezone_is_honored(self) -> None:
        # A +08:00 snapshot (as build_data emits) must not be read as naive/UTC.
        aware = datetime.now(timezone(timedelta(hours=8))) - timedelta(days=3)
        self.assertAlmostEqual(data_age_days(aware.isoformat()), 3.0, places=1)

    def test_empty_or_naive_raises_not_zero(self) -> None:
        # Must be distinguishable from "fresh"; a naive stamp is ambiguous.
        with self.assertRaises(ValueError):
            data_age_days("")
        with self.assertRaises(ValueError):
            data_age_days("2026-07-01T00:00:00")  # no tzinfo


class FreshnessCliTest(unittest.TestCase):
    def _write(self, generated_at: str | None) -> str:
        import tempfile

        fd = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        payload: dict = {"products": []}
        if generated_at is not None:
            payload["generatedAt"] = generated_at
        json.dump(payload, fd)
        fd.close()
        return fd.name

    def test_fresh_data_exits_zero(self) -> None:
        path = self._write(_iso(1))
        self.assertEqual(main(["--data", path, "--max-age-days", "14"]), 0)

    def test_stale_data_exits_one(self) -> None:
        # Beyond the SLO -> must fail so a monitor/cron can alert.
        path = self._write(_iso(DEFAULT_MAX_AGE_DAYS + 5))
        self.assertEqual(main(["--data", path, "--max-age-days", str(DEFAULT_MAX_AGE_DAYS)]), 1)

    def test_missing_timestamp_is_unknown_not_fresh(self) -> None:
        path = self._write(None)
        self.assertEqual(main(["--data", path]), 2)

    def test_missing_file_is_unknown(self) -> None:
        self.assertEqual(main(["--data", "/nonexistent/data.json"]), 2)


if __name__ == "__main__":
    unittest.main()
