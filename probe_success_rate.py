"""
Decisive diagnostic: after warm-up, what's the real per-scrape success rate from
this IP? Distinguishes "GitHub viable" (high rate post-warmup) from "GitHub
unusable, drips empties" (low rate even when warm) → pivot to GCP VM.
"""
import time
import urllib.request
from datetime import datetime, timedelta

import sources

ROUTES = [("BOM","DEL"),("DEL","BLR"),("BLR","MAA"),("MAA","CCU"),("CCU","HYD")]
DAYS = [7, 14]


def egress_ip():
    try:
        with urllib.request.urlopen("https://api.ipify.org", timeout=10) as r:
            return r.read().decode().strip()
    except Exception:
        return "unknown"


def main():
    print(f"🌐 Egress IP: {egress_ip()}")
    built = sources.build_sources(["fli", "fast-flights"])
    src0, dest0 = ROUTES[0]

    # Warm up (patient, up to 15 min).
    print("Warming up…")
    warm = False
    for i in range(30):
        date = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
        for s in built:
            try:
                r = s.search(src0, dest0, date)
                if r and any(f.price for f in r):
                    print(f"   warmed via [{s.name}] after {i+1} probe(s)")
                    warm = True
                    break
            except Exception:
                pass
        if warm:
            break
        time.sleep(30)

    if not warm:
        print("❌ Never warmed up in 15 min — this IP is effectively unusable.")
        return

    # Measure: run all ROUTES x DAYS once each, count fares vs empties per source.
    print("\nMeasuring per-scrape success across 10 scrapes…")
    stats = {s.name: {"fares": 0, "empty": 0, "err": 0} for s in built}
    first_success = {s.name: 0 for s in built}
    n = 0
    for src, dest in ROUTES:
        for days in DAYS:
            n += 1
            date = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
            for s in built:
                try:
                    r = s.search(src, dest, date)
                    priced = [f for f in (r or []) if f.price is not None and f.price >= 1000]
                    if priced:
                        stats[s.name]["fares"] += 1
                        first_success[s.name] += 1
                    else:
                        stats[s.name]["empty"] += 1
                except Exception:
                    stats[s.name]["err"] += 1
            time.sleep(5)

    print(f"\n=== Results over {n} scrapes per source ===")
    for name, st in stats.items():
        rate = st["fares"] / n * 100 if n else 0
        print(f"  [{name}] fares={st['fares']} empty={st['empty']} err={st['err']}  → {rate:.0f}% success")

    # Combined (multi-source) success: a scrape succeeds if ANY source had fares.
    print("\nVERDICT:")
    best = max((st["fares"] for st in stats.values()), default=0)
    if best / n >= 0.7:
        print(f"  ✅ GitHub IP is VIABLE post-warmup ({best}/{n} ≥ 70%). Keep GitHub.")
    elif best > 0:
        print(f"  ⚠️  Marginal ({best}/{n}). GitHub works but drips — consider GCP VM.")
    else:
        print(f"  ❌ Unusable even when warm. Pivot to GCP Mumbai VM.")


if __name__ == "__main__":
    main()
