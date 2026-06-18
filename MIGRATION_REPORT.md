# Flight-Scraper Migration Report

> **Status:** Phase 1 deliverable — reverse engineering of the existing scraper,
> data audit, weaknesses found, and compatibility plan for the fast-flights
> replacement. Written before any code is removed or replaced.

This document is the source of truth for what the **old** system does. It is the
contract the new system must honour where compatibility is required, and the
checklist of weaknesses the new system must fix.

---

## 0. Repo context (scope boundary)

`goyaljai/PML-IITB-SEM1` hosts **two unrelated bodies of work** in one repo:

| Body of work | Top-level paths | In scope? |
|---|---|---|
| **IIT Bombay PML coursework** — IPL Player Detection dataset, feature extraction notebooks, labelling portal | `dataset/`, `edge_detection/`, `Individual_Feature_CSVs/`, `pipeline/`, `labelling-portal/`, `Dataset_*`, `Dataset_Features_HSV_RGB_Textures.csv`, `Dataset_Features_HSV_RGB_Textures_Edge.zip`, `README.md`, the existing `requirements.txt` | ❌ **Out of scope — do not delete or modify** |
| **Flight scraper** | `scraper.py`, `sources.py`, `fli_patch.py`, `probe_*.py`, `vm_run.sh`, `temp/`, `.github/workflows/` | ✅ In scope |

The course README at the repo root is for the IPL dataset, not the scraper. The
scraper's own docs live in `temp/README.md`.

The cleanup phase (Phase 2) MUST leave the coursework intact. The four empty
sentinel files at the repo root (`Added`, `Created`, `Updated`, `git`) appear
to be stray artefacts from an earlier git operation — flagged for removal in
Phase 2.

---

## 1. Existing system at a glance

```
                ┌──────────────────────────────────────┐
                │   .github/workflows/daily_scrape.yml │  cron 12:17 UTC
                │   (also: vm_run.sh on a GCP IN VM)   │  Docker python:3.11
                └─────────────────┬────────────────────┘
                                  │ pip install flights fast-flights
                                  ▼
                         ┌─────────────────┐
                         │   scraper.py    │  canary → batch → fare-rate gate
                         └────────┬────────┘
                                  │ uses
                                  ▼
                         ┌─────────────────┐
                         │   sources.py    │  fli → fast-flights → playwright
                         └────────┬────────┘
                                  │ writes
                                  ▼
                ┌──────────────────────────────────────┐
                │ temp/flights_YYYY_MM.csv             │  LFS-tracked
                │ temp/batch_state.txt   (rotation)    │
                │ temp/.fli_version      (pinned vers) │
                └──────────────────────────────────────┘
```

**Two parallel deploy paths exist today:**

1. **GitHub Actions** (`.github/workflows/daily_scrape.yml`) — runs daily at
   `17 12 * * *` (UTC), pip-installs pinned versions from `.fli_version`, runs
   `python scraper.py`, on failure tries auto-upgrade + canary recheck, opens
   GitHub issues on unrecovered failure. Uses an optional proxy via
   `secrets.PROXY_URL`.
2. **GCP Mumbai VM** (`vm_run.sh`) — Docker `python:3.11-slim` container, uses
   a `GH_PAT` from `~/.pml_env` (out of repo), commits and pushes data with
   retries. Designed because Google Flights is friendlier to Indian IPs.

The migration replaces **both** of these with a single cron pipeline on the
Hostinger VPS, using **only fast-flights** (latest, refreshed each run).

---

## 2. Routes being tracked (preserved by the migration)

### 2.1 Cities (15)

Defined in `scraper.py:71-77`:

| City | IATA |
|---|---|
| Mumbai | BOM |
| Delhi | DEL |
| Bengaluru | BLR |
| Hyderabad | HYD |
| Chennai | MAA |
| Kolkata | CCU |
| Pune | PNQ |
| Ahmedabad | AMD |
| Surat | STV |
| Visakhapatnam | VTZ |
| Jaipur | JAI |
| Kochi | COK |
| Chandigarh | IXC |
| Indore | IDR |
| Lucknow | LKO |

