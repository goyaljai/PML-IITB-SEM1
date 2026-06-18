"""CLI argument parsing — separate from main() so we don't need a live API."""

from __future__ import annotations

import pytest

from scraper.cli import _parse_horizons, _parse_routes


def test_parse_routes_basic():
    assert _parse_routes("BOM:DEL") == [("BOM", "DEL")]
    assert _parse_routes("BOM:DEL,DEL:BOM") == [("BOM", "DEL"), ("DEL", "BOM")]


def test_parse_routes_strips_and_uppercases():
    assert _parse_routes(" bom : del , del : bom ") == [("BOM", "DEL"), ("DEL", "BOM")]


def test_parse_routes_rejects_empty():
    with pytest.raises(Exception):
        _parse_routes("")
    with pytest.raises(Exception):
        _parse_routes(",,")


def test_parse_routes_rejects_no_colon():
    with pytest.raises(Exception):
        _parse_routes("BOM-DEL")


def test_parse_routes_rejects_empty_side():
    with pytest.raises(Exception):
        _parse_routes("BOM:")
    with pytest.raises(Exception):
        _parse_routes(":DEL")


def test_parse_horizons():
    assert _parse_horizons("1,3,7") == [1, 3, 7]
    assert _parse_horizons("60") == [60]
