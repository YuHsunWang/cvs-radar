"""Tests for the data-freshness SLO check (review #9).

These encode WHY the check exists: a stale published dataset must fail loudly
(non-zero exit) so a prolonged pipeline outage is caught, while a fresh dataset
must pass and an unreadable/undated one must be reported as unknown — never
silently treated as fresh.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.check_data_freshness import DEFAULT_MAX_AGE_DAYS, data_age_days, main

ROOT = Path(__file__).resolve().parents[1]


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


# Keep the user's global/system git config (signing, hooks, url rewrites) out of
# the throwaway repos these tests build.
_HERMETIC_GIT = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@example.com", *args],
        cwd=cwd, check=True, capture_output=True, env={**os.environ, **_HERMETIC_GIT},
    )


def _write_data(root: Path, age_days: float) -> None:
    data = root / "web" / "public" / "data.json"
    data.parent.mkdir(parents=True, exist_ok=True)
    data.write_text(json.dumps({"generatedAt": _iso(age_days), "products": []}), encoding="utf-8")


class CronFreshnessGateTest(unittest.TestCase):
    """The cron wrapper must judge the data.json on origin, which is what the site
    is built from, not either local copy. The checkout's copy only moves when
    someone pulls. The worktree's copy is rebuilt by every run that reaches the
    check, so it is always fresh, including on a run whose push was rejected."""

    def _run_wrapper(
        self, *, published_age_days: float | None, local_age_days: float, checkout_age_days: float
    ) -> tuple[int, bool]:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            repo, wt, origin = base / "repo", base / "wt", base / "origin.git"
            ops = repo / "scripts" / "ops"
            ops.mkdir(parents=True)
            shutil.copy(ROOT / "scripts" / "ops" / "rebackfill-cron.sh", ops)
            shutil.copy(ROOT / "scripts" / "check_data_freshness.py", repo / "scripts")
            (ops / "rebackfill.sh").write_text("exit 0\n", encoding="utf-8")  # pipeline succeeded
            _write_data(repo, checkout_age_days)
            wt.mkdir()
            _git(wt, "init", "-q", "-b", "main")
            if published_age_days is not None:  # None: no origin to read from
                _git(base, "init", "-q", "--bare", "-b", "main", str(origin))
                _write_data(wt, published_age_days)
                _git(wt, "add", "web/public/data.json")
                _git(wt, "commit", "-q", "-m", "published snapshot")
                _git(wt, "remote", "add", "origin", str(origin))
                _git(wt, "push", "-q", "origin", "main")
            _write_data(wt, local_age_days)  # this run's own build, never pushed
            last_success = base / "last-success"
            env = {
                **os.environ,
                **_HERMETIC_GIT,
                "CVS_CRON_PATH": os.environ.get("PATH", ""),
                "WT": str(wt),
                "BRANCH": "main",
                "LAST_SUCCESS_FILE": str(last_success),
                "PUSH": "0",
                "CVS_FRESHNESS_WEBHOOK": "",
            }
            env.pop("CVS_DATA_STALE_DAYS", None)
            proc = subprocess.run(
                ["bash", str(ops / "rebackfill-cron.sh")], env=env, capture_output=True, text=True, timeout=60
            )
            return proc.returncode, last_success.exists()

    def test_run_whose_push_never_landed_fails(self) -> None:
        # Both local copies are minutes old; origin still has the old snapshot.
        rc, marked = self._run_wrapper(
            published_age_days=DEFAULT_MAX_AGE_DAYS + 5, local_age_days=0.1, checkout_age_days=0.1
        )
        self.assertEqual(rc, 1)
        self.assertFalse(marked)

    def test_fresh_published_data_passes_even_if_local_copies_are_stale(self) -> None:
        rc, marked = self._run_wrapper(
            published_age_days=0.1,
            local_age_days=DEFAULT_MAX_AGE_DAYS + 5,
            checkout_age_days=DEFAULT_MAX_AGE_DAYS + 5,
        )
        self.assertEqual(rc, 0)
        self.assertTrue(marked)

    def test_unreadable_origin_is_unknown_not_success(self) -> None:
        rc, marked = self._run_wrapper(published_age_days=None, local_age_days=0.1, checkout_age_days=0.1)
        self.assertEqual(rc, 2)
        self.assertFalse(marked)


if __name__ == "__main__":
    unittest.main()
