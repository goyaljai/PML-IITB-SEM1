"""
Diagnostic probe: is the flight-data failure an IP block or rate-limiting?

Runs the canary route several times with increasing spacing and reports, per
attempt, whether each source returned data. Also prints the egress IP so we can
see which network we're calling from.

Interpretation:
  - ALL attempts empty, even the first, well-spaced ones  -> hard IP/ASN block.
  - First attempts fail but later (more-spaced) ones succeed -> rate-limiting
    (delays would help).
  - Works immediately -> not blocked here at all.
"""

import os
import time
import urllib.request
from datetime import datetime, timedelta

import sources

ROUTE = ("BOM", "DEL")
DAYS_OUT = 7
# Increasing spacing between rounds (seconds). If a later, well-spaced round
# starts succeeding, that's the rate-limit signature.
SPACING = [0, 30, 60, 120, 60, 60]

# Indian-IP ground-truth cheapest fares (collected locally from an Indian IP) for
# these exact routes/dates, so the probe can measure foreign-IP price inflation.
# Format: (src, dest, days_out) -> cheapest INR seen from an Indian IP.
INDIAN_REFERENCE = {
    ("BOM", "DEL", 7): 6508,
    ("DEL", "BLR", 7): 8570,
    ("MAA", "CCU", 7): 5863,
}
EXTRA_ROUTES = [("BOM", "DEL", 7), ("DEL", "BLR", 7), ("MAA", "CCU", 7)]


def egress_ip():
    for url in ("https://api.ipify.org", "https://ifconfig.me/ip"):
        try:
            with urllib.request.urlopen(url, timeout=10) as r:
                return r.read().decode().strip()
        except Exception:
            continue
    return "unknown"


def main():
    print(f"🌐 Egress IP: {egress_ip()}")
    date = (datetime.now() + timedelta(days=DAYS_OUT)).strftime("%Y-%m-%d")
    src, dest = ROUTE
    built = sources.build_sources()
    print(f"Sources: {', '.join(s.name for s in built) or 'NONE'}")
    print(f"Probing {src}->{dest} on {date}, {len(SPACING)} rounds\n")

    any_success = False
    for i, wait in enumerate(SPACING, 1):
        if wait:
            print(f"   …waiting {wait}s before round {i}")
            time.sleep(wait)
        print(f"[Round {i}] (spacing {wait}s)")
        for s in built:
            try:
                res = s.search(src, dest, date)
                n = len(res) if res else 0
                priced = [f for f in (res or []) if f.price is not None]
                if priced:
                    any_success = True
                    print(f"   [{s.name}] ✅ {n} results, cheapest ₹{int(min(f.price for f in priced))}")
                else:
                    print(f"   [{s.name}] ⚪ {n} results (no fares)")
            except Exception as e:  # noqa: BLE001
                print(f"   [{s.name}] ❌ {type(e).__name__}: {str(e)[:120]}")
        print()

    print("=" * 50)
    if any_success:
        print("✅ At least one attempt succeeded — NOT a hard block. "
              "Delays/retries (or this network) work.")
    else:
        print("❌ Every attempt failed across all sources and spacings — "
              "this looks like a HARD IP/ASN block, not rate-limiting. "
              "Delays won't help; need a different egress IP (proxy or VM).")

    # ── Price-inflation check vs Indian-IP ground truth ──────────────────────
    # Once warm, compare this (foreign) IP's cheapest fares to the Indian-IP
    # reference to measure the inflation %, so we can correct it downstream.
    print("\n" + "=" * 50)
    print("💱 Price inflation check (foreign IP vs Indian-IP reference)")
    fli = next((s for s in built if s.name == "fli"), None)
    if fli is None:
        print("   (fli source unavailable — skipping)")
        return
    for src_, dest_, days_ in EXTRA_ROUTES:
        date_ = (datetime.now() + timedelta(days=days_)).strftime("%Y-%m-%d")
        try:
            res = fli.search(src_, dest_, date_)
            priced = [f.price for f in (res or []) if f.price is not None]
            if not priced:
                print(f"   {src_}->{dest_} +{days_}d: no fares")
                continue
            cheapest = int(min(priced))
            ref = INDIAN_REFERENCE.get((src_, dest_, days_))
            if ref:
                infl = (cheapest - ref) / ref * 100
                print(f"   {src_}->{dest_} +{days_}d: foreign ₹{cheapest} vs "
                      f"Indian ₹{ref}  →  {infl:+.1f}% inflation")
            else:
                print(f"   {src_}->{dest_} +{days_}d: foreign ₹{cheapest} "
                      f"(no Indian reference)")
        except Exception as e:  # noqa: BLE001
            print(f"   {src_}->{dest_} +{days_}d: {type(e).__name__}: {str(e)[:80]}")


if __name__ == "__main__":
    main()
