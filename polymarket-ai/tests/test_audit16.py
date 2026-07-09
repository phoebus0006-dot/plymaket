"""Tests for audit16 fixes: YES token mapping, BaselineArtifact, runner identity, concurrency."""
from __future__ import annotations

import json
import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from phase0.state import EventStore, ExperimentStateManager
from phase0.schemas import (
    PackageArtifact,
    CleanForecastPackage,
    ForecastMode,
    Forecast,
    ForecastLock,
    MarketManifest,
    PriceSnapshot,
    ResolutionOutcome,
    MarketUniverseRecord,
)
from phase0.forecast_lock import lock_forecast
from phase0.blind_forecast_runner import BlindForecastRunner
from phase0.package_validator import validate_package, MarketTaintError
from phase0.clob_provider import CLOBSnapshotProvider
from phase0.polymarket_client import PolymarketClient
from phase0.price_reveal_service import PriceRevealService


# ─────────────────────────────────────────────
# Issue 1: YES Token Mapping
# ─────────────────────────────────────────────

class TestYESTokenMapping:
    def test_standard_yes_no(self):
        """Standard ['Yes', 'No'] -> token[0]"""
        token = PolymarketClient.resolve_yes_token(["Yes", "No"], ["tok0", "tok1"])
        assert token == "tok0"

    def test_reversed_no_yes(self):
        """Reversed ['No', 'Yes'] -> token[1]"""
        token = PolymarketClient.resolve_yes_token(["No", "Yes"], ["tok0", "tok1"])
        assert token == "tok1"

    def test_missing_yes_raises(self):
        """Missing YES outcome -> ValueError"""
        with pytest.raises(ValueError, match="no YES outcome"):
            PolymarketClient.resolve_yes_token(["No", "Maybe"], ["tok0", "tok1"])

    def test_length_mismatch_raises(self):
        """Length mismatch -> ValueError"""
        with pytest.raises(ValueError, match="outcomes count.*!=.*clobTokenIds count"):
            PolymarketClient.resolve_yes_token(["Yes", "No"], ["tok0"])

    def test_empty_outcomes_raises(self):
        """Empty outcomes -> ValueError"""
        with pytest.raises(ValueError, match="no outcomes parsed"):
            PolymarketClient.resolve_yes_token([], ["tok0"])

    def test_single_outcome_market(self):
        """Single outcome market -> token[0]"""
        token = PolymarketClient.resolve_yes_token(["Yes"], ["tok_only"])
        assert token == "tok_only"

    def test_yes_token_id_in_market_universe_record(self):
        """MarketUniverseRecord stores resolved yes_token_id."""
        raw = {
            "conditionId": "0x123",
            "question": "Will X happen?",
            "outcomes": ["Yes", "No"],
            "clobTokenIds": "['0xYES', '0xNO']",
            "enableOrderBook": True,
            "acceptingOrders": True,
        }
        rec = PolymarketClient.market_to_universe_record(raw)
        assert rec is not None
        assert rec.yes_token_id == "0xYES"
        assert rec.clob_token_ids == ["0xYES", "0xNO"]

    def test_yes_token_id_empty_when_no_outcomes(self):
        """yes_token_id is empty when outcomes are missing."""
        raw = {
            "conditionId": "0x123",
            "question": "Will X happen?",
            "clobTokenIds": "['0xYES']",
        }
        rec = PolymarketClient.market_to_universe_record(raw)
        assert rec is not None
        assert rec.yes_token_id == ""


# ─────────────────────────────────────────────
# Issue 2: CLOB Eligibility
# ─────────────────────────────────────────────

class TestCLOBYESToken:
    def test_provider_uses_yes_token_id(self):
        """CLOBSnapshotProvider token_ids maps condition_id -> YES token_id."""
        provider = CLOBSnapshotProvider(token_ids={"M001": "0xYES"})
        assert provider._token_ids["M001"] == "0xYES"

    def test_provider_has_no_last_provenance(self):
        """CLOBSnapshotProvider no longer has _last_provenance."""
        provider = CLOBSnapshotProvider(token_ids={})
        assert not hasattr(provider, '_last_provenance')

    def test_provider_raises_on_missing_token(self):
        """Missing token raises RuntimeError."""
        provider = CLOBSnapshotProvider(token_ids={})
        with pytest.raises(RuntimeError, match="No CLOB token_id"):
            provider.get_snapshot("MISSING")


