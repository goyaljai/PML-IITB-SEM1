#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Flight scraper — manual run wrapper.
#
# Same plumbing as cron_run.sh (venv, pip-upgrade, run) but does NOT commit or
# push — useful for smoke tests and ad-hoc collections. Output goes straight
# to stdout/stderr so you can see what's happening live.
#
# Usage:
#   bash donotdelete/scripts/manual_run.sh                # full batch (no commit)
#   bash donotdelete/scripts/manual_run.sh --smoke        # 1 route × 1 horizon
#   bash donotdelete/scripts/manual_run.sh --canary-only  # health probe only
#   bash donotdelete/scripts/manual_run.sh --routes BOM:DEL,DEL:BOM
# ─────────────────────────────────────────────────────────────────────────────

set -uo pipefail

SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"
SCRAPER_BASE="$(cd "$SCRIPT_DIR/.." && pwd)"
INSTALL_ROOT="$(cd "$SCRAPER_BASE/.." && pwd)"
VENV="$INSTALL_ROOT/.scraper-venv"

if [ ! -x "$VENV/bin/python" ]; then
  echo "venv missing — run scripts/install.sh first" >&2
  exit 5
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"

echo "==> upgrading fast-flights (latest)…"
python -m pip install --quiet --upgrade fast-flights PyYAML typing_extensions || {
  echo "WARN: pip upgrade failed — continuing with current versions" >&2
}
python -c "import fast_flights; print('fast_flights:', getattr(fast_flights, '__version__', 'unknown'))"

echo "==> running scraper (no auto-commit) — args: $*"
cd "$SCRAPER_BASE" || exit 5
python -m scraper "$@" --no-advance
RC=$?
echo "==> exit code: $RC"
exit $RC
