#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Flight scraper — one-shot VPS installer.
#
# Run this ONCE on the Hostinger VPS (as root, since cron will run as root):
#
#     git clone https://github.com/goyaljai/PML-IITB-SEM1.git /opt/PML-IITB-SEM1
#     cd /opt/PML-IITB-SEM1
#     bash donotdelete/scripts/install.sh
#
# Re-running is idempotent: existing venv is updated in place, crontab line is
# de-duped, secrets file is never overwritten.
#
# What this does (and only this):
#   * Verify Python 3.11+ is present (installs python3-pip / venv on apt-based).
#   * Create a venv at $REPO/.scraper-venv and install deps.
#   * Create $HOME/.scraper_secrets (chmod 600) if it does not exist — with a
#     template the operator must fill in (GH_PAT).
#   * Install Git LFS (required for the CSV dataset).
#   * Add the cron entry idempotently.
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"
SCRAPER_BASE="$(cd "$SCRIPT_DIR/.." && pwd)"
INSTALL_ROOT="$(cd "$SCRAPER_BASE/.." && pwd)"
VENV="$INSTALL_ROOT/.scraper-venv"
# Default fire time: 12:47 UTC = 18:17 IST (≈ 6:17 PM IST, inside the
# requested 6–7 PM IST window). The minute is intentionally NOT :00/:30 to
# avoid colliding with other people's cron jobs. Override by passing
# `SCRAPER_CRON_LINE="47 12 * * * …"` env when invoking this installer.
CRON_LINE="${SCRAPER_CRON_LINE:-47 12 * * * $SCRIPT_DIR/cron_run.sh >/dev/null 2>&1}"
SECRETS_FILE="$HOME/.scraper_secrets"

echo "==> install root: $INSTALL_ROOT"
echo "==> venv:         $VENV"
echo "==> cron entry:   $CRON_LINE"

# 1) System prereqs (best-effort on apt-based — silently skip on other distros).
if command -v apt-get >/dev/null 2>&1; then
  echo "==> apt: ensuring python3, venv, pip, git, git-lfs, cron"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq python3 python3-venv python3-pip git git-lfs cron \
    >/dev/null
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 not found and apt is unavailable. Install Python 3.11+ manually."
  exit 1
fi

PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "==> Python: $PY_VER"
PY_MAJ=$(echo "$PY_VER" | cut -d. -f1)
PY_MIN=$(echo "$PY_VER" | cut -d. -f2)
if [ "$PY_MAJ" -lt 3 ] || { [ "$PY_MAJ" -eq 3 ] && [ "$PY_MIN" -lt 11 ]; }; then
  echo "WARN: python $PY_VER is below 3.11 — fast-flights typically supports 3.10+, but 3.11+ is recommended"
fi

# 2) Virtual environment.
if [ ! -x "$VENV/bin/python" ]; then
  echo "==> creating venv at $VENV"
  python3 -m venv "$VENV"
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"
python -m pip install --quiet --upgrade pip wheel
python -m pip install --quiet --upgrade fast-flights PyYAML typing_extensions
echo "==> venv ready (fast_flights $(python -c 'import fast_flights; print(getattr(fast_flights, "__version__", "?"))'))"
python -m pip install --quiet --upgrade pytest

# 3) Git LFS — fetch the existing dataset and the LFS hooks for committing CSVs.
if command -v git-lfs >/dev/null 2>&1; then
  cd "$INSTALL_ROOT"
  git lfs install --local
  git lfs pull
  echo "==> git-lfs initialised and dataset pulled"
else
  echo "WARN: git-lfs not installed. Dataset CSV may grow without LFS — install git-lfs ASAP."
fi

# 4) Secrets file template — never overwritten.
if [ ! -f "$SECRETS_FILE" ]; then
  umask 077
  cat > "$SECRETS_FILE" <<'EOF'
# Flight scraper secrets — sourced by donotdelete/scripts/cron_run.sh.
# This file is read by /bin/bash; every secret must be exported.
#
# 1) GitHub fine-grained PAT for goyaljai/PML-IITB-SEM1 with "Contents: read/write".
#    Generate at: https://github.com/settings/personal-access-tokens
#    Then replace the placeholder below.
#
export GH_PAT="REPLACE_ME_WITH_GH_PAT"
EOF
  chmod 600 "$SECRETS_FILE"
  echo "==> wrote $SECRETS_FILE (chmod 600) — EDIT IT BEFORE THE FIRST CRON FIRES"
else
  chmod 600 "$SECRETS_FILE"
  echo "==> $SECRETS_FILE already exists — left untouched (chmod 600 enforced)"
fi

# 5) Cron entry — idempotent install.
if command -v crontab >/dev/null 2>&1; then
  TMP_CRON="$(mktemp)"
  trap 'rm -f "$TMP_CRON"' EXIT
  crontab -l 2>/dev/null > "$TMP_CRON" || true
  # Strip any prior line referring to our script (handles relocations / version bumps).
  grep -v -F "$SCRIPT_DIR/cron_run.sh" "$TMP_CRON" > "$TMP_CRON.new" || true
  mv "$TMP_CRON.new" "$TMP_CRON"
  echo "$CRON_LINE" >> "$TMP_CRON"
  crontab "$TMP_CRON"
  echo "==> crontab updated — current entries:"
  crontab -l | sed 's/^/    /'
else
  echo "WARN: crontab(1) not found. Add this line to your scheduler manually:"
  echo "    $CRON_LINE"
fi

cat <<EOF

==============================================================================
 install.sh DONE.

 Next steps for the operator:
   1. Edit $SECRETS_FILE and set GH_PAT to a real token.
   2. (Optional but recommended) Run a smoke test:
        bash $SCRIPT_DIR/manual_run.sh --smoke
   3. The scrape will run automatically at 12:47 UTC (= 18:17 IST) every day.
   4. Inspect logs/runs with:
        bash $SCRIPT_DIR/healthcheck.sh
==============================================================================
EOF