### 2.2 Routes (210 directed)

All ordered pairs (`itertools.permutations(codes, 2)`): **15 × 14 = 210 directed
city pairs**. Each route is treated independently (BOM→DEL and DEL→BOM are
separate routes).

### 2.3 Daily batching (3-day rotation)

Driven by `get_todays_routes()` in `scraper.py:147-178` with the persistent
counter in `temp/batch_state.txt`:

| Day | Batch | Routes covered |
|---|---|---|
| Day N   | 0 | routes 0–69    (70) |
| Day N+1 | 1 | routes 70–139  (70) |
| Day N+2 | 2 | routes 140–209 (70) |
| Day N+3 | 0 | routes 0–69    (70) |
| …       | … | …                  |

`batch_state.txt` currently reads **`14`**, i.e. tomorrow will be batch
`14 % 3 = 2` (routes 140–209).

> ⚠️ **Bug spotted (carry over to new design):** the counter is **bumped before
> the scrape runs** (line 175). A failed/crashed run still advances the rotation,
> leaving that batch un-scraped until the next cycle. **The new scraper must
> advance the counter only after a successful run.**

### 2.4 Booking horizons (6)

`DAYS_OUT = [1, 3, 7, 14, 30, 60]` — every batched route is queried at all six
horizons in the same run.

**Total scrapes/day:** `70 routes × 6 horizons = 420 calls`. Old design budgeted
75 min wall-clock for this. **The new design will deliberately spread these
across ≤ 2 hours** — see compatibility section.

---

## 3. Schema (29 columns, version 3)

Source of truth: `CSV_HEADERS` in `scraper.py:95-105` and `temp/README.md`.

| # | Column | Type | Business purpose / forecasting role |
|---|---|---|---|
| 1 | `Schema_Version` | int | Vintage tag — lets downstream tell rows produced under different schemas apart over a 1+ year collection. |
| 2 | `Scrape_Timestamp` | datetime | The booking moment (when this fare was observed). The X-axis of any time-series price model. |
| 3 | `Days_to_Departure` | int | Booking horizon. The single most predictive fare feature: "how far ahead are you booking". |
| 4 | `Departure_Date` | date | The actual travel date. |
| 5 | `Day_of_Week` | str | Departure day of week — captures Mon/Fri vs Tue/Wed pricing differences. |
| 6 | `Booking_Day_Of_Week` | str | The DOW of the booking action — captures "weekend bookers pay more" effects. |
| 7 | `Departure_Time` | str (12h) | Human-readable. |
| 8 | `Departure_ISO` | datetime | ISO 8601 for unambiguous parsing downstream. |
| 9 | `Departure_Hour` | int | Red-eye vs peak-time signal (often-strong fare driver). |
| 10 | `Arrival_Time` | str (12h) | Human-readable. |
| 11 | `Arrival_ISO` | datetime | ISO 8601 arrival. |
| 12 | `Is_Weekend_Departure` | 0/1 | Pre-derived weekend flag (Saturday/Sunday). |
| 13 | `Is_Overnight` | 0/1 | Arrival on a later calendar day — proxy for red-eye. |
| 14 | `Source_City` | str (IATA) | Origin. |
| 15 | `Destination_City` | str (IATA) | Destination. |
| 16 | `Airline` | str | Primary/marketing airline (carrier-loyalty pricing signal). |
| 17 | `Flight_Number` | str | First-leg flight number (or just airline code from fast-flights). |
| 18 | `Aircraft` | str | First-leg aircraft type — proxy for cabin/comfort tier. |
| 19 | `Total_Duration_Mins` | int | Itinerary length (negatively correlated with willingness to pay above some inflection). |
| 20 | `Number_of_Stops` | int | 0/1/2+ — strong fare driver. |
| 21 | `Layover_City` | str (IATA/city) | First layover. |
| 22 | `Layover_Duration_Mins` | int | First layover length. |
| 23 | `Self_Transfer` | 0/1 | Itinerary requires a self-transfer (only fli exposes this; fast-flights returns 0). |
| 24 | `CO2_Emissions_Kg` | int | Emissions per passenger in **kg** (libraries return grams; scraper /1000). |
| 25 | `CO2_Delta_Pct` | int | % above/below typical emissions for the route. |
| 26 | `Num_Results` | int | How many priced flights the search returned — proxy for route demand/supply thickness. |
| 27 | `Data_Source` | str | Which adapter produced the row (`fli`/`fast-flights`/`playwright`). Critical for distinguishing source-specific quirks downstream. |
| 28 | `Flight_Category` | str | `Best` / `Cheapest` / `Median` / `NoFlights`. |
| 29 | `Price_INR` | int | The **target** variable. Real INR fare (no discount factor). Empty for `NoFlights` rows. |

