#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Flight scraper — TIME-SLICED daily cron entry.
#
# Variant of cron_run.sh that scrapes only ONE slice of the day's rotation
# batch, then commits+pushes its own rows. Installed as N crontab entries
# (default 8, one every 3 h) so a day's 70-route batch is spread across 24 h —
# keeping the per-IP request rate low enough to avoid Google's rate-limit
# (observed 2026-06-18: dense bursts got the VPS IP blocked after ~130 calls).
#
# Usage (from crontab):
#   cron_slice.sh I N      # scrape slice I of N (1-based), commit+push
# e.g. the 3rd of 8 slices:
#   /opt/PML-IITB-SEM1/donotdelete/scripts/cron_slice.sh 3 8
#
# Design notes:
#   * COMMIT PER SLICE: every slice independently commits+pushes, so a crash or
#     reboot loses at most one slice's rows — not the whole day.
#   * ROTATION: only the FINAL slice (I==N) advances the rotation counter
#     (handled inside `python -m scraper --route-slice I/N`), so the 3-day batch
#     cycle is preserved exactly as with the monolithic cron_run.sh.
#   * Each slice writes its own timestamped log: cron-slice-<I>of<N>-<STAMP>.log
#
# KNOWN LIMITATION (by design, acceptable for a rolling year-long dataset):
#   Each slice has its own fare-rate gate over its ~8-route subset. If a
#   NON-final slice trips the gate (or errors), that slice's routes are simply
#   absent from today's data — there is no same-day per-slice retry. The whole
#   batch is retried tomorrow only if the counter didn't advance. Because the
#   horizons roll forward daily, a single missed slice = one missing daily
#   snapshot for ~8 routes, not a structural gap. If per-slice completeness ever
#   matters, add per-slice state tracking + a catch-up run.
#
# Exit codes mirror the scraper's (see cli.py):
#   0 success · 2 canary failed · 3 fare-rate gate · 4 lock · 5 error
#   6 missing GH_PAT · 7 push failed
# ─────────────────────────────────────────────────────────────────────────────

set -uo pipefail

SLICE_I="${1:?usage: cron_slice.sh I N  (e.g. 3 8)}"
SLICE_N="${2:?usage: cron_slice.sh I N  (e.g. 3 8)}"

# Validate slice args up front so a bad crontab line fails loudly with the
# documented exit code (5) rather than a bare Python SystemExit (exit 1, which
# isn't in this script's exit-code map). Must be integers with 1 ≤ I ≤ N.
if ! [[ "$SLICE_I" =~ ^[0-9]+$ ]] || ! [[ "$SLICE_N" =~ ^[0-9]+$ ]] \
   || [ "$SLICE_N" -lt 1 ] || [ "$SLICE_I" -lt 1 ] || [ "$SLICE_I" -gt "$SLICE_N" ]; then
  echo "ERROR: invalid slice args I=$SLICE_I N=$SLICE_N (need integers, 1 ≤ I ≤ N)" >&2
  exit 5
fi

SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"
SCRAPER_BASE="$(cd "$SCRIPT_DIR/.." && pwd)"            # → donotdelete/
INSTALL_ROOT="$(cd "$SCRAPER_BASE/.." && pwd)"          # → repo root
VENV="$INSTALL_ROOT/.scraper-venv"
LOG_DIR="$SCRAPER_BASE/logs"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_LOG="$LOG_DIR/cron-slice-${SLICE_I}of${SLICE_N}-$STAMP.log"

mkdir -p "$LOG_DIR"
exec >>"$RUN_LOG" 2>&1

echo "=== cron_slice.sh start $STAMP (slice ${SLICE_I}/${SLICE_N}) ==="
echo "install_root=$INSTALL_ROOT"

# ── 0) Disk guard ───────────────────────────────────────────────────────────
DISK_MIN_GB="${DISK_MIN_GB:-2}"
FREE_KB=$(df -Pk "$INSTALL_ROOT" 2>/dev/null | awk 'NR==2 {print $4+0}')
if [ -n "$FREE_KB" ]; then
  FREE_GB=$(( FREE_KB / 1024 / 1024 ))
  echo "free_gb=$FREE_GB (threshold ${DISK_MIN_GB} GB)"
  if [ "$FREE_GB" -lt "$DISK_MIN_GB" ]; then
    echo "ERROR: only ${FREE_GB} GB free on $INSTALL_ROOT — refusing to run"
    exit 5
  fi
fi