# ─────────────────────────────────────────────
# Issue 3: Runner Identity Verification
# ─────────────────────────────────────────────

class FakeForecastProvider:
    def __init__(self, overrides: dict[str, Any] | None = None):
        self._overrides = overrides or {}

    def forecast(self, market_id: str, clean_package: dict[str, Any]) -> dict[str, Any]:
        base = {
            "market_id": market_id,
            "forecast_cutoff": datetime.now(timezone.utc).isoformat(),
            "forecast_mode": "PRIMARY_MODEL",
            "p_yes": 0.55,
            "interval_50": [0.50, 0.60],
            "interval_80": [0.40, 0.70],
            "top_drivers": [],
            "counterarguments": [],
            "critical_unknowns": [],
            "rules_confidence": "MEDIUM",
        }
        base.update(self._overrides)
        return base


class TestRunnerIdentity:
    def test_market_id_mismatch_rejected(self):
        """Forecast with wrong market_id raises RuntimeError."""
        clean_pkg = CleanForecastPackage(
            market_id="M001",
            question="?",
            description="d",
            resolution_source="test",
            outcomes=["Yes", "No"],
            package_created_at=datetime.now(timezone.utc),
        )
        canon = clean_pkg.model_dump(mode="json")
        ph = hashlib.sha256(json.dumps(canon, sort_keys=True, default=str).encode()).hexdigest()
        art = PackageArtifact(package=clean_pkg, package_hash=ph)

        provider = FakeForecastProvider(overrides={"market_id": "WRONG"})
        runner = BlindForecastRunner(provider=provider)

        with pytest.raises(RuntimeError, match="Forecast returned market_id WRONG != requested M001"):
            runner.run("M001", art, ForecastMode.PRIMARY_MODEL)

    def test_forecast_mode_mismatch_rejected(self):
        """Forecast with wrong forecast_mode raises RuntimeError."""
        clean_pkg = CleanForecastPackage(
            market_id="M001",
            question="?",
            description="d",
            resolution_source="test",
            outcomes=["Yes", "No"],
            package_created_at=datetime.now(timezone.utc),
        )
        canon = clean_pkg.model_dump(mode="json")
        ph = hashlib.sha256(json.dumps(canon, sort_keys=True, default=str).encode()).hexdigest()
        art = PackageArtifact(package=clean_pkg, package_hash=ph)

        provider = FakeForecastProvider(overrides={"forecast_mode": "CHEAP_BASELINE"})
        runner = BlindForecastRunner(provider=provider)

        with pytest.raises(RuntimeError, match="Forecast returned mode.*CHEAP_BASELINE.*!=.*PRIMARY_MODEL"):
            runner.run("M001", art, ForecastMode.PRIMARY_MODEL)

    def test_matching_identity_succeeds(self):
        """Correct identity passes verification."""
        clean_pkg = CleanForecastPackage(
            market_id="M001",
            question="?",
            description="d",
            resolution_source="test",
            outcomes=["Yes", "No"],
            package_created_at=datetime.now(timezone.utc),
        )
        canon = clean_pkg.model_dump(mode="json")
        ph = hashlib.sha256(json.dumps(canon, sort_keys=True, default=str).encode()).hexdigest()
        art = PackageArtifact(package=clean_pkg, package_hash=ph)

        provider = FakeForecastProvider()
        runner = BlindForecastRunner(provider=provider)

        fc, prov = runner.run("M001", art, ForecastMode.PRIMARY_MODEL)
        assert fc.market_id == "M001"
        assert fc.forecast_mode == ForecastMode.PRIMARY_MODEL


# ─────────────────────────────────────────────
# Issue 4: BaselineArtifact
# ─────────────────────────────────────────────

