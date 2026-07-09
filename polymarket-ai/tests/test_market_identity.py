from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from phase0.forecast_runner import run_forecast, MarketIdentityMismatchError
from phase0.forecast_lock import lock_forecast
from phase0.manifest import ManifestRegistry, create_manifest, freeze_manifest
from phase0.providers.fixture import FixtureForecastProvider
from phase0.schemas import CleanForecastPackage, Forecast


class TestMarketIdentity:
    def test_package_must_match_requested_market(self):
        provider = FixtureForecastProvider("tests/fixtures/forecast_outputs.json")
        pkg = CleanForecastPackage(
            market_id="WRONG",
            question="Q",
            description="D",
            resolution_source="https://example.com",
            outcomes=["Yes", "No"],
            package_created_at=datetime(2025, 5, 1, tzinfo=timezone.utc),
        )
        with pytest.raises(MarketIdentityMismatchError):
            run_forecast(provider, "M001", pkg.model_dump())

    def test_forecast_must_match_requested_market(self):
        provider = FixtureForecastProvider("tests/fixtures/forecast_outputs.json")
        pkg = CleanForecastPackage(
            market_id="M001",
            question="Q",
            description="D",
            resolution_source="https://example.com",
            outcomes=["Yes", "No"],
            package_created_at=datetime(2025, 5, 1, tzinfo=timezone.utc),
        )
        fc = run_forecast(provider, "M001", pkg.model_dump())
        assert fc.market_id == "M001"

    def test_forecast_market_id_via_forecast_lock(self, tmp_path: Path):
        fc = Forecast(
            market_id="M001",
            forecast_cutoff=datetime(2025, 6, 1, tzinfo=timezone.utc),
            forecast_mode="CHEAP_BASELINE",
            p_yes=0.5,
            interval_50=[0.4, 0.6],
            interval_80=[0.3, 0.7],
        )
        # Write forecast artifact
        fc_dir = tmp_path / "P0-TEST" / "forecasts" / "M001"
        fc_dir.mkdir(parents=True, exist_ok=True)
        (fc_dir / "v1.json").write_text(fc.model_dump_json(indent=2), encoding="utf-8")
        lock = lock_forecast(
            experiments_root=str(tmp_path),
            experiment_id="P0-TEST",
            market_id="M001",
            package={"market_id": "M001"},
            forecast=fc,
            forecast_mode="CHEAP_BASELINE",
        )
        assert lock.market_id == "M001"

class TestManifestMarketValidation:
    def test_market_not_in_manifest(self, tmp_path: Path):
        manifest = create_manifest("P0-TEST", [{"market_id": "M001"}])
        out = freeze_manifest(manifest, tmp_path)
        registry = ManifestRegistry(out)
        registry.load()
        assert not registry.has_market("M003")

    def test_market_in_manifest_ok(self, tmp_path: Path):
        manifest = create_manifest("P0-TEST", [{"market_id": "M001"}])
        out = freeze_manifest(manifest, tmp_path)
        registry = ManifestRegistry(out)
        registry.load()
        assert registry.has_market("M001")

