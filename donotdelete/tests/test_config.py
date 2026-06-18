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
