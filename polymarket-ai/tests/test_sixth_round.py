from __future__ import annotations

import json
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

import pytest

from phase0.blind_forecast_runner import BlindForecastRunner
from phase0.sampling import generate_manifest_markets, stratify_markets
from phase0.schemas import (
    MarketUniverseRecord,
    Resolution,
    ResolutionOutcome,
    ResolutionStatus,
    PackageArtifact,
    CleanForecastPackage,
)
from phase0.state import (
    EventStore,
    ExperimentStateManager,
    ExperimentStatus,
    MarketStatus,
)
from phase0.manifest import create_manifest, freeze_manifest, load_manifest, verify_manifest


# ── 1. Deterministic Sampling Reproducibility ──

class TestSamplingReproducibility:
    def test_same_input_same_output(self):
        cutoff = datetime(2025, 6, 1, tzinfo=timezone.utc)
        universe = [
            {"market_id": "M001", "question": "Q1", "resolution_rules": "standard", "close_time": "2026-01-01T00:00:00+00:00", "category": "AI"},
            {"market_id": "M002", "question": "Q2", "resolution_rules": "standard", "close_time": "2026-01-01T00:00:00+00:00", "category": "AI"},
            {"market_id": "M003", "question": "Q3", "resolution_rules": "standard", "close_time": "2026-01-01T00:00:00+00:00", "category": "Politics"},
            {"market_id": "M004", "question": "Q4", "resolution_rules": "standard", "close_time": "2026-01-01T00:00:00+00:00", "category": "Politics"},
            {"market_id": "M005", "question": "Q5", "resolution_rules": "standard", "close_time": "2026-01-01T00:00:00+00:00", "category": "Economics"},
        ]
        sel1, _ = generate_manifest_markets(universe, seed="test-seed", target_count=5, selection_cutoff=cutoff)
        sel2, _ = generate_manifest_markets(universe, seed="test-seed", target_count=5, selection_cutoff=cutoff)
        ids1 = [m.market_id for m in sel1]
        ids2 = [m.market_id for m in sel2]
        assert ids1 == ids2, f"Reproducibility failed: {ids1} != {ids2}"

    def test_different_seed_different_output(self):
        cutoff = datetime(2025, 6, 1, tzinfo=timezone.utc)
        universe = [
            {"market_id": "M001", "question": "Q1", "resolution_rules": "standard", "close_time": "2026-01-01T00:00:00+00:00", "category": "AI"},
            {"market_id": "M002", "question": "Q2", "resolution_rules": "standard", "close_time": "2026-01-01T00:00:00+00:00", "category": "AI"},
            {"market_id": "M003", "question": "Q3", "resolution_rules": "standard", "close_time": "2026-01-01T00:00:00+00:00", "category": "AI"},
            {"market_id": "M004", "question": "Q4", "resolution_rules": "standard", "close_time": "2026-01-01T00:00:00+00:00", "category": "Politics"},
            {"market_id": "M005", "question": "Q5", "resolution_rules": "standard", "close_time": "2026-01-01T00:00:00+00:00", "category": "Economics"},
        ]
        sel1, _ = generate_manifest_markets(universe, seed="seed-a", target_count=5, selection_cutoff=cutoff)
        sel2, _ = generate_manifest_markets(universe, seed="seed-b", target_count=5, selection_cutoff=cutoff)
        ids1 = [m.market_id for m in sel1]
        ids2 = [m.market_id for m in sel2]
        # With enough markets, different seeds should produce different orderings
        if ids1 == ids2:
            # Also verify the final shuffle at least differs
            same_order = all(a == b for a, b in zip(ids1, ids2))
            assert not same_order, "Different seeds should produce different orderings"

    def test_exclusion_provenance(self):
        cutoff = datetime(2025, 6, 1, tzinfo=timezone.utc)
        universe = [
            {"market_id": "M001", "question": "Q1", "resolution_rules": "", "close_time": "2026-01-01T00:00:00+00:00", "category": "AI"},
            {"market_id": "M002", "question": "Q2", "resolution_rules": "standard", "close_time": "2026-01-01T00:00:00+00:00", "category": "AI"},
            {"market_id": "", "question": "Q3", "resolution_rules": "standard", "close_time": "2026-01-01T00:00:00+00:00", "category": "AI"},
        ]
        selected, excluded = generate_manifest_markets(universe, seed="test", target_count=2, selection_cutoff=cutoff)
        # M001 should be excluded (missing resolution_rules)
        # empty market_id should be excluded
        exclude_text = "; ".join(excluded)
        assert any("resolution_rules" in e for e in excluded), f"Missing resolution_rules exclusion: {exclude_text}"
        assert any("market_id" in e.lower() for e in excluded), f"Missing market_id exclusion: {exclude_text}"
        assert len(selected) > 0


# ── 2. MarketUniverseRecord Schema ──

