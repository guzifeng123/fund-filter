#!/usr/bin/env bash
# cron_batch_tick.sh - one resumable shard tick of the coalesced full-market job.
#
# Designed to be invoked by the platform scheduler every few minutes. It is
# idempotent and non-overlapping:
#   * flock(-n) on a fixed lockfile: if the previous tick is still running this
#     tick exits 0 immediately instead of stacking runners;
#   * delegates PostgreSQL ensure/keepalive and the actual run to guard_batch.sh
#     (--resume), processing exactly TICK_MAX_BATCHES planned batch(es) per tick;
#   * all batches of a fixed job accumulate into ONE cross-process staging
#     generation in PostgreSQL (coalesced); the generation is published only
#     after the pending set is exhausted;
#   * appends a progress line to output/batch/tick.log after every tick.
#
# A tick killed mid-batch by the sandbox's background-process reclamation is
# harmless: claimed rows stay in_flight and are reclaimed by the next --resume,
# and already-staged funds are committed but stay invisible until final publish.
set -uo pipefail

ROOT="/home/user/Doubao/chats/38444826764535298/fund-filter"
LOCK_FILE="/tmp/fund-full-cron.lock"
JOB_ID="${FULL_JOB_ID:-fund-full-20260930}"
STATE_DB="${FULL_STATE_DB:-$ROOT/output/batch/state.db}"
LOG_FILE="$ROOT/output/batch/tick.log"
MAX_BATCHES="${TICK_MAX_BATCHES:-1}"
# Funds claimed per tick batch: 40 funds * ~6.7s/fund ≈ 270s, inside the sandbox's
# ~5min background-command window (eastmoney jitter can still occasionally exceed
# it; a killed tick is safe and reclaimed by the next --resume). Override with
# TICK_BATCH_SIZE. The runner reads this as FUND_BATCH_SIZE.
BATCH_SIZE="${TICK_BATCH_SIZE:-40}"
export FUND_BATCH_SIZE="$BATCH_SIZE"

# Non-blocking exclusive lock for the whole tick.
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  mkdir -p "$(dirname "$LOG_FILE")"
  echo "$(date '+%F %T') [tick] lock busy; another tick is running, skipping" >>"$LOG_FILE"
  exit 0
fi

mkdir -p "$(dirname "$LOG_FILE")"
echo "$(date '+%F %T') [tick] start job=$JOB_ID max_batches=$MAX_BATCHES batch_size=$BATCH_SIZE" >>"$LOG_FILE"

cd "$ROOT"
bash scripts/guard_batch.sh \
  --resume \
  --max-batches "$MAX_BATCHES" \
  --job-id "$JOB_ID" \
  --state-db "$STATE_DB" >>"$LOG_FILE" 2>&1
rc=$?

STATE_DB="$STATE_DB" "$ROOT/.venv/bin/python" - >>"$LOG_FILE" 2>&1 <<'PY'
import os
import sqlite3

db = os.environ["STATE_DB"]
con = sqlite3.connect(db)
counts = dict(con.execute("SELECT status, COUNT(*) FROM fund_sync_state GROUP BY 1"))
order = ("pending", "in_flight", "done", "skipped", "failed")
print(
    "[tick] progress "
    + " ".join(f"{k}={counts.get(k, 0)}" for k in order)
    + f" remaining_pending={counts.get('pending', 0)}"
)
con.close()
PY

echo "$(date '+%F %T') [tick] end guard_rc=$rc" >>"$LOG_FILE"
exit "$rc"