class TestBaselineArtifact:
    def test_baseline_artifact_created_and_persisted(self, tmp_path):
        """Full BaselineArtifact pipeline with mock CLOB provider."""
        from unittest.mock import MagicMock

        mock_provider = MagicMock()
        mock_provider.get_snapshot.return_value = {
            "market_id": "M001",
            "bid": 0.45,
            "ask": 0.55,
            "mid": 0.50,
            "spread": 0.10,
        }

        store = EventStore(str(tmp_path / "events.jsonl"))
        state_mgr = ExperimentStateManager(store)
        manifest = MarketManifest(
            experiment_id="EXP1",
            created_at=datetime.now(timezone.utc),
            selection_cutoff=datetime.now(timezone.utc),
        )
        state_mgr.record_experiment_created("EXP1", manifest)
        state_mgr.record_experiment_activated("EXP1")

        clean_pkg = CleanForecastPackage(
            market_id="M001",
            question="?",
            description="d",
            resolution_source="test",
            outcomes=["Yes", "No"],
            package_created_at=datetime.now(timezone.utc),
        )
        state_mgr.record_market_initialized("EXP1", "M001", clean_pkg)

        shared_cutoff = datetime.now(timezone.utc)

        lock_forecast = Forecast(
            market_id="M001",
            forecast_cutoff=shared_cutoff,
            forecast_mode=ForecastMode.PRIMARY_MODEL,
            p_yes=0.55,
            interval_50=[0.50, 0.60],
            interval_80=[0.40, 0.70],
        )

        # Create forecast artifact on disk (needed by PriceRevealService)
        forecast_dir = tmp_path / "EXP1" / "forecasts" / "M001"
        forecast_dir.mkdir(parents=True, exist_ok=True)
        forecast_path = forecast_dir / "v1.json"
        forecast_path.write_text(lock_forecast.model_dump_json(indent=2), encoding="utf-8")

        # Lock hash must match forecast artifact
        forecast_artifact_raw = json.dumps(lock_forecast.model_dump(mode="json"), sort_keys=True).encode("utf-8")
        forecast_artifact_hash = hashlib.sha256(forecast_artifact_raw).hexdigest()
        forecast_hash = hashlib.sha256(forecast_artifact_raw).hexdigest()

        # Create package artifact on disk
        pkg_dir = tmp_path / "EXP1" / "packages"
        pkg_dir.mkdir(parents=True, exist_ok=True)
        pkg_data = clean_pkg.model_dump(mode="json")
        pkg_hash = hashlib.sha256(json.dumps(pkg_data, sort_keys=True, default=str).encode("utf-8")).hexdigest()
        package_artifact = PackageArtifact(package=clean_pkg, package_hash=pkg_hash)
        (pkg_dir / "M001.json").write_text(package_artifact.model_dump_json(indent=2), encoding="utf-8")

        # Create lock artifact on disk
        lock_dir = tmp_path / "EXP1" / "locks" / "M001"
        lock_dir.mkdir(parents=True, exist_ok=True)
        lock = ForecastLock(
            forecast_id="M001_1",
            market_id="M001",
            forecast_version=1,
            forecast_cutoff=shared_cutoff,
            package_hash=pkg_hash,
            forecast_mode=ForecastMode.PRIMARY_MODEL,
            raw_probability=0.55,
            locked_at=datetime.now(timezone.utc),
            forecast_hash=forecast_hash,
            forecast_artifact_hash=forecast_artifact_hash,
        )
        (lock_dir / "v1.json").write_text(lock.model_dump_json(indent=2), encoding="utf-8")

        # Also record forecast_locked event in state machine
        state_mgr.record_forecast_locked("EXP1", "M001", lock)

        service = PriceRevealService(
            state_mgr=state_mgr,
            experiments_root=str(tmp_path),
            provider=mock_provider,
        )

        snapshot = service.reveal("M001", "EXP1", manifest_markets={"M001"})
        assert snapshot is not None
        assert snapshot.snapshot_id != ""

        # Verify BaselineArtifact file was persisted
        snap_dir = tmp_path / "EXP1" / "price_snapshots" / "M001"
        baseline_files = list(snap_dir.glob("*_baseline.json"))
        assert len(baseline_files) == 1

        baseline_raw = json.loads(baseline_files[0].read_text(encoding="utf-8"))
        assert baseline_raw["market_id"] == "M001"
        assert baseline_raw["best_bid"] == 0.45
        assert baseline_raw["best_ask"] == 0.55
        assert baseline_raw["mid"] == 0.50
        assert baseline_raw["spread"] == 0.10
        assert baseline_raw["forecast_id"] == "M001_1"
        assert baseline_raw["forecast_version"] == 1
        assert "artifact_hash" in baseline_raw
        assert "captured_at" in baseline_raw

        # Verify hash is consistent
        recomputed = hashlib.sha256(
            json.dumps(
                {k: v for k, v in baseline_raw.items() if k != "artifact_hash"},
                sort_keys=True, default=str,
            ).encode("utf-8")
        ).hexdigest()
        assert baseline_raw["artifact_hash"] == recomputed

        # Verify event contains baseline_artifact_hash
        events = store.read_all()
        price_events = [e for e in events if e.event_type == "price_revealed"]
        assert len(price_events) == 1
        assert price_events[0].data.get("baseline_artifact_hash") == recomputed


