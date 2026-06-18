"""Config loader — file overrides defaults, env overrides file."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from scraper import config


def test_load_defaults_when_no_yaml(tmp_path, monkeypatch):
    # No config/scraper.yaml in tmp_path.
    monkeypatch.delenv("SCRAPER_DELAY_MIN_SECONDS", raising=False)
    cfg = config.load(base_dir=tmp_path)
    assert cfg.cities["Mumbai"] == "BOM"
    assert cfg.days_out == [1, 3, 7, 14, 30, 60]
    assert cfg.min_plausible_price_inr == 1000


def test_yaml_overrides_defaults(tmp_path):
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "scraper.yaml").write_text(
        "delay_min_seconds: 5\n"
        "delay_max_seconds: 7\n"
        "min_plausible_price_inr: 500\n"
    )
    cfg = config.load(base_dir=tmp_path)
    assert cfg.delay_min_seconds == 5
    assert cfg.delay_max_seconds == 7
    assert cfg.min_plausible_price_inr == 500


def test_env_overrides_yaml(tmp_path, monkeypatch):
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "scraper.yaml").write_text("delay_min_seconds: 5\n")
    monkeypatch.setenv("SCRAPER_DELAY_MIN_SECONDS", "15")
    cfg = config.load(base_dir=tmp_path)
    assert cfg.delay_min_seconds == 15


def test_invalid_yaml_top_level_rejected(tmp_path):
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "scraper.yaml").write_text("- 1\n- 2\n")  # a list, not a mapping
    with pytest.raises(ValueError):
        config.load(base_dir=tmp_path)


def test_canary_route_validation(tmp_path):
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "scraper.yaml").write_text("canary_route: [BOM]\n")
    with pytest.raises(ValueError):
        config.load(base_dir=tmp_path)


def test_plausibility_band_validation(tmp_path):
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "scraper.yaml").write_text(
        "min_plausible_price_inr: 5000\n"
        "max_plausible_price_inr: 1000\n"      # bad — min > max
    )
    with pytest.raises(ValueError):
        config.load(base_dir=tmp_path)


def test_success_rate_in_range(tmp_path):
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "scraper.yaml").write_text("min_success_rate: 1.5\n")
    with pytest.raises(ValueError):
        config.load(base_dir=tmp_path)


def test_display_timezone_default_is_kolkata(tmp_path):
    cfg = config.load(base_dir=tmp_path)
    assert cfg.display_timezone == "Asia/Kolkata"
    # IST is UTC+5:30 = 19800 seconds.
    from datetime import datetime, timezone
    offset = cfg.display_tz.utcoffset(datetime(2026, 6, 18, tzinfo=timezone.utc))
    assert offset is not None and offset.total_seconds() == 19800


def test_resolve_timezone_falls_back_to_utc_on_bad_name():
    from datetime import timezone
    # A nonsense zone must never raise — it degrades to UTC.
    assert config.resolve_timezone("Not/AZone") is timezone.utc
    assert config.resolve_timezone("UTC") is timezone.utc
    assert config.resolve_timezone("") is timezone.utc
