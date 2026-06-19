"""
CLI entry point.

Usage:
    python -m scraper                  # full daily batch (cron mode)
    python -m scraper --smoke          # 1 route × 1 horizon — fast end-to-end check
    python -m scraper --canary-only    # just the startup canary
    python -m scraper --routes BOM:DEL,DEL:BOM   # ad-hoc subset
    python -m scraper --max-routes 5
    python -m scraper --max-horizons 2

Exit codes:
    0   success
    2   canary failed (sources broken / hard IP block)
    3   fare-rate gate tripped (partial outage / library rot mid-run)
    4   lock contention (another run is in progress)
    5   unexpected error
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from . import canary, lockfile, logger, pipeline, routes, state
from .config import Config, load

EXIT_OK = 0
EXIT_CANARY = 2
EXIT_GATE = 3
EXIT_LOCK = 4
EXIT_OTHER = 5


def _parse_routes(spec: str) -> list[tuple[str, str]]:
    """Parse a CLI route spec like ``BOM:DEL,DEL:BOM`` into a route list."""
    pairs: list[tuple[str, str]] = []
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if ":" not in chunk:
            raise argparse.ArgumentTypeError(f"bad route {chunk!r} (expected ORIGIN:DEST)")
        o, d = chunk.split(":", 1)
        o, d = o.strip().upper(), d.strip().upper()
        if not (o and d):
            raise argparse.ArgumentTypeError(f"bad route {chunk!r} (empty side)")
        pairs.append((o, d))
    if not pairs:
        raise argparse.ArgumentTypeError("no routes parsed")
    return pairs


def _parse_horizons(spec: str) -> list[int]:
    return [int(x) for x in spec.split(",") if x.strip()]


def _argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="scraper", description="Flight scraper (fast-flights, v4).")
    p.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to scraper.yaml. Defaults to <base_dir>/config/scraper.yaml.",
    )
    p.add_argument(
        "--base-dir",
        type=Path,
        default=Path.cwd(),
        help="donotdelete/ directory. Defaults to cwd.",
    )
    p.add_argument("--smoke", action="store_true",
                   help="Smoke test: 1 route × 1 horizon, no rotation advance.")
    p.add_argument("--canary-only", action="store_true",
                   help="Run only the startup canary. Exit 0 if healthy, 2 otherwise.")
    p.add_argument("--no-canary", action="store_true",
                   help="Skip the canary (debugging / replay).")
    p.add_argument("--no-advance", action="store_true",
                   help="Deprecated no-op: rotation is date-based and stateless, "
                        "so nothing is ever 'advanced'. Accepted for compatibility.")
    p.add_argument("--routes", type=_parse_routes, default=None,
                   help="Ad-hoc routes (BOM:DEL,DEL:BOM). Overrides rotation.")
    p.add_argument("--horizons", type=_parse_horizons, default=None,
                   help="Override days_out, comma-separated.")
    p.add_argument("--max-routes", type=int, default=0,
                   help="Cap routes to the first N (after rotation pick).")
    p.add_argument("--max-horizons", type=int, default=0,
                   help="Cap horizons to the first N.")
    p.add_argument("--route-slice", type=str, default=None, metavar="I/N",
                   help="Scrape only the I-th of N contiguous slices of today's "
                        "rotation batch (1-based, e.g. 3/8). Spreads a day's batch "
                        "across multiple cron fires to stay under the rate-limit. "
                        "Today's batch is fixed by the UTC date, so every slice "
                        "agrees on the batch and no slice is special.")
    return p


def _parse_route_slice(spec: str) -> tuple[int, int]:
    """Parse ``I/N`` (e.g. ``3/8``) into (slice_index, slice_count)."""
    try:
        i_str, n_str = spec.split("/", 1)
        i, n = int(i_str), int(n_str)
    except (ValueError, AttributeError):
        raise SystemExit(f"--route-slice must be I/N (e.g. 3/8), got {spec!r}")
    if n < 1 or not (1 <= i <= n):
        raise SystemExit(f"--route-slice I/N requires 1 ≤ I ≤ N and N ≥ 1, got {spec!r}")
    return i, n


def main(argv: list[str] | None = None) -> int:
    args = _argparser().parse_args(argv)

    try:
        cfg = load(config_path=args.config, base_dir=args.base_dir)
    except Exception as e:  # noqa: BLE001
        print(f"config error: {e}", file=sys.stderr)
        return EXIT_OTHER

    run_id = state.new_run_id()
    logger.setup(cfg.log_dir, level=cfg.log_level, run_id=run_id, retention_days=cfg.log_retention_days)
    log = logging.getLogger("cli")
    log.info("starting run %s (cwd=%s)", run_id, Path.cwd())

    # Smoke / canary-only short-circuits — no lock needed, no rotation touched.
    if args.canary_only:
        ok = canary.run(
            origin=cfg.canary_route[0],
            destination=cfg.canary_route[1],
            days_out=cfg.canary_days_out,
            max_wait_seconds=cfg.canary_max_wait_seconds,
            probe_interval_seconds=cfg.canary_probe_interval_seconds,
            api_timeout_seconds=cfg.api_timeout_seconds,
            per_probe_attempts=cfg.canary_attempts,
            backoff_base=cfg.backoff_base_seconds,
            backoff_max=cfg.backoff_max_seconds,
            backoff_jitter=cfg.backoff_jitter_seconds,
            cabin=cfg.cabin,
            adults=cfg.adults,
            currency=cfg.currency,
        )
        return EXIT_OK if ok else EXIT_CANARY

    # Acquire the cross-process lock — second daily run while one is in flight
    # exits 4 immediately rather than queueing or racing.
    try:
        lock_ctx = lockfile.acquire(cfg.lock_file)
    except lockfile.LockBusy as e:
        log.error("lock busy: %s", e)
        return EXIT_LOCK

    with lock_ctx:
        # Canary first (unless --no-canary).
        if not args.no_canary:
            ok = canary.run(
                origin=cfg.canary_route[0],
                destination=cfg.canary_route[1],
                days_out=cfg.canary_days_out,
                max_wait_seconds=cfg.canary_max_wait_seconds,
                probe_interval_seconds=cfg.canary_probe_interval_seconds,
                api_timeout_seconds=cfg.api_timeout_seconds,
                per_probe_attempts=cfg.canary_attempts,
                backoff_base=cfg.backoff_base_seconds,
                backoff_max=cfg.backoff_max_seconds,
                backoff_jitter=cfg.backoff_jitter_seconds,
                cabin=cfg.cabin,
                adults=cfg.adults,
                currency=cfg.currency,
            )
            if not ok:
                log.error("canary failed — aborting before scrape")
                return EXIT_CANARY

        # Resolve route + horizon set.
        routes_override = None
        horizons_override = None
        if args.smoke:
            batch = routes.current_batch(cfg.cities, cfg.batches, cfg.state_dir)
            routes_override = batch.routes[:1] or [cfg.canary_route]
            horizons_override = cfg.days_out[:1]
            log.info("SMOKE: 1 route × 1 horizon (no rotation advance)")
        elif args.route_slice is not None:
            sl_i, sl_n = _parse_route_slice(args.route_slice)
            batch = routes.current_batch(cfg.cities, cfg.batches, cfg.state_dir)
            routes_override = routes.batch_slice(batch.routes, sl_i, sl_n)
            log.info(
                "SLICE %d/%d of batch %d/%d (date-based rotation): %d routes",
                sl_i, sl_n, batch.index + 1, cfg.batches, len(routes_override),
            )
            if args.horizons is not None:
                horizons_override = args.horizons
            elif args.max_horizons and args.max_horizons > 0:
                horizons_override = cfg.days_out[:args.max_horizons]
        else:
            if args.routes is not None:
                routes_override = args.routes
            elif args.max_routes and args.max_routes > 0:
                batch = routes.current_batch(cfg.cities, cfg.batches, cfg.state_dir)
                routes_override = batch.routes[:args.max_routes]
            if args.horizons is not None:
                horizons_override = args.horizons
            elif args.max_horizons and args.max_horizons > 0:
                horizons_override = cfg.days_out[:args.max_horizons]

        # Run the scrape.
        try:
            summary, out_path = pipeline.run(
                cfg,
                run_id=run_id,
                routes_override=routes_override,
                days_out_override=horizons_override,
            )
        except Exception as e:  # noqa: BLE001 - last-ditch boundary so we don't crash silently
            log.exception("unexpected pipeline error: %s", e)
            return EXIT_OTHER

        # Quality gate — a PURE HEALTH SIGNAL now; it no longer controls
        # collection OR rotation. Rotation is date-based (see scraper.routes):
        # the past cannot affect which batch runs in the future, so there is
        # nothing to "advance" and nothing to withhold.
        #
        # commit_below_gate=True (default): a degraded run still commits the
        # valid rows it DID fetch — every written row already passed per-row
        # validation, so partial data is good data. The gate only decides the
        # EXIT CODE for monitoring: a below-gate run that fetched ZERO rows (or
        # commit_below_gate=False) returns EXIT_GATE so the healthcheck flags it;
        # otherwise we commit and return OK with a prominent WARNING.
        if not pipeline.passes_quality_gate(summary, cfg.min_success_rate):
            if cfg.commit_below_gate and summary.rows_written > 0:
                log.warning(
                    "FARE-RATE GATE: %.1f%% < %.1f%% — DEGRADED run, committing "
                    "%d valid rows already fetched (rotation is date-based, unaffected)",
                    summary.fare_rate * 100, cfg.min_success_rate * 100,
                    summary.rows_written,
                )
                # fall through — commit; rotation is stateless so nothing to do
            else:
                log.error(
                    "FARE-RATE GATE: %.1f%% < %.1f%% — %s",
                    summary.fare_rate * 100, cfg.min_success_rate * 100,
                    "0 rows fetched" if summary.rows_written == 0 else "commit_below_gate=False",
                )
                return EXIT_GATE

        if summary.budget_hit:
            log.warning("time budget hit — partial batch committed (date-based rotation unaffected)")

    log.info("run %s OK: wrote %d rows to %s", run_id, summary.rows_written, out_path)
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