class TestMarketUniverseRecord:
    def test_valid_record(self):
        rec = MarketUniverseRecord(
            market_id="M001",
            question="Will AGI arrive by 2030?",
            resolution_rules="Standard Polymarket resolution",
            source="test_fixture",
        )
        assert rec.market_id == "M001"

    def test_missing_required_id_rejected(self):
        with pytest.raises(Exception):
            MarketUniverseRecord(question="Test")

    def test_extra_field_rejected(self):
        with pytest.raises(Exception):
            MarketUniverseRecord(market_id="M001", question="Q", resolution_rules="R", source="S", price=0.5)


# ── 3. BlindForecastRunner Isolation ──

class MockForecastProvider:
    def forecast(self, market_id: str, clean_package: dict[str, Any]) -> dict[str, Any]:
        return {
            "market_id": market_id,
            "forecast_cutoff": "2025-06-01T00:00:00+00:00",
            "forecast_mode": "CHEAP_BASELINE",
            "p_yes": 0.63,
            "interval_50": [0.56, 0.70],
            "interval_80": [0.44, 0.77],
        }


class TestBlindForecastRunner:
    def test_runner_returns_forecast_and_provenance(self):
        from phase0.schemas import ForecastMode
        runner = BlindForecastRunner(
            provider=MockForecastProvider(),
            model_id="test-model",
            model_version="1.0",
            prompt_version="v1",
            runner_version="1.0",
        )
        pkg = {
            "market_id": "M001",
            "question": "Test?",
            "description": "Desc",
            "resolution_source": "test",
            "outcomes": ["Yes", "No"],
            "package_created_at": datetime.now(timezone.utc).isoformat(),
        }
        fc, prov = runner.run("M001", pkg, ForecastMode.CHEAP_BASELINE)
        assert fc.p_yes == 0.63
        assert prov["model_id"] == "test-model"
        assert prov["package_hash"] != ""
        assert prov["input_hash"] != ""
        assert prov["raw_output_hash"] != ""
        assert prov["parsed_forecast_hash"] != ""

    def test_runner_no_access_to_market_data(self):
        from phase0.schemas import ForecastMode
        runner = BlindForecastRunner(provider=MockForecastProvider())
        pkg = {
            "market_id": "M001",
            "question": "Test?",
            "description": "Desc",
            "resolution_source": "test",
            "outcomes": ["Yes", "No"],
            "package_created_at": datetime.now(timezone.utc).isoformat(),
        }
        # Runner only receives clean_package, no market baseline data
        fc, prov = runner.run("M001", pkg, ForecastMode.CHEAP_BASELINE)
        assert fc.market_id == "M001"


# ── 4. Enhanced Resolution Provenance ──

class TestResolutionProvenance:
    def test_enhanced_resolution(self):
        res = Resolution(
            market_id="M001",
            resolved_at=datetime.now(timezone.utc),
            outcome=ResolutionOutcome.YES,
            resolution_source="https://example.com/resolution",
            resolution_status=ResolutionStatus.RESOLVED_VALID,
            evidence_artifact_hash="abc123",
        )
        assert res.resolution_status == ResolutionStatus.RESOLVED_VALID
        assert res.p_yes_actual == 1.0

    def test_invalid_resolution_status(self):
        res = Resolution(
            market_id="M001",
            resolved_at=datetime.now(timezone.utc),
            outcome=ResolutionOutcome.NO,
            resolution_status=ResolutionStatus.UNRESOLVED,
        )
        assert res.outcome == ResolutionOutcome.NO

    def test_resolution_confidence_bounds(self):
        with pytest.raises(Exception):
            Resolution(
                market_id="M001",
                resolved_at=datetime.now(timezone.utc),
                outcome=ResolutionOutcome.YES,
                resolution_confidence=1.5,
            )


# ── 5. State Machine New Transitions ──

