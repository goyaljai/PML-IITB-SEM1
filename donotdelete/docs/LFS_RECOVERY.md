# Git LFS — setup, verification, recovery

The flight dataset CSVs are tracked by Git LFS. This isn't decorative: a year
of daily appends produces 12 monthly CSVs of ~1 MB each, which is fine for
LFS but slow for plain git (full re-pack on every commit). LFS keeps the main
git history light and gives us pointer-only checkouts when we only need code.

## What's tracked

`.gitattributes` (at the repo root):

```
*.csv filter=lfs diff=lfs merge=lfs -text
*.db  filter=lfs diff=lfs merge=lfs -text
*.zip filter=lfs diff=lfs merge=lfs -text
```

→ every `*.csv` file in any directory is stored via LFS. The flight scraper's
`donotdelete/data/flights_*.csv` files are covered by this rule, as is the
coursework's `edge_detection/CSVs/*.csv` etc.

## Verifying LFS is wired up

```bash
# 1) Client install (per-checkout).
git lfs install --local

# 2) The hooks exist (post-checkout, post-commit, post-merge, pre-push).
ls -la .git/hooks | grep -E 'lfs|post-|pre-'

# 3) The pattern actually fires.
git check-attr --all -- donotdelete/data/flights_2026_06.csv
# Expected: filter: lfs, diff: lfs, merge: lfs

# 4) After a commit, the CSV is a pointer in git but a real file on disk.
git cat-file -p HEAD:donotdelete/data/flights_2026_06.csv | head -3
# Expected pointer:
#   version https://git-lfs.github.com/spec/v1
#   oid sha256:…
#   size <bytes>

# 5) LFS objects are present locally.
git lfs ls-files | head
```

## Adding LFS to a fresh clone

```bash
git clone https://github.com/goyaljai/PML-IITB-SEM1.git
cd PML-IITB-SEM1
git lfs install --local          # registers the smudge/clean filters
git lfs pull                     # downloads the actual CSV bytes
```

`donotdelete/scripts/install.sh` runs both of these automatically on the VPS.

## When a CSV looks corrupt or is a stale pointer

Symptom: `donotdelete/data/flights_2026_06.csv` is 132 bytes long and starts
with `version https://git-lfs.github.com/spec/v1`.

```bash
# Pull the real content.
git lfs pull

# Or if a specific file is corrupt, re-fetch it directly.
git lfs fetch --include="donotdelete/data/flights_2026_06.csv"
git lfs checkout donotdelete/data/flights_2026_06.csv
```

## Recovering from "LFS quota exceeded"

GitHub free-tier LFS storage and bandwidth are limited. If you hit the cap:

1. The scraper continues writing locally. `git push` is the operation that
   fails (the LFS push of the new CSV bytes is rejected).
2. `cron_run.sh` will retry 3× then exit code 7. The local commit is intact.
3. To unblock:
   * Buy a GitHub LFS data pack (~$5/mo for 50 GB), OR
   * Switch the LFS remote to a self-hosted server (e.g. `git-lfs-s3`):
     ```bash
     git config -f .lfsconfig lfs.url https://<your-server>/lfs/PML-IITB-SEM1
     git commit -am "lfs: switch remote"
     git lfs push --all <new-remote-name>
     ```

## Migrating an existing CSV out of LFS (rare)

If you ever need to remove a CSV from LFS tracking — e.g. it's small and the
team wants `git diff` to show actual changes:

```bash
git lfs migrate export --include="path/to/file.csv" --everything
git push --force-with-lease     # rewrites history; coordinate with collaborators
```

## Disaster: the dataset is gone from the VPS but in LFS

```bash
cd /opt/PML-IITB-SEM1
git fetch --all
git reset --hard origin/main
git lfs pull
# `donotdelete/data/flights_*.csv` are now restored from LFS.
```

## Sanity test of the full LFS round-trip

`donotdelete/tests/test_lfs_smoke.sh` — runs locally OR on the VPS and:

1. Verifies `.gitattributes` claims `*.csv` for LFS.
2. Verifies the most recent CSV in `donotdelete/data/` is an LFS object.
3. Verifies a roundtrip `git lfs ls-files | grep <basename>` finds it.

Run any time:

```bash
bash donotdelete/tests/test_lfs_smoke.sh
```