# ─────────────────────────────────────────────
# Issue 5: record_price_revealed baseline_artifact_hash
# ─────────────────────────────────────────────

class TestPriceRevealedHash:
    def test_baseline_artifact_hash_stored_in_event(self):
        """record_price_revealed stores baseline_artifact_hash in event data."""
        store = EventStore(Path.cwd() / "_test_pr_hash_events.jsonl")
        try:
            state_mgr = ExperimentStateManager(store)
            manifest = MarketManifest(
                experiment_id="EXP_HASH",
                created_at=datetime.now(timezone.utc),
                selection_cutoff=datetime.now(timezone.utc),
            )
            state_mgr.record_experiment_created("EXP_HASH", manifest)
            state_mgr.record_experiment_activated("EXP_HASH")

            clean_pkg = CleanForecastPackage(
                market_id="M_HASH",
                question="?",
                description="d",
                resolution_source="test",
                outcomes=["Yes", "No"],
                package_created_at=datetime.now(timezone.utc),
            )
            state_mgr.record_market_initialized("EXP_HASH", "M_HASH", clean_pkg)
            lock = ForecastLock(
                forecast_id="M_HASH_1",
                market_id="M_HASH",
                forecast_version=1,
                forecast_cutoff=datetime.now(timezone.utc),
                package_hash="0" * 64,
                forecast_mode=ForecastMode.PRIMARY_MODEL,
                raw_probability=0.5,
                locked_at=datetime.now(timezone.utc),
                forecast_hash="0" * 64,
            )
            state_mgr.record_forecast_locked("EXP_HASH", "M_HASH", lock)

            snap = PriceSnapshot(market_id="M_HASH", bid=0.4, ask=0.6, mid=0.5, spread=0.2)
            ev = state_mgr.record_price_revealed(
                "EXP_HASH", "M_HASH", snap, baseline_artifact_hash="abcdef123456",
            )
            assert ev.data.get("baseline_artifact_hash") == "abcdef123456"
        finally:
            p = Path.cwd() / "_test_pr_hash_events.jsonl"
            if p.exists():
                p.unlink()


# ─────────────────────────────────────────────
# Issue 6: State machine concurrency
# ─────────────────────────────────────────────

def _race_forecast_lock_worker(pid: int, path_str: str, exp_id: str, market_id: str):
    """Worker that tries to lock a forecast."""
    try:
        store = EventStore(path_str)
        state_mgr = ExperimentStateManager(store)
        lock = ForecastLock(
            forecast_id=f"{market_id}_{pid}",
            market_id=market_id,
            forecast_version=pid,
            forecast_cutoff=datetime.now(timezone.utc),
            package_hash="0" * 64,
            forecast_mode=ForecastMode.PRIMARY_MODEL,
            raw_probability=0.5,
            locked_at=datetime.now(timezone.utc),
            forecast_hash="0" * 64,
        )
        state_mgr.record_forecast_locked(exp_id, market_id, lock)
        return "ok"
    except Exception as e:
        return f"fail:{e}"


