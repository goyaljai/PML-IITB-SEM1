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
SPACING = [0, 30, 60, 120]


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


if __name__ == "__main__":
    main()
