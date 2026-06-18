# Production-readiness audit

> Phase 9 deliverable. Walks every failure mode I could think of and shows
> where in the system that mode is detected, contained, and recovered from.
> The target horizon is **unattended operation for ≥ 12 months**.

## Audit format

For each failure mode:
* **Symptom** — what an operator would observe.
* **Impact** — what gets broken if nothing intervenes.
* **Detection** — what catches it.
* **Containment** — what stops it from corrupting prior data.
* **Recovery** — what brings the system back to "green" without human action
  (where possible) and the manual procedure if needed.

## 1. fast-flights upstream protocol change

| | |
|---|---|
| Symptom | Every fast-flights call returns empty or errors with the same import/parse failure across all routes. |
| Impact | If the bug is decoder-side, the library can silently return wrong values — exactly the v3 fli ₹69 disaster. |
| Detection | **Canary** at run start: a known-busy route (BOM→DEL +7d) probes for up to 15 min. Empty across the whole window → exit 2. **Validator** at write time: anything outside the INR plausibility band is dropped (defence in depth for silent-corruption decoder bugs). |
| Containment | No rows written, no rotation advance, no commit. Yesterday's data remains the latest. |
| Recovery | The next cron `pip install --upgrade fast-flights` may pick up an upstream fix — recovery is automatic. If upstream is broken for days, the operator pins a known-good version manually with `pip install fast-flights==X.Y.Z` inside the venv and disables the auto-upgrade line until upstream returns. |

## 2. Hard IP block / sustained rate-limit

| | |
|---|---|
| Symptom | First few requests succeed; later ones return empty or 429-equivalent. |
| Detection | **Fare-rate gate** at run end: if < 60% of (route, horizon) calls returned a priced row, exit 3. Per-call **retries** with exponential backoff absorb transient throttles; the gate catches the sustained case. |
| Containment | Same as #1 — no commit, no rotation advance. |
| Recovery | Wait 24 h; many rate-limits self-clear. If sustained, switch to a residential proxy via fast-flights' `proxy=` parameter (configurable in `config/scraper.yaml` once we wire it through, see "Known gaps" below) or move the VPS to a different ASN. |

## 3. Single transient network blip

| | |
|---|---|
| Symptom | One request fails with a connection reset / DNS timeout. |
| Detection | The adapter sees an exception. |
| Containment | **Per-call retries** (default 3) with 2/4/8 s backoff + ≤ 1.5 s jitter. The whole route+horizon is retried, the rest of the run continues. |
| Recovery | Automatic. |

## 4. Hung API call (slow-loris)

| | |
|---|---|
| Symptom | A single fast-flights call hangs indefinitely. |
| Impact | If unbounded, one call could stall the whole 2-h budget. |
| Detection | **SIGALRM-based per-call timeout** in `adapter._call_timeout` (default 30 s). On expiry raises `APITimeout`, which the retry loop treats as a transient error. |
| Recovery | Automatic — the call is retried up to `max_attempts`. After exhaustion the route is counted as errored and the loop continues. |

## 5. Process killed mid-batch (SIGKILL, OOM, VPS reboot)