def _race_baseline_worker(pid: int, path_str: str, exp_id: str, market_id: str):
    """Worker that tries to capture baseline."""
    try:
        store = EventStore(path_str)
        state_mgr = ExperimentStateManager(store)
        state_mgr.record_baseline_captured(exp_id, market_id)
        return "ok"
    except Exception as e:
        return f"fail:{e}"


class TestEventStoreConcurrentTransitions:
    def test_same_forecast_lock_single_winner(self, tmp_path: Path):
        """Concurrent forecast_locked for same market -> single winner."""
        import multiprocessing as mp

        ev_path = tmp_path / "events.jsonl"
        store = EventStore(str(ev_path))
        state_mgr = ExperimentStateManager(store)
        manifest = MarketManifest(
            experiment_id="RACE_EXP",
            created_at=datetime.now(timezone.utc),
            selection_cutoff=datetime.now(timezone.utc),
        )
        state_mgr.record_experiment_created("RACE_EXP", manifest)
        state_mgr.record_experiment_activated("RACE_EXP")
        clean_pkg = CleanForecastPackage(
            market_id="RACE_M",
            question="?",
            description="d",
            resolution_source="test",
            outcomes=["Yes", "No"],
            package_created_at=datetime.now(timezone.utc),
        )
        state_mgr.record_market_initialized("RACE_EXP", "RACE_M", clean_pkg)

        n_procs = 4
        ctx = mp.get_context("spawn")
        procs = [
            ctx.Process(target=_race_forecast_lock_worker, args=(i, str(ev_path), "RACE_EXP", "RACE_M"))
            for i in range(n_procs)
        ]
        for p in procs:
            p.start()
        for p in procs:
            p.join()

        events = store.read_all()
        forecast_locked_events = [e for e in events if e.event_type == "forecast_locked"]
        assert len(forecast_locked_events) == 1, (
            f"Expected 1 forecast_locked event, got {len(forecast_locked_events)}"
        )

    def test_same_baseline_capture_single_winner(self, tmp_path: Path):
        """Concurrent baseline_captured for same market -> single winner."""
        import multiprocessing as mp

        ev_path = tmp_path / "events.jsonl"
        store = EventStore(str(ev_path))
        state_mgr = ExperimentStateManager(store)
        manifest = MarketManifest(
            experiment_id="RACE_EXP2",
            created_at=datetime.now(timezone.utc),
            selection_cutoff=datetime.now(timezone.utc),
        )
        state_mgr.record_experiment_created("RACE_EXP2", manifest)
        state_mgr.record_experiment_activated("RACE_EXP2")
        clean_pkg = CleanForecastPackage(
            market_id="RACE_M2",
            question="?",
            description="d",
            resolution_source="test",
            outcomes=["Yes", "No"],
            package_created_at=datetime.now(timezone.utc),
        )
        state_mgr.record_market_initialized("RACE_EXP2", "RACE_M2", clean_pkg)
        lock = ForecastLock(
            forecast_id="RACE_M2_1",
            market_id="RACE_M2",
            forecast_version=1,
            forecast_cutoff=datetime.now(timezone.utc),
            package_hash="0" * 64,
            forecast_mode=ForecastMode.PRIMARY_MODEL,
            raw_probability=0.5,
            locked_at=datetime.now(timezone.utc),
            forecast_hash="0" * 64,
        )
        state_mgr.record_forecast_locked("RACE_EXP2", "RACE_M2", lock)
        state_mgr.record_price_revealed("RACE_EXP2", "RACE_M2")

        n_procs = 4
        ctx = mp.get_context("spawn")
        procs = [
            ctx.Process(target=_race_baseline_worker, args=(i, str(ev_path), "RACE_EXP2", "RACE_M2"))
            for i in range(n_procs)
        ]
        for p in procs:
            p.start()
        for p in procs:
            p.join()

        events = store.read_all()
        baseline_events = [e for e in events if e.event_type == "baseline_captured"]
        assert len(baseline_events) == 1, (
            f"Expected 1 baseline_captured event, got {len(baseline_events)}"
        )


