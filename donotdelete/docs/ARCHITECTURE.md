# Architecture

> The 30-page version is in `MIGRATION_REPORT.md` at the repo root. This file
> is the **engineering** view — module responsibilities, control flow, and
> the rationale for the major design choices.

## One-line summary

A single-source (fast-flights) flight-price scraper that runs once a day on
a VPS via cron, writes ≤ 420 rows to a monthly-partitioned CSV (LFS-tracked),
and pushes to GitHub. Configurable, validating, locking, append-only,
designed for 1+ year unattended operation.

## Why these choices

| Decision | Reason |
|---|---|
| **Single source (fast-flights)** | The legacy multi-source design (fli + fast-flights + playwright) made the v3 dataset 96 % bogus on non-Indian IPs because `fli`'s implausible-price rows leaked past the filter. Removing fli eliminates the failure class entirely. fast-flights is the only adapter that produced clean prices in the audit. |
| **Latest fast-flights, not pinned** | Per project requirement. Upstream protocol changes are frequent enough that a pin would silently rot. The cron `pip install --upgrade` runs before every scrape — at worst, a bad upstream release breaks one day's run, and the canary catches it before any data is committed. |
| **Cron, not GitHub Actions** | GitHub Actions runs on a US datacenter IP that Google Flights deprioritises (see legacy `probe_*.py`). A Hostinger VPS in Mumbai (or any IN-region IP) gets responsive results consistently. Cron also keeps the schedule under operator control without GitHub's rate limits. |
| **Slow scrape (~2 h/day)** | 420 calls × ~17 s = ~119 min. Spacing the requests out avoids burst-detection, and the ≤ 2 h ceiling fits comfortably inside one VPS hour-of-low-traffic. |
| **End-of-run commit** | The whole batch is one logical unit of work. Committing per-route would create 420 commits/day and pollute `git log`. One commit/day keeps history grep-friendly. |
| **Lock file via `fcntl.flock`** | The kernel releases the lock on process death — no PID file management, no stale-lock cleanup. A second concurrent run exits immediately with code 4. |
| **Rotation counter advance AFTER success** | v3 advanced BEFORE the scrape, so a crashed run silently skipped that batch. v4 advances only on a clean exit. |
| **Plausibility band [₹1k, ₹200k]** | Indian-domestic economy fares fit comfortably inside this range. Anything outside is a parsing artefact and is dropped before the row hits the CSV. |
| **Monthly file partitioning** | A single ever-growing CSV makes `git diff`, `pd.read_csv`, and LFS chunking all slow over time. Monthly partitions keep each file ~1 MB. |
| **Schema v4 additive over v3** | The 29 v3 columns remain byte-compatible; 4 v4 columns appended. Downstream `pd.read_csv` of a year of v3 + a year of v4 works without code changes. |

## Module map

```
donotdelete/scraper/
├── __init__.py        # package marker; __version__
├── __main__.py        # entry: `python -m scraper`
├── cli.py             # arg parsing, exit codes, top-level orchestration
├── canary.py          # startup health check (patient retry for IP warm-up)
├── pipeline.py        # the actual scrape loop (delays, gate, advance)
├── adapter.py         # fast-flights wrapper → NormalizedFlight (retries, timeout)
├── routes.py          # IATA codes, all_routes(), 3-day rotation
├── writer.py          # atomic append, monthly partitioning, fsync per row
├── validator.py       # per-row schema + plausibility checks
├── lockfile.py        # fcntl-based exclusive lock (kernel auto-release)
├── logger.py          # structured logging, daily-rotated file + stderr
├── state.py           # run_id generator
├── config.py          # YAML loader with env-var overrides, sane defaults
└── schema.py          # CSV_HEADERS, SCHEMA_VERSION, category constants
```

## Control flow (cron run)

