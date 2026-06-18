# Operations runbook

Day-to-day operation for the daily flight-data cron. Designed to be readable
mid-incident — short sections, exact commands.

## Daily health check (60 seconds)

```bash
ssh root@<vps>
bash /opt/PML-IITB-SEM1/donotdelete/scripts/healthcheck.sh
```

What "healthy" looks like:
  * Lock free.
  * Latest cron-*.log has `rc=0`, fare_rate ≥ 60 %, budget_hit=False.
  * Newest CSV mtime < 36 h (cron fires at 12:47 UTC = 6:17 PM IST daily).
  * No errors in the last 7 days section.

## When a run fails — symptoms → diagnosis

| Symptom | Look here | Likely cause | First action |
|---|---|---|---|
| `rc=2` (canary failed) | `logs/scraper.log` for the run, lines starting with `canary` | fast-flights upstream broken, hard IP block, or DNS issue | Try `manual_run.sh --canary-only`. If still failing, `curl -I https://www.google.com/travel/flights` from the VPS. |
| `rc=3` (fare-rate gate) | `cron-*.log`, the `scrape end` line | Partial outage: many routes returned no fares | Re-run manually; if still bad, check fast-flights upstream issues. |
| `rc=4` (lock contention) | `cat donotdelete/.lock` | Another scrape is running (manual run, or previous cron hasn't finished) | Wait, or kill the holder PID. |
| `rc=5` (unexpected) | Full `cron-*.log`, stderr trace | Code bug, missing dependency | Read trace; reproduce with `manual_run.sh --smoke`. |
| `rc=6` (no GH_PAT) | `~/.scraper_secrets` | PAT not set or file unreadable | `chmod 600 ~/.scraper_secrets`, edit, re-source. |
| `rc=7` (push retries failed) | `cron-*.log` "push attempt" lines | PAT expired/revoked, branch protection, or net issue | Generate fresh PAT, edit `~/.scraper_secrets`. |
| No log file at all | `crontab -l`, `systemctl status cron`, MAILTO | cron daemon not running, or crontab entry missing | `systemctl start cron && systemctl enable cron`; reinstall: `bash donotdelete/scripts/install.sh`. |
| Old `rc=0` but no new data | `git log donotdelete/data/ -10` | All routes returning `NoFlights` (still counts as healthy fare_rate=0% if no errors) — but no fares means upstream is degraded silently | Drop `min_success_rate` floor temporarily, investigate upstream. |

## Manually running a partial scrape

```bash
cd /opt/PML-IITB-SEM1
# Canary only (~30s):
bash donotdelete/scripts/manual_run.sh --canary-only
# A handful of routes (~3 min):
bash donotdelete/scripts/manual_run.sh --routes BOM:DEL,DEL:BOM
# A handful of routes × 1 horizon (~30s):
bash donotdelete/scripts/manual_run.sh --routes BOM:DEL --horizons 7
# Smoke (1 route × 1 horizon, no data committed by default):
bash donotdelete/scripts/manual_run.sh --smoke
```

`manual_run.sh` always passes `--no-advance` to the scraper, so the rotation
counter is left intact. The CSV IS written (good — those rows are valid data),
but `cron_run.sh` is the only path that commits and pushes.

## Replaying a failed day

If today's cron failed (rc != 0), the rotation counter did NOT advance.
Tomorrow's cron will retry the same batch automatically. To replay manually:

```bash
cd /opt/PML-IITB-SEM1
# Replays current batch — DOES advance the counter on success.
bash donotdelete/scripts/cron_run.sh
```

## Skipping a batch on purpose

If a batch is consistently failing (e.g. one route the API hates), and you
want to move on:

```bash
echo "$(( $(cat donotdelete/data/.batch_state) + 1 ))" > donotdelete/data/.batch_state
```

Document the skip in `logs/` so future-you knows what happened.

## Rotating logs (already automated)

`cron_run.sh` deletes `cron-*.log` older than 90 days.
`logger.py` rotates `scraper.log` daily, keeping `log_retention_days` (default
30) backups. So a year of operation leaves ~30 daily `scraper.log.YYYY-MM-DD`
files plus the live `scraper.log`, and ~90 per-run `cron-*.log` files —
combined disk use is well under 100 MB.

To shorten retention temporarily:

```bash
# In donotdelete/config/scraper.yaml:
log_retention_days: 7
```

…or as a one-off env override:

```bash
SCRAPER_LOG_RETENTION_DAYS=7 bash donotdelete/scripts/manual_run.sh --smoke
```

## Disk-pressure guard (manual; consider automating)

The scraper does not check free disk itself. If `df -h` shows the VPS volume
above 90 %:

```bash
# Look for the biggest local consumers:
du -sh /opt/PML-IITB-SEM1/* | sort -h
du -sh /var/log/* | sort -h
# Quick free-up: prune old logs and APT cache.
find /opt/PML-IITB-SEM1/donotdelete/logs -name 'cron-*.log' -mtime +14 -delete
apt-get clean
```

## Verifying data integrity

```bash
# Row count by month:
for f in /opt/PML-IITB-SEM1/donotdelete/data/flights_*.csv; do
  echo "$(wc -l < "$f") $f"
done
# Schema versions present:
awk -F, 'NR>1 {print $1}' /opt/PML-IITB-SEM1/donotdelete/data/flights_*.csv | sort | uniq -c
# Categories present:
awk -F, 'NR>1 {print $28}' /opt/PML-IITB-SEM1/donotdelete/data/flights_*.csv | sort | uniq -c
# Distinct routes covered in current month:
awk -F, 'NR>1 {print $14"->"$15}' /opt/PML-IITB-SEM1/donotdelete/data/flights_$(date +%Y_%m).csv \
  | sort -u | wc -l
```

## Timezone hygiene

`Scrape_Timestamp` is **local time** (no offset stored). To avoid confusion:

```bash
# Recommended VPS timezone for an Indian-flights dataset:
timedatectl set-timezone Asia/Kolkata
```

`Run_Id` is always UTC, so cross-referencing with logs is unambiguous even if
the VPS timezone changes.
