"""
Diagnostic: dump fli's full price distribution vs fast-flights, from whatever IP
this runs on. Answers: is fli corrupting ALL prices or just a few outlier rows?
"""
import time
from datetime import datetime, timedelta
import urllib.request

ROUTE = ("BOM", "DEL")
DAYS = 7


def egress_ip():
    try:
        with urllib.request.urlopen("https://api.ipify.org", timeout=10) as r:
            return r.read().decode().strip()
    except Exception:
        return "unknown"


def main():
    print(f"🌐 Egress IP: {egress_ip()}")
    date = (datetime.now() + timedelta(days=DAYS)).strftime("%Y-%m-%d")
    src, dest = ROUTE

    # Spy on fli's raw price blocks BEFORE our patch, to see what ₹69 really is.
    raw_blocks = []
    try:
        from fli.search import _decoders
        _orig = _decoders._parse_price_info
        if not getattr(_orig, "_spy", False):
            def _spy(row):
                pb = _decoders._get_price_block(row)
                try:
                    res = _orig(row)
                    raw_blocks.append((res[0], pb))
                    return res
                except Exception:
                    raw_blocks.append(("ERR", pb))
                    raise
            _spy._spy = True
            _decoders._parse_price_info = _spy
    except Exception as e:
        print(f"spy setup failed: {e!r}")

    import sources
    fli = sources.FliSource()
    ff = sources.FastFlightsSource()

    # Warm up first (foreign IPs need it).
    for i in range(12):
        try:
            r = fli.search(src, dest, date)
            if r and any(f.price for f in r):
                break
        except Exception:
            pass
        print(f"   warm-up {i+1} …")
        time.sleep(30)

    # fli full distribution
    try:
        r = fli.search(src, dest, date) or []
        prices = sorted(int(f.price) for f in r if f.price is not None)
        print(f"\n[fli] {len(r)} results, {len(prices)} priced")
        print(f"  lowest 10: {prices[:10]}")
        print(f"  highest 5: {prices[-5:]}")
        below1000 = [p for p in prices if p < 1000]
        print(f"  rows under ₹1000 (bogus): {len(below1000)} -> {below1000[:10]}")
        plausible = [p for p in prices if 1000 <= p <= 200000]
        if plausible:
            print(f"  plausible cheapest: ₹{min(plausible)}  median: ₹{plausible[len(plausible)//2]}")
    except Exception as e:
        print(f"[fli] ERROR {e!r}")

    # fast-flights for comparison
    try:
        r2 = ff.search(src, dest, date) or []
        p2 = sorted(int(f.price) for f in r2 if f.price is not None)
        print(f"\n[fast-flights] {len(r2)} results")
        print(f"  lowest 10: {p2[:10]}")
        print(f"  cheapest: ₹{min(p2)}  median: ₹{p2[len(p2)//2]}" if p2 else "  none")
    except Exception as e:
        print(f"[fast-flights] ERROR {e!r}")

    # Show the raw price blocks for the lowest-decoded rows — reveals what the
    # bogus ₹69 actually is in Google's structure.
    if raw_blocks:
        numeric = [(p, pb) for p, pb in raw_blocks if isinstance(p, (int, float))]
        numeric.sort(key=lambda x: x[0])
        print("\n🔬 Lowest-decoded rows (decoded_price, raw_price_block):")
        for p, pb in numeric[:6]:
            print(f"   decoded=₹{int(p)}  block={pb}")

    print("\nVERDICT: if fli's 'plausible cheapest' matches fast-flights, fli is")
    print("fine except for a few outlier rows the sanity filter already drops.")


if __name__ == "__main__":
    main()
