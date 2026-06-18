#!/usr/bin/env bash
#
# VM runner for the PML flight scraper — designed for the Mumbai (asia-south1)
# GCP VM, where fli works reliably (Indian IP). Runs the scraper inside a
# python:3.11-slim Docker container (the VM's system Python is 3.9), then
# commits and pushes the collected data.
#
# Cron installs this to run daily. All state lives under $WORKDIR so it never
# touches the shared VM's build artifacts.
#
# Required env (from ~/.pml_env, sourced below):
#   GH_PAT   — fine-grained PAT with contents:read/write on goyaljai/PML-IITB-SEM1
#
set -uo pipefail

WORKDIR="$HOME/pml-scraper"
REPO="github.com/goyaljai/PML-IITB-SEM1"
REPO_DIR="$WORKDIR/PML-IITB-SEM1"
LOG="$WORKDIR/run-$(date -u +%Y%m%d-%H%M%S).log"
IMAGE="python:3.11-slim"
MIN_FREE_GB=5    # alert/skip if VM disk is dangerously full

mkdir -p "$WORKDIR"
exec > >(tee -a "$LOG") 2>&1
echo "=== PML scraper VM run $(date -u +%FT%TZ) ==="

# 0) Disk guard — the shared VM's build artifacts can fill the disk.
free_gb=$(df -BG --output=avail "$HOME" | tail -1 | tr -dc '0-9')
echo "Free disk: ${free_gb}G"
if [ "${free_gb:-0}" -lt "$MIN_FREE_GB" ]; then
  echo "⛔ Less than ${MIN_FREE_GB}G free — skipping run to avoid corrupting state."
  exit 1
fi

# 1) Load credentials.
if [ -f "$HOME/.pml_env" ]; then
  # shellcheck disable=SC1091
  source "$HOME/.pml_env"
fi
if [ -z "${GH_PAT:-}" ]; then
  echo "⛔ GH_PAT not set (expected in ~/.pml_env). Cannot push."
  exit 1
fi
AUTH_URL="https://goyaljai:${GH_PAT}@${REPO}.git"

# 2) Clone or update the repo (with LFS).
if [ ! -d "$REPO_DIR/.git" ]; then
  echo "Cloning repo…"
  git clone "https://${REPO}.git" "$REPO_DIR" || { echo "clone failed"; exit 1; }
fi
cd "$REPO_DIR" || exit 1
git config user.name "goyaljai"
git config user.email "goyaljai.y14@gmail.com"
git fetch origin main --quiet
git reset --hard origin/main
git lfs pull || true

# 3) Run the scraper in a clean Python 3.11 container.
#    VM is an Indian IP, so fli works immediately: short canary, short delays.
echo "Running scraper in Docker ($IMAGE)…"
sudo docker run --rm \
  -v "$REPO_DIR":/work -w /work \
  -e PYTHONUNBUFFERED=1 \
  -e CANARY_MAX_WAIT_S=120 \
  -e CANARY_PROBE_INTERVAL_S=15 \
  -e DELAY_MIN_S=2 -e DELAY_MAX_S=5 \
  -e SCRAPE_BUDGET_MIN=60 \
  "$IMAGE" bash -c "pip install -q flights fast-flights && python scraper.py"
SCRAPE_RC=$?
echo "scraper exit code: $SCRAPE_RC"

# 4) Commit & push whatever data we have (even on partial/non-zero, so a budget
#    cut-off or gate trip still preserves collected rows).
git add temp/ || true
if git diff --cached --quiet; then
  echo "No new data to commit."
else
  git commit -m "🛫 Data: $(date -u +%Y-%m-%d) [vm]"
  for attempt in 1 2 3; do
    if git push "$AUTH_URL" main; then echo "Push OK"; break; fi
    echo "push attempt $attempt failed; resyncing…"
    git fetch origin main --quiet && git rebase origin/main || git rebase --abort
    [ "$attempt" -eq 3 ] && { echo "push failed after retries"; exit 1; }
  done
fi

echo "=== done $(date -u +%FT%TZ) (scrape rc=$SCRAPE_RC) ==="
# Prune old logs (keep last 14).
ls -1t "$WORKDIR"/run-*.log 2>/dev/null | tail -n +15 | xargs -r rm -f
exit $SCRAPE_RC
