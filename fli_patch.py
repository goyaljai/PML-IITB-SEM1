"""
Runtime patch for the `fli` library — applied on top of whatever (latest)
version is installed, so we keep upstream's protocol fixes AND our correction.

Bug addressed: from some IPs (notably non-Indian datacenter IPs like GitHub
Actions runners), fli's price decoder occasionally returns an implausible
cheapest fare (e.g. ₹69) for a row, while the rest of the result set is correct.
Root cause is in `_parse_price_info` reading `head[-1]` from the price block,
which on certain response shapes is not the total fare.

Approach (monkeypatch, not a fork): we wrap fli's `_parse_price_info` so that
when it returns an implausible price we raise `ValueError`. fli's own row loop
(`flights.py`: `except (AttributeError, KeyError, ValueError, TypeError)`)
already treats a `ValueError` from price parsing as "skip this row" — exactly
how it handles malformed sponsor rows. So the bad row is dropped at the source
and every other (correct) row is kept. No fork, no vendored copy: we always
`pip install` the latest fli and layer this patch at import time.

Usage: `import fli_patch; fli_patch.apply()` before any fli search. Idempotent
and safe — if fli's internals change so the patch target is gone, it logs and
no-ops rather than crashing (the scraper's own sanity filter still backstops).
"""

from __future__ import annotations

import os

# Plausible Indian-domestic economy fare bounds (INR). Kept in sync with the
# scraper's own filter; overridable via the same env vars.
MIN_PLAUSIBLE_PRICE = float(os.environ.get("MIN_PLAUSIBLE_PRICE", "1000"))
MAX_PLAUSIBLE_PRICE = float(os.environ.get("MAX_PLAUSIBLE_PRICE", "200000"))

_applied = False


def apply():
    """Patch fli's price decoder in place. Idempotent; returns True if applied."""
    global _applied
    if _applied:
        return True
    try:
        from fli.search import _decoders
    except Exception as e:  # noqa: BLE001 - fli not importable; nothing to patch
        print(f"[fli_patch] fli not importable, skipping patch: {e!r}")
        return False

    original = getattr(_decoders, "_parse_price_info", None)
    if original is None or getattr(original, "_pml_patched", False):
        _applied = original is not None
        return _applied

    def _patched_parse_price_info(row):
        price, currency = original(row)
        # Only reject clearly-bogus *present* prices. A genuine None (Google's
        # "no shopping-list price") is left untouched — fli handles it normally.
        if price is not None and not (MIN_PLAUSIBLE_PRICE <= price <= MAX_PLAUSIBLE_PRICE):
            raise ValueError(
                f"implausible price {price!r} outside "
                f"[{MIN_PLAUSIBLE_PRICE}, {MAX_PLAUSIBLE_PRICE}] — skip row (PML patch)"
            )
        return price, currency

    _patched_parse_price_info._pml_patched = True  # type: ignore[attr-defined]
    _decoders._parse_price_info = _patched_parse_price_info
    _applied = True
    print(f"[fli_patch] applied price-sanity patch to fli "
          f"(bounds ₹{int(MIN_PLAUSIBLE_PRICE)}–₹{int(MAX_PLAUSIBLE_PRICE)})")
    return True