**Three-row-per-search shape:** every successful (route, horizon) emits up to
3 rows — `Best` (first result), `Cheapest` (min by price), `Median` (midpoint
of the sorted priced list, **only when its price differs from Cheapest**).
Routes with no fares emit a single `NoFlights` row.

---

## 4. Data audit — `temp/flights_2026_06.csv`

| Metric | Value |
|---|---|
| File size | 192 KB (plain CSV, **not** an LFS pointer — actual data) |
| Rows | 1,117 data rows (+ 1 header) |
| Scrape dates | 2026-06-17, 2026-06-18 |
| Unique routes seen | 89 (out of 210 — partial batch coverage in this snapshot) |
| All Schema_Version | 3 |
| Categories | Best 309 • Cheapest 309 • Median 267 • NoFlights 232 |
| Data sources used | fli 864 • fast-flights 21 • (blank, for NoFlights) 232 |
| Horizons covered | 1, 3, 7, 14, 30, 60 (all six) |

### 4.1 🚨 Critical data-quality finding

**~96% of priced rows in the existing CSV have bogus prices.**

| Category | Source | Implausible (< ₹1,000) | Plausible (≥ ₹1,000) |
|---|---|---:|---:|
| Best     | fli           | **295** | 7 |
| Cheapest | fli           | **295** | 7 |
| Median   | fli           | **258** | 2 |
| Best     | fast-flights  | 0   | 7 |
| Cheapest | fast-flights  | 0   | 7 |
| Median   | fast-flights  | 0   | 7 |

Of all rows tagged `fli`, **only ~16 out of 864 are usable**. fast-flights rows
are clean. This matches the documented "fli `₹69` parsing glitch on non-Indian
datacenter IPs" — but it's clearly the dominant failure mode in practice, not
an edge case. The `MIN_PLAUSIBLE_PRICE=1000` filter in `scraper.py` **did not
catch these rows**, which means either (a) the data was collected before the
filter shipped, or (b) the filter is not running on this path. Either way:

> **The new system cannot trust `fli`. It will use only `fast-flights` (per the
> explicit instruction) and will validate INR plausibility on every row before
> it's written, dropping any row that violates the band.**

### 4.2 Other observations

- **NoFlights rows have empty `Data_Source`.** Downstream queries that filter
  on `Data_Source` will exclude all NoFlights. New schema should populate it
  with the source that *attempted* the search (so the absence signal is
  attributable).
- **Median is occasionally skipped** (267 < 309), which is by design — only
  emitted when its price differs from Cheapest. Worth a comment in the new
  data dictionary to avoid surprise.
- **`Self_Transfer` is always 0 in fast-flights rows** (the library doesn't
  expose it). New schema will surface this as a known-null when the source
  doesn't provide the field, not a silent `0`.

---

## 5. Strengths to preserve

These are good ideas in the existing system. The replacement keeps them.

1. **Monthly file partitioning** (`flights_YYYY_MM.csv`) keeps any one CSV
   under a few MB even after a year of daily appends.
2. **Schema versioning** (`Schema_Version` column) lets future schema changes
   coexist with historical rows.
3. **Health gates** (canary at startup, fare-rate gate at end) prevent silently
   committing an empty/garbage dataset.
4. **NoFlights rows** as a first-class category — absence is a useful signal
   in itself for a forecasting model.
5. **Best/Cheapest/Median triple per search** — captures the price *distribution*
   from a single API call instead of just the min.