```
cron_run.sh
  ├─ source ~/.scraper_secrets            (GH_PAT)
  ├─ activate venv
  ├─ pip install --upgrade fast-flights   (latest, every run)
  ├─ git fetch + reset --hard origin/main (sync code; gitignored state survives)
  ├─ python -m scraper
  │     ├─ cli.main()
  │     │     ├─ config.load()                       # YAML + env overrides
  │     │     ├─ logger.setup()                      # stderr + daily-rotated file
  │     │     ├─ lockfile.acquire(.lock)             # fcntl LOCK_EX|LOCK_NB
  │     │     ├─ canary.run()                        # one BOM→DEL probe (patient)
  │     │     │     └─ adapter.search_flights() ← retries + timeout
  │     │     ├─ pipeline.run()
  │     │     │     ├─ routes.current_batch()        # PURE READ — no advance
  │     │     │     ├─ for (origin, dest) in batch:
  │     │     │     │     for days in [1,3,7,14,30,60]:
  │     │     │     │         adapter.search_flights()
  │     │     │     │         pipeline._rows_for_search()  → Best/Cheapest/Median
  │     │     │     │         validator.validate_row()     → drop invalid
  │     │     │     │         writer.append_rows()         → fsync per row
  │     │     │     │         random delay
  │     │     │     ├─ long_pause every N routes
  │     │     │     └─ honour wall-clock budget (stop early; flag budget_hit)
  │     │     ├─ passes_quality_gate()                # fare_rate ≥ MIN_SUCCESS_RATE?
  │     │     ├─ routes.advance_batch()               # ONLY on clean exit, not on budget_hit
  │     │     └─ exit(EXIT_OK | EXIT_CANARY | EXIT_GATE | EXIT_LOCK | EXIT_OTHER)
  ├─ if exit == 0:
  │     ├─ git add donotdelete/data/
  │     ├─ git commit
  │     └─ git push origin main   (credential.helper from $GH_PAT in env)
  └─ trim cron-*.log older than 90 days
```

## Where state lives

| What | Where | Tracked? | Persistence |
|---|---|---|---|
| CSV dataset | `data/flights_YYYY_MM.csv` | ✅ via LFS | committed daily |
| Rotation counter | `data/.batch_state` | ❌ gitignored | per-VPS |
| Lock | `.lock` | ❌ gitignored | per-run, kernel-released |
| Logs (cron-*.log) | `logs/cron-*.log` | ❌ gitignored | 90-day retention |
| Logs (scraper.log) | `logs/scraper.log[.YYYY-MM-DD]` | ❌ gitignored | `log_retention_days` (30 default) |
| Secrets (`GH_PAT`) | `~/.scraper_secrets` (outside repo) | ❌ never | chmod 600 |
| Config | `config/scraper.yaml` | ✅ committed | tweak + commit |
| Code | `scraper/*.py` | ✅ committed | code reviewed |

## Failure modes & detection

```
fast-flights upstream breaks
    └─ canary.run() fails after CANARY_MAX_WAIT_S
       └─ exit code 2 → no commit, rotation untouched

Google starts rate-limiting (partial outage)
    └─ many (route, horizon) calls fail or empty
       └─ fare_rate < MIN_SUCCESS_RATE
       └─ exit code 3 → no commit, rotation untouched

Network blip on a single call
    └─ adapter retries 3× with exponential backoff + jitter
       └─ succeeds → continue
       └─ exhausts → that route counts as errored; loop continues

Cron fires while a manual run is in progress
    └─ lockfile.acquire() raises LockBusy immediately
       └─ exit code 4 → no commit

Pipeline crashes mid-batch (OOM, kill -9)
    └─ kernel releases the lock automatically
    └─ rows written so far are still consistent (fsync per row)
    └─ rotation counter NOT advanced (advance only on clean exit)
    └─ next cron retries the same batch

GH_PAT expired
    └─ git push fails 3× in cron_run.sh
       └─ exit code 7 → commit is local-only, will retry tomorrow
```