| | |
|---|---|
| Symptom | The cron run never reaches the "scraper end" log line. |
| Detection | The kernel releases the `fcntl.flock` advisory lock automatically when the file descriptor closes (process death is one such close). The lock breadcrumb in `.lock` may be stale, but the OS-level lock is gone. |
| Containment | **Per-row fsync** in the writer means every row that hit the CSV is durable; no half-line ever exists on disk. **Rotation counter advances only on clean exit**, so a crash leaves the counter pointing at today's batch — tomorrow's cron retries the same batch. |
| Recovery | Next scheduled cron run picks up. If the crash happened after some rows were written, those rows remain (with the dead run's `Run_Id`); downstream can identify them by Run_Id and decide whether to keep them. |

## 6. Two cron firings overlap

| | |
|---|---|
| Symptom | An ad-hoc manual run is in progress when the scheduled cron fires. |
| Detection | `lockfile.acquire()` returns `LockBusy` immediately (non-blocking `LOCK_EX|LOCK_NB`). |
| Containment | The losing run exits with code 4 before touching the data dir or rotation counter. |
| Recovery | Nothing to do — the holding run finishes normally. |

## 7. Disk full mid-write

| | |
|---|---|
| Symptom | A CSV row write fails with `ENOSPC`. |
| Detection | `cron_run.sh` **disk guard** at the top of every run refuses to start when free space is below `DISK_MIN_GB` (default 2 GB, overridable via env). Inside a running scrape, `os.write`/`os.fsync` raises `OSError(ENOSPC)`. |
| Containment | If the disk fills mid-row, the row's write/fsync raises before append completes — the file's last line is well-formed because we open in append mode and write the full row in one `csv.writerow` call followed by `flush+fsync`. **Any prior rows are durable.** |
| Recovery | Operator frees disk (`OPERATIONS.md` has the prune commands), then runs `donotdelete/scripts/cron_run.sh` manually to retry the day. |

## 8. CSV corruption (last line truncated / extra bytes)

| | |
|---|---|
| Symptom | `pd.read_csv` raises a parse error. |
| Detection | Manual — periodic `wc -l` and a `pd.read_csv` smoke. |
| Containment | The append-only model + fsync-per-row + write-row-as-atomic-csv-write means this should be impossible to produce in normal operation. Could happen from disk corruption or out-of-band edits. |
| Recovery | `git checkout HEAD donotdelete/data/flights_YYYY_MM.csv` to restore the last known-good version. Resume scraping. |

## 9. Bad config edit

| | |
|---|---|
| Symptom | `scraper.yaml` has invalid values (e.g. `max_attempts: 0`). |
| Detection | `config.load()` validates bounds at start-of-run: positive attempt count, ordered plausibility band, success-rate in [0, 1], two-element canary route. |
| Containment | The process exits 5 BEFORE the lock is acquired — no state touched. |
| Recovery | Fix the YAML, run again. |

## 10. Code bug / unhandled exception

| | |
|---|---|
| Symptom | A new release introduces a bug that crashes the pipeline. |
| Detection | The CLI's top-level boundary catches every exception that escapes `pipeline.run()` and exits with code 5 plus a full stack trace in the structured log. |
| Containment | Same as #5 — durable prefix on disk, no rotation advance. |
| Recovery | Roll back: `git reset --hard <good-sha>`; next cron uses the rolled-back code. |

## 11. GH_PAT expired or revoked

| | |
|---|---|
| Symptom | The local commit succeeds, but `git push` returns 401/403. |
| Detection | `cron_run.sh` retries the push 3× with a `git rebase origin/main` between attempts; if all three fail the script exits 7. |
| Containment | The commit is local-only — the data is durable on the VPS even if the remote can't receive it. |
| Recovery | Edit `~/.scraper_secrets`, set a fresh PAT. The next cron will commit its own day's data on top of the unpushed commit, then push both together. |

## 12. LFS quota exceeded

| | |
|---|---|
| Symptom | `git push` succeeds for normal objects but fails the LFS upload step. |
| Detection | Same as #11. |
| Recovery | Upgrade GitHub LFS data pack, OR switch to a self-hosted LFS server (`docs/LFS_RECOVERY.md`). |

## 13. VPS clock skew

| | |
|---|---|
| Symptom | `Scrape_Timestamp` doesn't match wall clock. |
| Detection | Visible in healthcheck (freshness section) only if the skew is several hours. |
| Containment | The Run_Id is also derived from the system clock, so the per-row stamp and the run identifier stay consistent within one run. Downstream cleanly groups rows by Run_Id even when wall time is wrong. |
| Recovery | `timedatectl set-ntp true` on the VPS; this is the operator's setup responsibility. Out of scope for the scraper. |

## 14. Long-term log growth

| | |
|---|---|
| Symptom | logs/ grows to multi-GB. |
| Detection | `healthcheck.sh` runs `df -h` and reports. |
| Containment | `scraper.log` is rotated daily with `log_retention_days` (default 30) backups. `cron-*.log` files are pruned after 90 days by `cron_run.sh`. **Cap: ~30 daily `scraper.log.YYYY-MM-DD` + ~90 per-run `cron-*.log` ≈ < 150 MB total.** |
| Recovery | Manual prune (see OPERATIONS.md "Disk-pressure guard"). |

## 15. Repository drift (someone pushed to main from elsewhere)

| | |
|---|---|
| Symptom | The VPS local working tree has not seen a remote commit pushed by another machine. |
| Detection | `git push` fails non-fast-forward. |
| Containment | `cron_run.sh` does `git fetch && git rebase origin/main` between push retries. Gitignored runtime files (logs, lock, batch_state) survive the rebase. |
| Recovery | Automatic via retry loop, unless there's a true merge conflict — in which case exit 7 fires and the operator resolves it manually. |

## 16. `.batch_state` corruption

| | |
|---|---|
| Symptom | The file contains non-integer content. |
| Detection | `routes.current_batch()` catches `ValueError` and falls back to `0`. |
| Containment | Treated as "start of the rotation" — at worst we re-scrape a few routes. |
| Recovery | Automatic — next clean run writes a fresh integer via `advance_batch()` which uses atomic rename. |

## Known gaps (acceptable, but worth tracking)

These are conscious choices to keep the system small. None of them is a
"production blocker," but documenting them lets future-us know what's optional
to add when the time comes.

| Gap | Why we accept it | When to revisit |
|---|---|---|
| **No proxy support wired through.** fast-flights accepts a `proxy=` kwarg; we never thread one through `adapter.search_flights`. | The Hostinger VPS is in India; an Indian IP is exactly what fast-flights wants. | If the VPS moves to a foreign region or the IP gets persistently rate-limited (see #2). |
| **No multi-VPS coordination.** Two VPSes would each advance their own `.batch_state` (gitignored) and could push conflicting data within the same monthly CSV. | The brief is for one VPS. | If you ever need redundancy, use a single VPS with a hot spare that ONLY runs when the primary misses a day. |
| **No alerting beyond logs.** A failed run is visible in the local log; nothing pages the operator. | Cron's MAILTO works if SMTP is set up on the VPS, and `healthcheck.sh` is the 60-second daily check. | If you want phone-based pages, point cron's MAILTO at a notification gateway. |
| **No automated dataset backups.** Recovery from CSV corruption relies on `git checkout HEAD`. | LFS + git history IS the backup. | If you want an off-GitHub backup, `donotdelete/data/` is the only directory you need to rsync somewhere on a weekly cron. |
| **No `--dry-run` mode.** | `--smoke` is close enough (1 route × 1 horizon, validates the whole code path including writes). | If you want a true no-write dry-run, the writer is the place to add it. |
| **Self_Transfer always `0` and Flight_Number always empty.** | fast-flights does not expose either field; we documented this as known-null-from-source. | If fast-flights exposes them later, update `adapter._normalize`. |
| **Scrape_Timestamp is local time** (no offset). | v3 compatibility. The Run_Id (UTC) disambiguates. | If you ever want a timezone-aware column, add it as col 34+. |

## Verification

* Unit + integration tests: `pytest donotdelete/tests/ --timeout=30` — 79 passing.
* Live API smoke: `bash donotdelete/scripts/manual_run.sh --smoke` —
  confirmed end-to-end on 2026-06-18 (3 rows of real AMD→BLR fares).
* LFS round-trip: `bash donotdelete/tests/test_lfs_smoke.sh` — passing.