# ─────────────────────────────────────────────
# Issue 7: PackageArtifact identity verification
# ─────────────────────────────────────────────

class TestRunnerPackageArtifact:
    def test_original_market_id_mismatch_rejected(self):
        """PackageArtifact.original_market_id mismatch raises RuntimeError."""
        clean_pkg = CleanForecastPackage(
            market_id="M001",
            question="?",
            description="d",
            resolution_source="test",
            outcomes=["Yes", "No"],
            package_created_at=datetime.now(timezone.utc),
        )
        canon = clean_pkg.model_dump(mode="json")
        ph = hashlib.sha256(json.dumps(canon, sort_keys=True, default=str).encode()).hexdigest()
        art = PackageArtifact(
            package=clean_pkg,
            package_hash=ph,
            original_market_id="WRONG_PARENT",
        )
        provider = FakeForecastProvider()
        runner = BlindForecastRunner(provider=provider)

        with pytest.raises(RuntimeError, match="PackageArtifact original_market_id WRONG_PARENT != M001"):
            runner.run("M001", art, ForecastMode.PRIMARY_MODEL)

    def test_original_market_id_empty_skipped(self):
        """Empty original_market_id is skipped (no error)."""
        clean_pkg = CleanForecastPackage(
            market_id="M001",
            question="?",
            description="d",
            resolution_source="test",
            outcomes=["Yes", "No"],
            package_created_at=datetime.now(timezone.utc),
        )
        canon = clean_pkg.model_dump(mode="json")
        ph = hashlib.sha256(json.dumps(canon, sort_keys=True, default=str).encode()).hexdigest()
        art = PackageArtifact(package=clean_pkg, package_hash=ph, original_market_id="")

        provider = FakeForecastProvider()
        runner = BlindForecastRunner(provider=provider)

        fc, prov = runner.run("M001", art, ForecastMode.PRIMARY_MODEL)
        assert fc.market_id == "M001"


# ─────────────────────────────────────────────
# Nested taint detection
# ─────────────────────────────────────────────

class TestNestedTaint:
    def test_nested_dict_taint_detected(self):
        """Taint inside nested dict is detected by _taint_audit."""
        pkg = CleanForecastPackage(
            market_id="M001",
            question="?",
            description="d",
            resolution_source="test",
            outcomes=["Yes", "No"],
            evidence=[{"source": "https://example.com", "market_price": 0.75}],
            package_created_at=datetime.now(timezone.utc),
        )
        canon = pkg.model_dump(mode="json")
        ph = hashlib.sha256(json.dumps(canon, sort_keys=True, default=str).encode()).hexdigest()
        art = PackageArtifact(package=pkg, package_hash=ph)

        provider = FakeForecastProvider()
        runner = BlindForecastRunner(provider=provider)

        with pytest.raises(RuntimeError, match="Package taint detected"):
            runner.run("M001", art, ForecastMode.PRIMARY_MODEL)

    def test_nested_list_taint_detected(self):
        """Taint inside nested list is detected by _taint_audit."""
        pkg = CleanForecastPackage(
            market_id="M001",
            question="?",
            description="d",
            resolution_source="test",
            outcomes=["Yes", "No"],
            references=[{"title": "ref1", "data": {"current_price": 0.5}}],
            package_created_at=datetime.now(timezone.utc),
        )
        canon = pkg.model_dump(mode="json")
        ph = hashlib.sha256(json.dumps(canon, sort_keys=True, default=str).encode()).hexdigest()
        art = PackageArtifact(package=pkg, package_hash=ph)

        provider = FakeForecastProvider()
        runner = BlindForecastRunner(provider=provider)

        with pytest.raises(RuntimeError, match="Package taint detected"):
            runner.run("M001", art, ForecastMode.PRIMARY_MODEL)
