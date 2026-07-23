#!/usr/bin/env bash
# rebackfill-cron.sh — scheduled wrapper around rebackfill.sh (review #9).
#
# Cron's PATH is minimal, so we set a full one (override with CVS_CRON_PATH).
# Records a last-success timestamp and, after a successful run, checks the
# published data against the freshness SLO so a prolonged failure/absence is
# caught instead of silently going stale. See docs/ops-pipeline.md.
#
# Env overrides: CVS_CRON_PATH PUSH DO_COMMIT LAST_SUCCESS_FILE
#                CVS_DATA_STALE_DAYS CVS_FRESHNESS_WEBHOOK
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"

export HOME="${HOME:-/home/user}"
export PATH="${CVS_CRON_PATH:-/home/user/.local/bin:/home/user/.hermes/node/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin}"
export PUSH="${PUSH:-1}"        # go live by default; override PUSH=0 to dry-run
export DO_COMMIT="${DO_COMMIT:-1}"
LAST_SUCCESS_FILE="${LAST_SUCCESS_FILE:-$HOME/.claude/logs/cvs-rebackfill.last-success}"

echo "========== $(date -u +%FT%TZ) cvs-rebackfill cron start (PUSH=$PUSH) =========="
bash "$HERE/rebackfill.sh"
rc=$?

if [ "$rc" -eq 0 ]; then
  # exit 0 covers both "labeled+pushed" and "nothing new to label" — both healthy.
  mkdir -p "$(dirname "$LAST_SUCCESS_FILE")"
  date -u +%FT%TZ > "$LAST_SUCCESS_FILE"
  # Verify the published data actually meets the freshness SLO. A non-zero exit
  # here (or a webhook when CVS_FRESHNESS_WEBHOOK is set) is the alert signal.
  python3 "$REPO/scripts/check_data_freshness.py" || \
    echo "[cron] WARNING: freshness check reported the published data is stale" >&2
fi

echo "========== $(date -u +%FT%TZ) cvs-rebackfill cron end (exit $rc) =========="
exit "$rc"