# ── 1) Secrets ──────────────────────────────────────────────────────────────
if [ -f "$HOME/.scraper_secrets" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$HOME/.scraper_secrets"
  set +a
else
  echo "WARN: $HOME/.scraper_secrets missing — push will fail later if GH_PAT is unset"
fi

# ── 2) Virtualenv ───────────────────────────────────────────────────────────
if [ ! -x "$VENV/bin/python" ]; then
  echo "ERROR: venv missing at $VENV. Run scripts/install.sh first."
  exit 5
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"
echo "python=$(python -V 2>&1) at $(command -v python)"

# ── 3) Refresh fast-flights to latest before every run ──────────────────────
echo "--- pip upgrade ---"
python -m pip install --quiet --upgrade pip || echo "WARN: pip self-upgrade failed"
python -m pip install --quiet --upgrade fast-flights PyYAML typing_extensions \
  || echo "WARN: pip upgrade failed; falling back to currently-installed version"
python -c "import fast_flights; from importlib.metadata import version, PackageNotFoundError
try: v = version('fast-flights')
except PackageNotFoundError: v = 'unknown'
print('fast_flights =', v)" \
  || { echo "ERROR: fast_flights not importable (no usable version present)"; exit 5; }

# ── 4) Sync repo state with origin ──────────────────────────────────────────
# Same loss-averse sync as cron_run.sh: commit any orphaned rows, then
# fetch+rebase --autostash (never reset --hard).
cd "$INSTALL_ROOT" || exit 5
git config --local user.name  "goyaljai"
git config --local user.email "goyaljai.y14@gmail.com"
git config --local pull.rebase true

if [ -n "$(git status --porcelain -- donotdelete/data/ 2>/dev/null)" ]; then
  echo "Recovering rows from prior crashed run — committing donotdelete/data/"
  git add donotdelete/data/
  git commit -m "data(flights): recovery commit from prior crashed run ($STAMP)" \
    --allow-empty || true
fi

git fetch origin main --quiet || { echo "ERROR: git fetch failed"; exit 5; }
if ! git pull --rebase --autostash origin main --quiet; then
  echo "ERROR: rebase failed — leaving repo for manual inspection"
  git rebase --abort 2>/dev/null || true
  exit 5
fi
git lfs install --local --quiet || true
git lfs pull --quiet || true

# ── 5) Run the scraper for this slice ───────────────────────────────────────
echo "--- scraper begin (slice ${SLICE_I}/${SLICE_N}) ---"
cd "$SCRAPER_BASE" || exit 5
python -m scraper --route-slice "${SLICE_I}/${SLICE_N}"
SCRAPE_RC=$?
echo "--- scraper end rc=$SCRAPE_RC ---"

# ── 6) Commit & push only on full success ───────────────────────────────────
if [ "$SCRAPE_RC" -eq 0 ]; then
  cd "$INSTALL_ROOT" || exit 5
  git add donotdelete/data/
  if git diff --cached --quiet; then
    echo "No new data to commit — exiting clean"
  else
    DATE_TAG="$(date -u +%Y-%m-%d)"
    git commit -m "data(flights): ${DATE_TAG} slice ${SLICE_I}/${SLICE_N} (run ${STAMP})"
    if [ -z "${GH_PAT:-}" ]; then
      echo "ERROR: GH_PAT not set in env — cannot push (commit is local only)"
      exit 6
    fi
    PUSH_OK=0
    for attempt in 1 2 3; do
      if git -c credential.helper='!f() { echo "username=goyaljai"; echo "password=$GH_PAT"; }; f' \
             push origin HEAD:main; then
        echo "Push OK on attempt $attempt"
        PUSH_OK=1
        break
      fi
      echo "Push attempt $attempt failed — re-syncing and retrying"
      git fetch origin main --quiet || true
      git rebase origin/main || git rebase --abort
      sleep $((5 * attempt))
    done
    if [ "$PUSH_OK" -ne 1 ]; then
      echo "ERROR: push failed after 3 attempts"
      exit 7
    fi
  fi
else
  echo "Scraper exit code $SCRAPE_RC — NOT committing"
fi

# ── Log rotation: trim slice + legacy cron logs to last 90 days ─────────────
find "$LOG_DIR" -maxdepth 1 -name "cron-*.log" -mtime +90 -delete 2>/dev/null || true

echo "=== cron_slice.sh end rc=$SCRAPE_RC (slice ${SLICE_I}/${SLICE_N}) ==="
exit $SCRAPE_RC
