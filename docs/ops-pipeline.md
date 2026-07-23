# Ops: data-refresh pipeline, scheduling & freshness (review #9)

This documents how the live CVS Radar data is refreshed, scheduled, and
monitored, so the process is reproducible from the repo rather than only from
the author's machine. For raw-store loss recovery see
[`runbook-data-recovery.md`](./runbook-data-recovery.md).

## Architecture (current)

Since 2026-07-21 the publisher is a **local cron pipeline**, not GitHub Actions.
`.github/workflows/refresh-data.yml` is kept only as a **manual** fallback
(`workflow_dispatch`) for when the local machine is unavailable.

The pipeline scripts are versioned in this repo:

| Script | Role |
|---|---|
| [`scripts/ops/rebackfill.sh`](../scripts/ops/rebackfill.sh) | the full refresh: crawl → backfill review text → export unlabeled delta → **Codex LLM sentiment labeling** → verify → import labels → recompute scores → `strip_profiles` (de-identify) → `build_data` → commit (+push) |
| [`scripts/ops/rebackfill-cron.sh`](../scripts/ops/rebackfill-cron.sh) | scheduled wrapper: full PATH, records last-success, runs the freshness check |
| [`scripts/check_data_freshness.py`](../scripts/check_data_freshness.py) | freshness SLO check on the **published** `web/public/data.json` |

The **Codex labeling step requires a local Codex CLI subscription** and is not
reproducible in CI; every other step is standard python + git.

### Key environment overrides

`REPO` `BRANCH` `WT` `STORE_SEED` `PAGES` `REFRESH_DAYS` `CHUNK` `CONC`
`DO_COMMIT` `PUSH` `RUNNER` (rebackfill.sh); `CVS_CRON_PATH` `LAST_SUCCESS_FILE`
`CVS_DATA_STALE_DAYS` `CVS_FRESHNESS_WEBHOOK` (cron wrapper / freshness check).
Defaults target the author's WSL setup; override them on any other host.

## Scheduling

Point cron at the **repo copy** so the repo is the single source of truth
(avoids drift with any older copy under `~/.claude/tools/`):

```cron
30 8 * * *  /bin/bash /home/user/github-work/YuHsunWang/cvs-radar-clean/scripts/ops/rebackfill-cron.sh >> ~/.claude/logs/cvs-rebackfill.cron.log 2>&1
```

`PUSH=1` (the wrapper's default) publishes to `origin/main`; set `PUSH=0` for a
dry run that commits only in the worktree.

## Freshness SLO & monitoring

- **SLO:** published data must be at most `DATA_STALE_DAYS` = **14** days old
  (mirrored in `web/build_data.py`; override with `CVS_DATA_STALE_DAYS`).
- **Check:** `python3 scripts/check_data_freshness.py` reads `data.json`'s
  `generatedAt` (the data-snapshot time, not the build time) and exits
  `0` fresh / `1` stale / `2` unknown. The non-zero exit is the alert signal;
  set `CVS_FRESHNESS_WEBHOOK` to also POST a JSON alert when stale.
- **Last success:** the cron wrapper writes `LAST_SUCCESS_FILE`
  (default `~/.claude/logs/cvs-rebackfill.last-success`); the wrapper also runs
  the freshness check after every successful run.
- **Existing local alerts** (WSL cron, outside the repo): `cvs-ci-healthcheck.py`
  and `cvs-rebackfill-healthcheck.py` post to Discord on prolonged failure.

Run the freshness check anywhere (CI, a monitor, manually) to detect a silently
stale site independently of the pipeline host.

## Backup

`data/posts.jsonl` (raw store, contains real PTT accounts — **never committed**,
the repo is public) is snapshotted weekly to `D:\Claude\backups\cvs-radar\`
(8 retained). Encrypted/durable off-host backup is tracked as review #9 part C
and not yet implemented.