6. **Pre-derived signals** (booking DOW, departure hour, is-weekend, is-overnight)
   surface latent features cheaply.
7. **Git LFS for CSVs** (already configured in `.gitattributes`).
8. **15-city × 6-horizon × 3-day rotation** — solid coverage given API budget.

---

## 6. Weaknesses & risks (the new system must fix)

| # | Weakness | Impact | Fix in new system |
|---|---|---|---|
| 1 | `fli` produces bogus prices on non-Indian IPs and they leak past the filter (1080/1117 rows bogus). | Dataset largely unusable. | Drop `fli` entirely. Use only `fast-flights` (latest). Plausibility filter is mandatory pre-write. |
| 2 | Rotation counter `batch_state.txt` is bumped **before** the scrape runs. | A failed run skips a batch until the next 3-day cycle. | Advance counter only after a successful run completes (write a sentinel mid-run, commit on success). |
| 3 | No file lock — two cron invocations could overlap. | Corrupt CSV writes / duplicate rows. | `flock`-backed lock file in `donotdelete/.lock`. |
| 4 | Unstructured `print()` logs only, retained only by GitHub Actions UI. | Hard to debug failures, no long-term visibility. | Python `logging` + JSON/structlog to `donotdelete/logs/scraper-YYYY-MM-DD.log` with rotation. |
| 5 | No data validation before writing. | Bad rows enter the dataset and CSV stays corrupt forever (append-only). | Per-row validator (schema, types, INR bounds, ISO dates, non-empty route) — invalid rows are logged and **not written**. |
| 6 | No retry/backoff with jitter at the *route* level inside fast-flights calls. | Transient network errors abort that route. | Tenacity-style retry: 3 attempts, exponential backoff (2/4/8s) + jitter, on `RequestException`, timeout, empty response. |
| 7 | No timeout on the API call itself (relies on library defaults). | A hung call can stall the run. | Per-call timeout (env-configurable, default 30s). |
| 8 | No partial-failure recovery — if the run dies, the day's data is lost. | Multi-hour wasted work. | Write to a daily working file as you go; mark routes done in a sidecar; restart-safe. |
| 9 | Config scattered across env vars and hard-coded constants. | Operator changes need code edits. | Single `config/scraper.yaml` (cities, horizons, delays, plausibility band, retry policy, paths). |
| 10 | Empty sentinel files at repo root (`Added`, `Created`, `Updated`, `git`). | Repo noise. | Delete in Phase 2. |
| 11 | Two parallel deploy paths (GH Actions + VM script). | Maintenance burden, confusion about source of truth. | Single VPS cron path. Workflows removed entirely (Phase 2). |
| 12 | Credentials (`GH_PAT`) committed indirectly via `vm_run.sh`'s expected env file. | Operator can grep for token; risk of accidental commit. | New deployment expects credentials *only* in `~/.scraper_secrets` on the VPS (gitignored, never read into source). |

---

## 7. Compatibility considerations (what the new system MUST keep)

The new scraper must remain a drop-in successor for any downstream analysis the
user already has built or plans to build on the historical data.

1. **Same 15-city / 210-route universe** — preserve the cities/IATA mapping
   verbatim.
