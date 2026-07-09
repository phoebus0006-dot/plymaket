from __future__ import annotations

import json
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

import pytest

from phase0.forecast_lock import lock_forecast
from phase0.manifest import create_manifest
from phase0.package_validator import validate_package
from phase0.price_reveal_service import PriceRevealService
from phase0.providers.fixture import FixtureMarketSnapshotProvider
from phase0.schemas import Forecast, ForecastMode
from phase0.state import EventStore, ExperimentStateManager


def make_forecast(market_id: str = "M001") -> Forecast:
    return Forecast(
        market_id=market_id,
        forecast_cutoff=datetime(2025, 6, 1, tzinfo=timezone.utc),
        forecast_mode="CHEAP_BASELINE",
        p_yes=0.63,
        interval_50=[0.56, 0.70],
        interval_80=[0.44, 0.77],
    )


def _setup_full_state(tmp_path: Path, market_id: str = "M001") -> tuple[ExperimentStateManager, str]:
    """Create a fully initialized experiment with a locked forecast.

    Returns (state_mgr, experiments_root).
    """
    experiments_root = str(tmp_path / "experiments")
    exp_id = "P0-TEST"

    manifest = create_manifest(
        exp_id,
        [{"market_id": market_id, "question": "Test market"}],
        selection_cutoff=datetime(2025, 6, 1, tzinfo=timezone.utc),
    )
    store = EventStore(Path(experiments_root) / exp_id / "events.jsonl")
    sm = ExperimentStateManager(store)
    sm.record_experiment_created(exp_id, manifest)
    sm.record_experiment_activated(exp_id)

    pkg = {
        "market_id": market_id,
        "question": "Test?",
        "description": "Desc",
        "resolution_source": "https://example.com",
        "outcomes": ["Yes", "No"],
        "evidence": [],
        "package_created_at": datetime.now(timezone.utc).isoformat(),
    }
    clean_pkg = validate_package(pkg)
    sm.record_market_initialized(exp_id, market_id, clean_pkg)

    # Write forecast artifact
    fc = make_forecast(market_id)
    fc_dir = Path(experiments_root) / exp_id / "forecasts" / market_id
    fc_dir.mkdir(parents=True, exist_ok=True)
    (fc_dir / "v1.json").write_text(fc.model_dump_json(indent=2), encoding="utf-8")

    # Write package artifact with package_hash for tamper detection
    pkg_no_hash = {k: v for k, v in pkg.items() if k != "package_hash"}
    pkg_hash_val = sha256(json.dumps(pkg_no_hash, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    pkg_with_hash = dict(pkg)
    pkg_with_hash["package_hash"] = pkg_hash_val
    pkg_path = Path(experiments_root) / exp_id / "packages" / f"{market_id}.json"
    pkg_path.parent.mkdir(parents=True, exist_ok=True)
    pkg_path.write_text(json.dumps(pkg_with_hash, default=str), encoding="utf-8")

    # Lock forecast
    lock_obj = lock_forecast(
        experiments_root=experiments_root,
        experiment_id=exp_id,
        market_id=market_id,
        package=pkg,
        forecast=fc,
        forecast_mode=ForecastMode.CHEAP_BASELINE,
    )
    lock_dir = Path(experiments_root) / exp_id / "locks" / market_id
    lock_dir.mkdir(parents=True, exist_ok=True)
    (lock_dir / "v1.json").write_text(lock_obj.model_dump_json(indent=2), encoding="utf-8")
    sm.record_forecast_locked(exp_id, market_id, lock_obj)

    return sm, experiments_root


class TestPriceRevealService:
    def test_reveal_without_state_fails(self, tmp_path: Path):
        store = EventStore(tmp_path / "events.jsonl")
        sm = ExperimentStateManager(store)
        experiments_root = str(tmp_path / "experiments")

        provider = FixtureMarketSnapshotProvider("tests/fixtures")
        service = PriceRevealService(
            state_mgr=sm,
            experiments_root=experiments_root,
            provider=provider,
        )
        with pytest.raises(RuntimeError):
            service.reveal("M001", "P0-TEST")

    def test_fake_empty_lock_blocks_reveal(self, tmp_path: Path):
        sm, experiments_root = _setup_full_state(tmp_path)
        provider = FixtureMarketSnapshotProvider("tests/fixtures")
        service = PriceRevealService(
            state_mgr=sm,
            experiments_root=experiments_root,
            provider=provider,
        )
        with pytest.raises(RuntimeError):
            service.reveal("NONEXISTENT", "P0-TEST")

    def test_state_not_locked_blocks_reveal(self, tmp_path: Path):
        experiments_root = str(tmp_path / "experiments")
        exp_id = "P0-TEST"
        manifest = create_manifest(
            exp_id,
            [{"market_id": "M001", "question": "Test?"}],
            selection_cutoff=datetime(2025, 6, 1, tzinfo=timezone.utc),
        )
        store = EventStore(Path(experiments_root) / exp_id / "events.jsonl")
        sm = ExperimentStateManager(store)
        sm.record_experiment_created(exp_id, manifest)
        sm.record_experiment_activated(exp_id)
        pkg = validate_package({
            "market_id": "M001",
            "question": "Test?",
            "description": "Desc",
            "resolution_source": "https://example.com",
            "outcomes": ["Yes", "No"],
            "evidence": [],
            "package_created_at": datetime.now(timezone.utc).isoformat(),
        })
        sm.record_market_initialized(exp_id, "M001", pkg)
        # Not locking — state is PACKAGE_READY

        provider = FixtureMarketSnapshotProvider("tests/fixtures")
        service = PriceRevealService(
            state_mgr=sm,
            experiments_root=experiments_root,
            provider=provider,
        )
        with pytest.raises(RuntimeError):
            service.reveal("M001", exp_id)

    def test_full_valid_reveal_succeeds(self, tmp_path: Path):
        sm, experiments_root = _setup_full_state(tmp_path)
        provider = FixtureMarketSnapshotProvider("tests/fixtures")
        service = PriceRevealService(
            state_mgr=sm,
            experiments_root=experiments_root,
            provider=provider,
        )
        result = service.reveal("M001", "P0-TEST")
        assert result is not None
        assert result.market_id == "M001"

    def test_missing_package_artifact_blocks_reveal(self, tmp_path: Path):
        sm, experiments_root = _setup_full_state(tmp_path)
        # Delete package artifact
        pkg_path = Path(experiments_root) / "P0-TEST" / "packages" / "M001.json"
        if pkg_path.exists():
            pkg_path.unlink()

        provider = FixtureMarketSnapshotProvider("tests/fixtures")
        service = PriceRevealService(
            state_mgr=sm,
            experiments_root=experiments_root,
            provider=provider,
        )
        with pytest.raises(FileNotFoundError):
            service.reveal("M001", "P0-TEST")

    def test_tampered_package_artifact_blocks_reveal(self, tmp_path: Path):
        sm, experiments_root = _setup_full_state(tmp_path)
        # Tamper package artifact
        pkg_path = Path(experiments_root) / "P0-TEST" / "packages" / "M001.json"
        data = json.loads(pkg_path.read_text(encoding="utf-8"))
        data["question"] = "Tampered question"
        pkg_path.write_text(json.dumps(data), encoding="utf-8")

        provider = FixtureMarketSnapshotProvider("tests/fixtures")
        service = PriceRevealService(
            state_mgr=sm,
            experiments_root=experiments_root,
            provider=provider,
        )
        with pytest.raises(RuntimeError):
            service.reveal("M001", "P0-TEST")

    def test_package_market_mismatch_blocks_reveal(self, tmp_path: Path):
        sm, experiments_root = _setup_full_state(tmp_path)
        # Overwrite package with wrong market_id
        pkg_path = Path(experiments_root) / "P0-TEST" / "packages" / "M001.json"
        data = json.loads(pkg_path.read_text(encoding="utf-8"))
        data["market_id"] = "WRONG"
        pkg_path.write_text(json.dumps(data, default=str), encoding="utf-8")

        provider = FixtureMarketSnapshotProvider("tests/fixtures")
        service = PriceRevealService(
            state_mgr=sm,
            experiments_root=experiments_root,
            provider=provider,
        )
        with pytest.raises(RuntimeError):
            service.reveal("M001", "P0-TEST")

    def test_provider_failure_keeps_state_forecast_locked(self, tmp_path: Path):
        sm, experiments_root = _setup_full_state(tmp_path)

        class CrashProvider:
            def get_snapshot(self, market_id):
                raise RuntimeError("provider crash")

        service = PriceRevealService(
            state_mgr=sm,
            experiments_root=experiments_root,
            provider=CrashProvider(),
        )
        with pytest.raises(RuntimeError):
            service.reveal("M001", "P0-TEST")
        assert sm.market_status("M001").value == "FORECAST_LOCKED"

    def test_missing_forecast_artifact_blocks_lock(self, tmp_path: Path):
        """The lock_forecast function itself verifies the forecast artifact exists."""
        fc = make_forecast("M001")
        # Don't write forecast artifact
        with pytest.raises(FileNotFoundError):
            lock_forecast(
                experiments_root=str(tmp_path),
                experiment_id="P0-TEST",
                market_id="M001",
                package={"market_id": "M001", "test": "data"},
                forecast=fc,
                forecast_mode=ForecastMode.CHEAP_BASELINE,
            )
