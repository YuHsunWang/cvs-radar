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
  # Freshness decides whether this run counts as a success. A pipeline that exits 0
  # while the published data is stale is precisely the failure an exit-status monitor
  # exists to catch, so the check runs before the marker is written and its exit code
  # is kept instead of being downgraded to a warning.
  python3 "$REPO/scripts/check_data_freshness.py"
  fresh_rc=$?
  if [ "$fresh_rc" -eq 0 ]; then
    mkdir -p "$(dirname "$LAST_SUCCESS_FILE")"
    date -u +%FT%TZ > "$LAST_SUCCESS_FILE"
  else
    echo "[cron] FAILED: published data did not meet the freshness SLO" >&2
    rc="$fresh_rc"
  fi
fi

echo "========== $(date -u +%FT%TZ) cvs-rebackfill cron end (exit $rc) =========="
exit "$rc"
