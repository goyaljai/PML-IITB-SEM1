#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Flight scraper — daily cron entry.
#
# Installed by scripts/install.sh and invoked by crontab. Self-contained:
# every path is derived from the script's own location so the same file works
# regardless of where the repo is checked out.
#
# Flow:
#   1. Source ~/.scraper_secrets   (provides GH_PAT — kept OFF the repo)
#   2. Activate the venv           (created by install.sh)
#   3. pip install --upgrade fast-flights PyYAML  (per project requirement)
#   4. git fetch + reset --hard    (sync with origin; gitignored state survives)
#   5. python -m scraper           (the actual scrape; honours the lock)
#   6. On success only: commit donotdelete/data/ and push via PAT.
#
# Exit codes mirror the scraper's:
#   0  success (data committed)
#   2  canary failed
#   3  fare-rate gate tripped
#   4  another run was in progress (lock contention)
#   5  unexpected scraper error
#   6  missing GH_PAT (cannot push)
#   7  push failed after retries
# ─────────────────────────────────────────────────────────────────────────────

set -uo pipefail

# Resolve installation root from the script's own location — no hard-coded path.
SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"
SCRAPER_BASE="$(cd "$SCRIPT_DIR/.." && pwd)"            # → donotdelete/
INSTALL_ROOT="$(cd "$SCRAPER_BASE/.." && pwd)"          # → repo root
VENV="$INSTALL_ROOT/.scraper-venv"
LOG_DIR="$SCRAPER_BASE/logs"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_LOG="$LOG_DIR/cron-$STAMP.log"

mkdir -p "$LOG_DIR"
exec >>"$RUN_LOG" 2>&1

echo "=== cron_run.sh start $STAMP ==="
echo "install_root=$INSTALL_ROOT"
echo "scraper_base=$SCRAPER_BASE"
echo "venv=$VENV"

# ── 0) Disk guard — refuse to run if the volume is dangerously full ─────────
# A failed write mid-scrape can corrupt the CSV; better to skip the day cleanly.
# Default threshold 2 GiB; override via DISK_MIN_GB env var (or scraper secrets).
DISK_MIN_GB="${DISK_MIN_GB:-2}"
FREE_KB=$(df -Pk "$INSTALL_ROOT" 2>/dev/null | awk 'NR==2 {print $4+0}')
if [ -n "$FREE_KB" ]; then
  FREE_GB=$(( FREE_KB / 1024 / 1024 ))
  echo "free_gb=$FREE_GB (threshold ${DISK_MIN_GB} GB)"
  if [ "$FREE_GB" -lt "$DISK_MIN_GB" ]; then
    echo "ERROR: only ${FREE_GB} GB free on $INSTALL_ROOT — refusing to run (threshold ${DISK_MIN_GB} GB)"
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
# Project requirement: never pin a fast-flights version; always pull latest.
# typing_extensions is a transitive dep that's been seen missing from a clean
# install of fast-flights==3.0.2 — installing it eagerly is cheap insurance.
echo "--- pip upgrade ---"
python -m pip install --quiet --upgrade pip || echo "WARN: pip self-upgrade failed"
python -m pip install --quiet --upgrade fast-flights PyYAML typing_extensions || {
  echo "ERROR: pip upgrade failed; aborting before scrape"
  exit 5
}
python -c "import fast_flights; print('fast_flights =', getattr(fast_flights, '__version__', 'unknown'))" \
  || { echo "ERROR: fast_flights not importable after upgrade"; exit 5; }

# ── 4) Sync repo state with origin ──────────────────────────────────────────
# Gitignored state (logs/, .batch_state, .lock) survives `reset --hard`.
cd "$INSTALL_ROOT" || exit 5
git config --local user.name  "goyaljai"
git config --local user.email "goyaljai.y14@gmail.com"
git config --local pull.rebase true
git fetch origin main --quiet || { echo "ERROR: git fetch failed"; exit 5; }
git reset --hard origin/main --quiet
git lfs install --local --quiet || true
git lfs pull --quiet || true

# ── 5) Run the scraper ──────────────────────────────────────────────────────
echo "--- scraper begin ---"
cd "$SCRAPER_BASE" || exit 5
python -m scraper
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
    git commit -m "data(flights): ${DATE_TAG} (run ${STAMP})"
    if [ -z "${GH_PAT:-}" ]; then
      echo "ERROR: GH_PAT not set in env — cannot push (commit is local only)"
      exit 6
    fi
    # Credential helper reads GH_PAT from env — PAT never appears in argv,
    # in the remote URL, or in any file on disk written by this script.
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

# ── Log rotation: trim cron-*.log to last 90 days ──────────────────────────
find "$LOG_DIR" -maxdepth 1 -name "cron-*.log" -mtime +90 -delete 2>/dev/null || true

echo "=== cron_run.sh end rc=$SCRAPE_RC ==="
exit $SCRAPE_RC