2. **Same 6 booking horizons** `[1, 3, 7, 14, 30, 60]`.
3. **Same 3-day batch rotation** with the persisted counter (fixed for issue
   #2 above).
4. **Same column set, in the same order, with the same names and semantics**
   for at least all 29 columns — so a year of historical rows still concatenates
   cleanly with a year of new rows under a single `pd.read_csv` call.
5. **`Schema_Version` field is preserved** — bumped to `4` to mark the new
   vintage (single-source fast-flights, stricter validation, advance-after-success
   rotation). Downstream can filter on `Schema_Version == 3` for old data,
   `Schema_Version == 4` going forward.
6. **`Data_Source` column kept** — will be `"fast-flights"` for every priced
   row, and the same for NoFlights (no longer blank).
7. **Monthly partitioning kept** — `data/flights_YYYY_MM.csv` (path moves under
   `donotdelete/data/`, see Phase 6).
8. **LFS tracking kept** — `*.csv filter=lfs` continues to apply.

> **Schema additions (additive only, won't break old readers):** a small set
> of new columns goes at the END of the row, so existing column-index-based
> readers continue to work. Defined fully in Phase 4.

### 7.1 User-mandated changes vs the old system

| Old | New | Why |
|---|---|---|
| `fli` primary, fast-flights fallback | **fast-flights only**, **latest version** | User instruction; data audit confirms fli unusable from non-IN IPs. |
| Pinned versions in `temp/.fli_version` | `pip install --upgrade fast-flights` before every cron run | User instruction. Latest, not pinned. |
| GitHub Actions (12:17 UTC) + VM | **VPS cron only** | User instruction (Phase 6). |
| 75-min budget, 8–18s delays | **~2-hour soft budget, longer delays** | User instruction: "slow slow (≤2hrs per day)". Spreads the call rate across the runner to look less bot-like and stay polite. |
| Per-route commits via workflow | **Single end-of-day commit** after the full batch finishes | User instruction. |
| Auto-open GitHub issue on failure | Local structured logs + a `donotdelete/logs/last_failure.txt` marker | No GH-token surface on the VPS. |

---

## 8. Migration plan (high-level — full detail per phase)

| Phase | Output |
|---|---|
| 2 | Remove `.github/workflows/`, empty sentinel files, `vm_run.sh`, `fli_patch.py`, `probe_*.py`, `sources.py`, `scraper.py`. Single commit. |
| 3 | New `donotdelete/scraper/` (config-driven, fast-flights-only, retries, lock, validation, structured logs). |
| 4 | Schema v4 with additive columns; `donotdelete/docs/SCHEMA.md`. |
| 5 | LFS already wired; verify and document recovery path. |
| 6 | `donotdelete/{scraper,data,logs,config,scripts,docs,tests}` populated. |
| 7 | Cron script (`scripts/cron_run.sh`) — pip-upgrade fast-flights, lock, run, commit on success. **User installs on VPS** (SSH password is off-limits to this assistant; see top of task brief). |
| 8 | Tests under `donotdelete/tests/`, executed locally, passing. |
| 9 | Failure-mode review with mitigations. |
| 10-11 | Final audit, commits as goyaljai (`goyaljai.y14@gmail.com`) on a clean branch, push. PAT push status reported. |

---

## 9. Independent review of this report

Adversarial self-check before continuing:

- ✅ **Are routes fully captured?** Cross-checked `CITIES` dict against
  `itertools.permutations(codes, 2)` — yes, 210 directed pairs. New scraper will
  generate the same set deterministically.
- ✅ **Are horizons fully captured?** `DAYS_OUT = [1, 3, 7, 14, 30, 60]` —
  verified against schema column 3 in the CSV.
- ✅ **Is the schema complete?** All 29 headers enumerated, types and
  semantics derived from `_flight_to_row()` + `temp/README.md`.
- ✅ **Is the data-quality claim defensible?** Counted directly via awk on the
  raw CSV: 1080 priced rows below ₹1,000, dominated by fli source. Numbers
  reproducible from the file in-repo.
- ⚠️ **Risk re Schema_Version bump:** downstream code that does
  `df = df[df.Schema_Version == 3]` to "get all production data" will silently
  start ignoring new rows. **Mitigation:** call this out prominently in
  `docs/SCHEMA.md` and the README, and recommend `Schema_Version >= 3`.
- ⚠️ **fast-flights API stability risk:** the user wants always-latest. A breaking
  upstream change can wedge the cron silently. **Mitigation:** canary at run
  start; if it fails after retries, the run exits non-zero and `last_failure.txt`
  is updated — no commit, no rotation advance. Stale-data alarm is a separate
  fast-follow if needed.
- ⚠️ **The `Self_Transfer` column will be a constant 0** under fast-flights-only.
  Could mislead a model. **Mitigation:** documented as known-null-from-source
  in `docs/SCHEMA.md`.

The report is consistent with the on-disk evidence. Ready to proceed to Phase 2.
