# Deployment — Hostinger VPS

This document is the **only** deployment authority. The cron pipeline reads
this and nothing else.

## Target

| Property | Value |
|---|---|
| Provider | Hostinger |
| Host | `187.127.151.46` |
| User | `root` (the cron lives here; pick a non-root user if you prefer — see "Non-root install") |
| Schedule | `47 12 * * *` (12:47 UTC = 18:17 IST — start time inside the requested 6–7 PM IST window; scrape runs ≤ 2 h, so it finishes by ~20:17 IST) |
| Install path | `/opt/PML-IITB-SEM1/` (any path works — every script derives its install root from `dirname $0`) |
| Python | 3.11+ recommended (3.10 also works) |

## Credentials — handling rules

**No credentials live inside this repository.** Specifically:
  * No PATs, no SSH keys, no passwords in any tracked file.
  * No PATs in cron entries (`crontab -l` is readable to that user).
  * No PATs in `git config remote.origin.url`.
  * No PATs in documentation.

The only file on the VPS that contains the GitHub PAT is `~/.scraper_secrets`
(chmod 600). It's sourced by `donotdelete/scripts/cron_run.sh` and used
in-memory only via a `credential.helper` shell function — the PAT never
appears in process args (`ps`) or on the disk after the secrets file itself.

The PAT must be a fine-grained personal access token on
`goyaljai/PML-IITB-SEM1` with:
  * **Contents** → Read & Write
  * **Metadata** → Read (auto)

No other scopes. Set expiration to 1 year; rotate by editing
`~/.scraper_secrets` and re-saving — no code change needed.

## First-time install

```bash
# 1) Log in to the VPS interactively (NOT via this assistant — SSH-password auth
#    is intentionally not used by the install pipeline).
ssh root@187.127.151.46

# 2) Clone the repo into the install location.
cd /opt
git clone https://github.com/goyaljai/PML-IITB-SEM1.git
cd PML-IITB-SEM1

# 3) Run the one-shot installer (creates venv, installs deps, installs cron).
bash donotdelete/scripts/install.sh

# 4) Edit the secrets file the installer just created.
${EDITOR:-nano} ~/.scraper_secrets
# Set GH_PAT="ghp_…"  (or the github_pat_… fine-grained format)

# 5) Smoke-test end-to-end (will NOT commit or push — safe).
bash donotdelete/scripts/manual_run.sh --smoke

# 6) Verify health.
bash donotdelete/scripts/healthcheck.sh
```

The cron entry is now in place. The next scheduled run is at 12:47 UTC (=
6:17 PM IST) on the next calendar day.

## Non-root install (optional, recommended for prod)

```bash
# As root (one time):
adduser --disabled-password --gecos "" scraper
mkdir -p /opt/PML-IITB-SEM1 && chown scraper /opt/PML-IITB-SEM1

# As 'scraper':
sudo -u scraper -i
cd /opt/PML-IITB-SEM1
git clone https://github.com/goyaljai/PML-IITB-SEM1.git .
bash donotdelete/scripts/install.sh
${EDITOR:-nano} ~/.scraper_secrets   # set GH_PAT
```

The installer detects when run as a non-root user and writes the crontab and
secrets under that user's HOME automatically.

## Inspecting and operating

```bash
# Last few runs at a glance.
bash donotdelete/scripts/healthcheck.sh

# Per-run cron output.
ls -lh /opt/PML-IITB-SEM1/donotdelete/logs/cron-*.log | tail
tail -200 /opt/PML-IITB-SEM1/donotdelete/logs/cron-<stamp>.log

# Per-call structured log (TimedRotatingFileHandler — daily).
ls -lh /opt/PML-IITB-SEM1/donotdelete/logs/scraper.log*
tail -200 /opt/PML-IITB-SEM1/donotdelete/logs/scraper.log

# Currently held lock (if anything is running).
cat /opt/PML-IITB-SEM1/donotdelete/.lock

# Rotation state.
cat /opt/PML-IITB-SEM1/donotdelete/data/.batch_state

# Force a manual run (no rotation advance, no auto-push).
bash donotdelete/scripts/manual_run.sh                  # full ~2h batch
bash donotdelete/scripts/manual_run.sh --canary-only    # ~10s health probe
bash donotdelete/scripts/manual_run.sh --routes BOM:DEL,DEL:BOM
```

## What the cron actually does

`donotdelete/scripts/cron_run.sh` — invoked daily by `crontab(1)`:

1. Sources `~/.scraper_secrets` to populate `GH_PAT`.
2. Activates the venv at `/opt/PML-IITB-SEM1/.scraper-venv`.
3. Runs `pip install --upgrade fast-flights PyYAML typing_extensions`
   — **every run** pulls the latest fast-flights, per project requirement.
4. `git fetch origin main && git reset --hard origin/main` — pulls any
   commits made elsewhere (e.g. operator pushes). Gitignored runtime files
   (`logs/`, `.lock`, `.batch_state`) survive.
5. `python -m scraper` — full daily batch.
6. On exit code 0 only: `git add donotdelete/data/` → commit → push.
7. Trims `logs/cron-*.log` older than 90 days.

Exit-code contract:

| Code | Meaning | Cron behaviour |
|---|---|---|
| 0 | Healthy run, data committed and pushed | log + email (cron MAILTO if set) |
| 2 | Canary failed — fast-flights broken or hard IP block | data NOT touched; rotation NOT advanced; next cron retries |
| 3 | Fare-rate gate tripped — partial outage | no commit; rotation NOT advanced; next cron retries |
| 4 | Another scraper run was holding the lock | exit immediately |
| 5 | Unexpected script error | log; rotation may or may not have advanced — investigate |
| 6 | `GH_PAT` not in env at push time | commit is local-only; next cron will commit again on top |
| 7 | All push retries failed | commit is local-only; next cron will re-push |

## Updating the scraper

```bash
# On the VPS:
cd /opt/PML-IITB-SEM1
git fetch origin main
git reset --hard origin/main
# The next cron picks up the new code automatically (it re-pulls before
# every run). To use a new pip dep immediately:
bash donotdelete/scripts/install.sh    # idempotent re-install
```

## Rolling back

```bash
cd /opt/PML-IITB-SEM1
git reset --hard <good-sha>
git push origin main:main --force    # only if absolutely necessary
```

For data rollback, see `LFS_RECOVERY.md`.
