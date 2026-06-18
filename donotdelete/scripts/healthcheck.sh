#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Flight scraper — health check.
#
# Quick at-a-glance: when was the last successful scrape, how big is the
# current month's CSV, is the lock currently held, what was the most recent
# fare-rate?
#
# Safe to run while a scrape is in progress (read-only — no lock taken).
# ─────────────────────────────────────────────────────────────────────────────

set -uo pipefail

SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"
SCRAPER_BASE="$(cd "$SCRIPT_DIR/.." && pwd)"
DATA_DIR="$SCRAPER_BASE/data"
LOG_DIR="$SCRAPER_BASE/logs"
LOCK_FILE="$SCRAPER_BASE/.lock"
STATE_FILE="$DATA_DIR/.batch_state"

echo "── Flight scraper health ─────────────────────────────────────────"
echo "Scraper base: $SCRAPER_BASE"
echo "Time:         $(date -u +%FT%TZ)"
echo

# Lock state.
if [ -s "$LOCK_FILE" ]; then
  HOLDER=$(cat "$LOCK_FILE" 2>/dev/null || echo "<unreadable>")
  echo "Lock:         held by → $HOLDER"
  # flock check — does anyone actually hold the fcntl lock right now?
  if command -v flock >/dev/null 2>&1; then
    if flock -n "$LOCK_FILE" -c true 2>/dev/null; then
      echo "  └─ (advisory lock is actually FREE; breadcrumb is stale)"
    else
      echo "  └─ advisory lock IS active — a scrape is in progress"
    fi
  fi
else
  echo "Lock:         free"
fi

# Rotation state.
if [ -f "$STATE_FILE" ]; then
  COUNTER=$(cat "$STATE_FILE" 2>/dev/null || echo "?")
  echo "Rotation:     counter=$COUNTER  (next batch=$((COUNTER % 3 + 1))/3)"
else
  echo "Rotation:     unset — first cron will start at batch 1/3"
fi

# Dataset.
echo
echo "── Dataset ────────────────────────────────────────────────────────"
if [ ! -d "$DATA_DIR" ]; then
  echo "no data/ directory yet"
else
  ls -lh "$DATA_DIR"/flights_*.csv 2>/dev/null | head -12 || echo "no flights_*.csv yet"
fi

# Recent runs.
echo
echo "── Recent cron runs (last 5) ──────────────────────────────────────"
mapfile -t LOGS < <(ls -1t "$LOG_DIR"/cron-*.log 2>/dev/null | head -5)
if [ "${#LOGS[@]}" -eq 0 ]; then
  echo "no cron logs yet"
else
  for L in "${LOGS[@]}"; do
    RC=$(grep -E '^=== cron_run.sh end rc=' "$L" | tail -1 | sed -E 's/.*rc=([0-9]+).*/\1/' || echo "?")
    FARE=$(grep -E 'fare_rate=[0-9.]+' "$L" | tail -1 | sed -E 's/.*fare_rate=([0-9.]+).*/\1%/' || echo "?")
    ROWS=$(grep -E 'rows_written=[0-9]+' "$L" | tail -1 | sed -E 's/.*rows_written=([0-9]+).*/\1/' || echo "?")
    BUDGET=$(grep -E 'budget_hit=(True|False)' "$L" | tail -1 | sed -E 's/.*budget_hit=(True|False).*/\1/' || echo "?")
    BASE=$(basename "$L")
    printf "  %-32s  rc=%s  rows=%s  fare_rate=%s  budget=%s\n" "$BASE" "$RC" "$ROWS" "$FARE" "$BUDGET"
  done
fi

# Recent errors (any cron log in the last 7 days that didn't exit 0).
echo
echo "── Errors / non-zero exits (last 7 days) ──────────────────────────"
FOUND=0
while IFS= read -r L; do
  if grep -qE '^=== cron_run.sh end rc=[1-9]' "$L"; then
    BASE=$(basename "$L")
    LAST_ERR=$(grep -E 'ERROR|FAILED|gate trip|TIMEOUT' "$L" | tail -1)
    echo "  $BASE — ${LAST_ERR:-<no error message>}"
    FOUND=1
  fi
done < <(find "$LOG_DIR" -maxdepth 1 -name 'cron-*.log' -mtime -7 2>/dev/null)
[ "$FOUND" -eq 0 ] && echo "  none — clean week"

# Disk pressure.
echo
echo "── Disk ───────────────────────────────────────────────────────────"
df -h "$SCRAPER_BASE" 2>/dev/null | sed 's/^/  /' || true

# Stale-data warning.
echo
echo "── Freshness ──────────────────────────────────────────────────────"
LAST_CSV=$(ls -1t "$DATA_DIR"/flights_*.csv 2>/dev/null | head -1 || true)
if [ -n "$LAST_CSV" ]; then
  MTIME=$(stat -c %Y "$LAST_CSV" 2>/dev/null || stat -f %m "$LAST_CSV" 2>/dev/null)
  NOW=$(date -u +%s)
  AGE_H=$(( (NOW - MTIME) / 3600 ))
  echo "  newest CSV:   $LAST_CSV"
  echo "  mtime age:    ${AGE_H} h"
  if [ "$AGE_H" -gt 36 ]; then
    echo "  ⚠️  Data older than 36 h — investigate. Expected daily updates at 12:47 UTC (18:17 IST)."
  fi
else
  echo "  no CSV yet"
fi
