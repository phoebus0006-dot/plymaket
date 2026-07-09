from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from phase0.forecast_lock import (
    find_latest_version,
    find_latest_file,
    lock_forecast,
    parse_version,
)
from phase0.schemas import Forecast, ForecastMode


def make_forecast(market_id: str = "M001") -> Forecast:
    return Forecast(
        market_id=market_id,
        forecast_cutoff=datetime(2025, 6, 1, tzinfo=timezone.utc),
        forecast_mode="CHEAP_BASELINE",
        p_yes=0.63,
        interval_50=[0.56, 0.70],
        interval_80=[0.44, 0.77],
    )


def _write_forecast(tmp_path: Path, experiment_id: str, market_id: str, fc: Forecast, version: int = 1) -> Path:
    d = tmp_path / experiment_id / "forecasts" / market_id
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"v{version}.json"
    p.write_text(fc.model_dump_json(indent=2), encoding="utf-8")
    return p


class TestParseVersion:
    def test_parse_simple(self):
        assert parse_version("v1.json") == 1

    def test_parse_double_digit(self):
        assert parse_version("v12.json") == 12

    def test_v9_before_v12(self):
        assert parse_version("v9.json") < parse_version("v12.json")

    def test_invalid_stem(self):
        assert parse_version("no_v.json") is None

    def test_parse_from_path_name(self):
        assert parse_version(Path("v1.json").name) == 1


class TestForecastLock:
    def test_lock_creates_v1(self, tmp_path: Path):
        fc = make_forecast()
        _write_forecast(tmp_path, "P0-TEST", "M001", fc)
        lock = lock_forecast(
            experiments_root=str(tmp_path),
            experiment_id="P0-TEST",
            market_id="M001",
            package={"market_id": "M001", "test": "data"},
            forecast=fc,
            forecast_mode=ForecastMode.CHEAP_BASELINE,
        )
        assert lock.forecast_version == 1
        assert lock.market_id == "M001"

    def test_lock_forecast_id_custom(self, tmp_path: Path):
        fc = make_forecast()
        _write_forecast(tmp_path, "P0-TEST", "M001", fc)
        lock = lock_forecast(
            experiments_root=str(tmp_path),
            experiment_id="P0-TEST",
            market_id="M001",
            package={"market_id": "M001", "test": "data"},
            forecast=fc,
            forecast_mode=ForecastMode.CHEAP_BASELINE,
        )
        assert lock.forecast_id == "M001_1"

    def test_lock_integrity(self, tmp_path: Path):
        fc = make_forecast()
        _write_forecast(tmp_path, "P0-TEST", "M001", fc)
        lock = lock_forecast(
            experiments_root=str(tmp_path),
            experiment_id="P0-TEST",
            market_id="M001",
            package={"market_id": "M001", "test": "data"},
            forecast=fc,
            forecast_mode=ForecastMode.CHEAP_BASELINE,
        )
        assert lock.market_id == "M001"
        assert lock.forecast_hash != ""

    def test_lock_tamper_detected(self, tmp_path: Path):
        fc = make_forecast()
        p = _write_forecast(tmp_path, "P0-TEST", "M001", fc)
        data = json.loads(p.read_text(encoding="utf-8"))
        data["p_yes"] = 0.99
        data["interval_50"] = [0.94, 0.99]
        data["interval_80"] = [0.85, 1.0]
        p.write_text(json.dumps(data), encoding="utf-8")

        fc_original = make_forecast()
        lock = lock_forecast(
            experiments_root=str(tmp_path),
            experiment_id="P0-TEST",
            market_id="M001",
            package={"market_id": "M001", "test": "data"},
            forecast=fc_original,
            forecast_mode=ForecastMode.CHEAP_BASELINE,
        )
        assert lock.forecast_hash != lock.forecast_artifact_hash

    def test_find_latest_version(self, tmp_path: Path):
        fc = make_forecast()
        for v in range(1, 6):
            _write_forecast(tmp_path, "P0-TEST", "VERSIONED", fc, version=v)
        assert find_latest_version(tmp_path / "P0-TEST" / "forecasts" / "VERSIONED") == 5

    def test_version_sort_v12_after_v9(self, tmp_path: Path):
        fc = make_forecast()
        for v in range(1, 13):
            _write_forecast(tmp_path, "P0-TEST", "VERSIONED", fc, version=v)
        assert find_latest_version(tmp_path / "P0-TEST" / "forecasts" / "VERSIONED") == 12

    def test_lock_rejects_contaminated_package(self, tmp_path: Path):
        fc = make_forecast()
        _write_forecast(tmp_path, "P0-TEST", "M001", fc)
        lock = lock_forecast(
            experiments_root=str(tmp_path),
            experiment_id="P0-TEST",
            market_id="M001",
            package={"market_id": "M001", "best_ask": 0.5},
            forecast=fc,
            forecast_mode=ForecastMode.CHEAP_BASELINE,
        )
        assert lock.package_hash != ""

    def test_find_latest_file(self, tmp_path: Path):
        fc = make_forecast()
        _write_forecast(tmp_path, "P0-TEST", "M001", fc, version=1)
        _write_forecast(tmp_path, "P0-TEST", "M001", fc, version=3)
        _write_forecast(tmp_path, "P0-TEST", "M001", fc, version=2)
        latest = find_latest_file(tmp_path / "P0-TEST" / "forecasts" / "M001")
        assert latest is not None
        assert latest.name == "v3.json"
