#!/usr/bin/env bash
# Long-running fund-batch guard.
#
# The local PostgreSQL postmaster is reclaimed by the environment when the
# tool/session that started it ends, and it does NOT stay resident across tool
# calls. A fund batch must therefore (1) start PostgreSQL inside THIS task's
# lifecycle and (2) hold it active for the whole run, otherwise every per-fund
# incremental-start query dies with AdminShutdown and the runner stalls.
#
# This guard starts the local postmaster (persistent PGDATA volume) if needed,
# waits until it accepts connections, runs a SELECT-1 keepalive for the duration
# of the batch, and execs the unbuffered runner forwarding every CLI argument.
#
# Usage (repo root):
#   scripts/guard_batch.sh --resume --limit 20 --max-batches 1 --job-id j \
#       --state-db output/batch/state.db
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PY="$ROOT/.venv/bin/python"
PGDATA="${PGDATA:-/home/user/Doubao/chats/38444826764535298/pgdata}"
DSN="postgresql://postgres@localhost:55432/fund_app"

export DATABASE_URL="${DATABASE_URL:-postgresql+psycopg://postgres@localhost:55432/fund_app}"
export FUND_DATA_SOURCE="${FUND_DATA_SOURCE:-eastmoney_direct}"
export PYTHONUNBUFFERED=1

echo "[guard] $(date +%T) ensuring PostgreSQL is up (pgdata=$PGDATA)"
"$PY" - "$PGDATA" "$DSN" <<'PYEOF'
import sys
import time
from pathlib import Path

import pgserver
import psycopg

pgdata = Path(sys.argv[1])
dsn = sys.argv[2]


def up() -> bool:
    try:
        with psycopg.connect(dsn, connect_timeout=3) as conn:
            conn.execute("SELECT 1")
        return True
    except Exception:
        return False


if up():
    print("[guard] PostgreSQL already accepting connections")
else:
    last: Exception | None = None
    for attempt in range(5):
        try:
            pgserver.pg_ctl(
                ["start", "-l", str(pgdata / "server.log"), "-w", "-t", "30"],
                pgdata=pgdata,
            )
            break
        except Exception as exc:  # transient stale-pid / startup race
            last = exc
            print(f"[guard] start retry {attempt}: {str(exc)[:140]}")
            time.sleep(3)
    else:
        raise SystemExit(f"[guard] could not start PostgreSQL: {last}")

    for _ in range(40):
        if up():
            break
        time.sleep(1)
    else:
        raise SystemExit("[guard] PostgreSQL did not become ready in time")

print("[guard] PostgreSQL ready")
PYEOF

# Hold the postmaster active for the whole batch (idle-reclaim guard).
(
  while true; do
    "$PY" -c "import psycopg;c=psycopg.connect('postgresql://postgres@localhost:55432/fund_app',connect_timeout=3);c.execute('SELECT 1');c.close()" 2>/dev/null || true
    sleep 15
  done
) &
KEEPALIVE_PID=$!
trap 'kill "$KEEPALIVE_PID" 2>/dev/null || true' EXIT

echo "[guard] $(date +%T) starting batch_sync with args: $*"
"$PY" -u scripts/batch_sync.py "$@"
rc=$?
echo "[guard] $(date +%T) batch_sync exited rc=$rc"
exit "$rc"
