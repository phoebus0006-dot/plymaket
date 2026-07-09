from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from phase0.forecast_lock import lock_forecast
from phase0.manifest import create_manifest
from phase0.package_validator import validate_package
from phase0.temporal import check_evidence_temporal_integrity
from phase0.providers.fixture import FixtureForecastProvider, FixtureMarketSnapshotProvider
from phase0.forecast_runner import run_forecast
from phase0.price_reveal_service import PriceRevealService
from phase0.evaluate import evaluate_experiment
from phase0.schemas import ForecastMode, Resolution, ResolutionOutcome
from phase0.state import EventStore, ExperimentStateManager, ExperimentStatus, MarketStatus


class TestEndToEnd:
    def test_full_pipeline_single_market(self, tmp_path: Path):
        experiments_root = str(tmp_path / "experiments")
        exp_id = "P0-E2E"

        manifest = create_manifest(
            exp_id,
            [{"market_id": "M001", "question": "Test market"}],
            selection_cutoff=datetime(2025, 6, 1, tzinfo=timezone.utc),
        )

        store = EventStore(Path(experiments_root) / exp_id / "events.jsonl")
        sm = ExperimentStateManager(store)
        sm.record_experiment_created(exp_id, manifest)
        sm.record_experiment_activated(exp_id)

        pkg = {
            "market_id": "M001",
            "question": "Test?",
            "description": "Desc",
            "resolution_source": "https://example.com",
            "outcomes": ["Yes", "No"],
            "evidence": [{"published_at": "2025-05-01T00:00:00+00:00", "source_url": "https://example.com/news"}],
            "package_created_at": datetime.now(timezone.utc).isoformat(),
        }
        clean_pkg = validate_package(pkg)
        sm.record_market_initialized(exp_id, "M001", clean_pkg)

        check_evidence_temporal_integrity(pkg["evidence"], manifest.selection_cutoff)

        provider = FixtureForecastProvider("tests/fixtures/forecast_outputs.json")
        fc = run_forecast(provider, "M001", clean_pkg.model_dump())

        # Write forecast artifact
        fc_dir = Path(experiments_root) / exp_id / "forecasts" / "M001"
        fc_dir.mkdir(parents=True, exist_ok=True)
        (fc_dir / "v1.json").write_text(fc.model_dump_json(indent=2), encoding="utf-8")

        # Write package artifact for PriceRevealService
        pkg_artifact_path = Path(experiments_root) / exp_id / "packages" / "M001.json"
        pkg_artifact_path.parent.mkdir(parents=True, exist_ok=True)
        pkg_artifact_path.write_text(json.dumps(pkg, default=str), encoding="utf-8")

        # Lock forecast
        lock_obj = lock_forecast(
            experiments_root=experiments_root,
            experiment_id=exp_id,
            market_id="M001",
            package=pkg,
            forecast=fc,
            forecast_mode=ForecastMode.CHEAP_BASELINE,
        )
        lock_dir = Path(experiments_root) / exp_id / "locks" / "M001"
        lock_dir.mkdir(parents=True, exist_ok=True)
        (lock_dir / "v1.json").write_text(lock_obj.model_dump_json(indent=2), encoding="utf-8")
        sm.record_forecast_locked(exp_id, "M001", lock_obj)

        # Reveal price
        snap_provider = FixtureMarketSnapshotProvider("tests/fixtures")
        reveal_svc = PriceRevealService(
            state_mgr=sm,
            experiments_root=experiments_root,
            provider=snap_provider,
        )
        reveal_svc.reveal("M001", exp_id)
        assert sm.market_status("M001") in (MarketStatus.PRICE_REVEALED, MarketStatus.BASELINE_CAPTURED)

        # Resolve
        res = Resolution(
            market_id="M001",
            resolved_at=datetime.now(timezone.utc),
            outcome=ResolutionOutcome.YES,
        )
        sm.record_market_resolved(exp_id, "M001", res)
        assert sm.market_status("M001") == MarketStatus.RESOLVED

        # Evaluate
        summary = evaluate_experiment(
            state_mgr=sm,
            experiments_root=experiments_root,
            experiment_id=exp_id,
        )
        assert summary.has_evaluable_cases()
        assert summary.evaluated_count == 1
        assert sm.market_status("M001") == MarketStatus.EVALUATED

        # Complete experiment
        sm.record_experiment_completed(exp_id)
        assert sm.experiment_status() == ExperimentStatus.COMPLETE

    def test_naive_timestamp_in_manifest_rejected(self, tmp_path: Path):
        from phase0.schemas import MarketManifest
        with pytest.raises(Exception):
            MarketManifest(
                experiment_id="P0-TEST",
                created_at=datetime(2025, 6, 1),
                selection_cutoff=datetime(2025, 6, 1, tzinfo=timezone.utc),
            )