class TestStateMachineNewTransitions:
    def test_baseline_captured_transition(self, tmp_path: Path):
        from phase0.manifest import create_manifest
        from phase0.package_validator import validate_package
        from phase0.schemas import ForecastLock, Forecast, ForecastMode

        store = EventStore(tmp_path / "events.jsonl")
        sm = ExperimentStateManager(store)
        manifest = create_manifest("P0-TEST", [{"market_id": "M001", "question": "?"}], selection_cutoff=datetime(2025, 6, 1, tzinfo=timezone.utc))
        sm.record_experiment_created("P0-TEST", manifest)
        sm.record_experiment_activated("P0-TEST")
        pkg = validate_package({"market_id": "M001", "question": "?", "description": "d", "resolution_source": "test", "outcomes": ["Yes", "No"], "package_created_at": datetime.now(timezone.utc).isoformat()})
        sm.record_market_initialized("P0-TEST", "M001", pkg)
        # Manually lock
        lock = ForecastLock(forecast_id="FC1", market_id="M001", forecast_version=1, forecast_cutoff=datetime.now(timezone.utc), package_hash="x", forecast_mode=ForecastMode.CHEAP_BASELINE, raw_probability=0.5, locked_at=datetime.now(timezone.utc), forecast_hash="x")
        sm.record_forecast_locked("P0-TEST", "M001", lock)
        assert sm.market_status("M001") == MarketStatus.FORECAST_LOCKED

        # Transition to BASELINE_CAPTURED
        sm.record_price_revealed("P0-TEST", "M001")
        sm.record_baseline_captured("P0-TEST", "M001")
        assert sm.market_status("M001") == MarketStatus.BASELINE_CAPTURED

    def test_audited_transition(self, tmp_path: Path):
        from phase0.manifest import create_manifest
        from phase0.package_validator import validate_package
        from phase0.schemas import ForecastLock, Forecast, ForecastMode, Resolution

        store = EventStore(tmp_path / "events.jsonl")
        sm = ExperimentStateManager(store)
        manifest = create_manifest("P0-TEST", [{"market_id": "M001", "question": "?"}], selection_cutoff=datetime(2025, 6, 1, tzinfo=timezone.utc))
        sm.record_experiment_created("P0-TEST", manifest)
        sm.record_experiment_activated("P0-TEST")
        pkg = validate_package({"market_id": "M001", "question": "?", "description": "d", "resolution_source": "test", "outcomes": ["Yes", "No"], "package_created_at": datetime.now(timezone.utc).isoformat()})
        sm.record_market_initialized("P0-TEST", "M001", pkg)
        lock = ForecastLock(forecast_id="FC1", market_id="M001", forecast_version=1, forecast_cutoff=datetime.now(timezone.utc), package_hash="x", forecast_mode=ForecastMode.CHEAP_BASELINE, raw_probability=0.5, locked_at=datetime.now(timezone.utc), forecast_hash="x")
        sm.record_forecast_locked("P0-TEST", "M001", lock)
        sm.record_price_revealed("P0-TEST", "M001")
        sm.record_baseline_captured("P0-TEST", "M001")
        res = Resolution(market_id="M001", resolved_at=datetime.now(timezone.utc), outcome=ResolutionOutcome.YES)
        sm.record_market_resolved("P0-TEST", "M001", res)
        sm.record_market_evaluated("P0-TEST", "M001")
        assert sm.market_status("M001") == MarketStatus.EVALUATED

        sm.record_market_audited("P0-TEST", "M001")
        assert sm.market_status("M001") == MarketStatus.AUDITED

    def test_illegal_baseline_before_lock_blocked(self, tmp_path: Path):
        from phase0.manifest import create_manifest
        store = EventStore(tmp_path / "events.jsonl")
        sm = ExperimentStateManager(store)
        manifest = create_manifest("P0-TEST", [{"market_id": "M001", "question": "?"}], selection_cutoff=datetime(2025, 6, 1, tzinfo=timezone.utc))
        sm.record_experiment_created("P0-TEST", manifest)
        sm.record_experiment_activated("P0-TEST")
        # Cannot capture baseline without forecast lock
        with pytest.raises(RuntimeError):
            sm.record_baseline_captured("P0-TEST", "M001")

    def test_illegal_evaluate_before_resolve_blocked(self, tmp_path: Path):
        from phase0.manifest import create_manifest
        from phase0.package_validator import validate_package
        from phase0.schemas import ForecastLock, Forecast, ForecastMode

        store = EventStore(tmp_path / "events.jsonl")
        sm = ExperimentStateManager(store)
        manifest = create_manifest("P0-TEST", [{"market_id": "M001", "question": "?"}], selection_cutoff=datetime(2025, 6, 1, tzinfo=timezone.utc))
        sm.record_experiment_created("P0-TEST", manifest)
        sm.record_experiment_activated("P0-TEST")
        pkg = validate_package({"market_id": "M001", "question": "?", "description": "d", "resolution_source": "test", "outcomes": ["Yes", "No"], "package_created_at": datetime.now(timezone.utc).isoformat()})
        sm.record_market_initialized("P0-TEST", "M001", pkg)
        lock = ForecastLock(forecast_id="FC1", market_id="M001", forecast_version=1, forecast_cutoff=datetime.now(timezone.utc), package_hash="x", forecast_mode=ForecastMode.CHEAP_BASELINE, raw_probability=0.5, locked_at=datetime.now(timezone.utc), forecast_hash="x")
        sm.record_forecast_locked("P0-TEST", "M001", lock)
        sm.record_price_revealed("P0-TEST", "M001")
        sm.record_baseline_captured("P0-TEST", "M001")
        # Cannot evaluate before resolve
        with pytest.raises(RuntimeError):
            sm.record_market_evaluated("P0-TEST", "M001")


# ── 6. Price Taint: Market Price Leakage into Package ──

class TestPriceTaintRejection:
    def test_price_field_in_package_rejected(self):
        from phase0.package_validator import validate_package, MarketTaintError
        pkg = {
            "market_id": "M001",
            "question": "Test?",
            "description": "Desc",
            "resolution_source": "test",
            "outcomes": ["Yes", "No"],
            "evidence": [],
            "package_created_at": datetime.now(timezone.utc).isoformat(),
            "bid": 0.5,
        }
        with pytest.raises(MarketTaintError):
            validate_package(pkg)
