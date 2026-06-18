#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# LFS sanity check — referenced in docs/LFS_RECOVERY.md.
#
# Verifies:
#   1. .gitattributes claims *.csv → lfs
#   2. git lfs is installed and active in this repo
#   3. The newest CSV in donotdelete/data/ is tracked by LFS (if any exists)
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

# Resolve repo root from this script's location.
SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}")"
REPO_ROOT="$(cd "$(dirname "$SCRIPT_PATH")/../.." && pwd)"

cd "$REPO_ROOT"

echo "── LFS smoke test in $REPO_ROOT ──"

# 1) .gitattributes mentions *.csv → lfs.
if ! grep -qE '^\*\.csv\s.*filter=lfs' .gitattributes 2>/dev/null; then
  echo "FAIL: .gitattributes does not have '*.csv filter=lfs' rule"
  exit 1
fi
echo "  ✓ .gitattributes claims *.csv → lfs"

# 2) git lfs is installed.
if ! command -v git-lfs >/dev/null 2>&1; then
  echo "FAIL: git-lfs CLI not installed"
  exit 2
fi
echo "  ✓ git-lfs present: $(git lfs --version)"

# 3) LFS is enabled in this checkout.
if [ ! -f .git/hooks/post-merge ] || ! grep -q "git lfs" .git/hooks/post-merge 2>/dev/null; then
  echo "WARN: LFS hooks missing — run: git lfs install --local"
fi

# 4) The newest CSV under donotdelete/data/ is tracked.
NEWEST_CSV=$(ls -1t donotdelete/data/flights_*.csv 2>/dev/null | head -1 || true)
if [ -z "$NEWEST_CSV" ]; then
  echo "  (no flight CSV yet — skipping LFS-object check)"
else
  ATTR=$(git check-attr --all -- "$NEWEST_CSV" | grep -i lfs || true)
  if [ -z "$ATTR" ]; then
    echo "FAIL: $NEWEST_CSV is not LFS-tracked"
    exit 3
  fi
  echo "  ✓ $NEWEST_CSV → $(echo "$ATTR" | tr -s ' ')"
fi

echo "── LFS smoke OK ──"
