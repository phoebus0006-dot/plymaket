"""Tests for audit15 fixes: pilot control flow, CLOB provenance, EventStore race."""
from __future__ import annotations

import json, os, hashlib, time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from phase0.state import EventStore, ExperimentStateManager
from phase0.schemas import (
    PackageArtifact, CleanForecastPackage, ForecastMode, Forecast,
    ForecastLock, PriceSnapshot, ResolutionOutcome,
)
from phase0.forecast_lock import lock_forecast
from phase0.blind_forecast_runner import BlindForecastRunner
from phase0.package_validator import validate_package, MarketTaintError
from phase0.clob_provider import CLOBSnapshotProvider

# Test 1: EventStore concurrent first-create race
def _race_worker(pid: int, p: str, exp: str, n: int):
    store = EventStore(p)
    for i in range(n):
        store.append("sim_event", exp, {"pid": pid, "i": i})

class TestEventStoreConcurrentCreate:
    def test_concurrent_first_append(self, tmp_path: Path):
        import multiprocessing as mp
        path = tmp_path / "events.jsonl"
        n_procs = 4
        n_events = 10

        ctx = mp.get_context("spawn")
        procs = [ctx.Process(target=_race_worker, args=(i, str(path), "P0-RACE", n_events)) for i in range(n_procs)]
        for p in procs: p.start()
        for p in procs: p.join()

        store = EventStore(path)
        events = store.read_all()
        total = len(events)
        seqs = [e.event_sequence for e in events]
        assert total == n_procs * n_events, f"Expected {n_procs * n_events}, got {total}"
        assert len(set(seqs)) == n_procs * n_events, "Duplicate sequences"
        assert min(seqs) == 1, f"Min seq {min(seqs)} != 1"
        assert max(seqs) == n_procs * n_events
        ok, _ = store.verify_chain()
        assert ok


# Test 2: lock_forecast argument fail-closed
class TestLockArgConsistency:
    def test_market_id_mismatch_rejected(self, tmp_path: Path):
        fc = Forecast(market_id="M001", forecast_cutoff=datetime.now(timezone.utc),
                       forecast_mode=ForecastMode.PRIMARY_MODEL, p_yes=0.5,
                       interval_50=[0.45, 0.55], interval_80=[0.40, 0.60])
        d = tmp_path / "P0-TEST" / "forecasts" / "M001"
        d.mkdir(parents=True, exist_ok=True)
        (d / "v1.json").write_text(fc.model_dump_json(indent=2), encoding="utf-8")
        with pytest.raises(RuntimeError, match="Lock forecast argument consistency"):
            lock_forecast(experiments_root=str(tmp_path), experiment_id="P0-TEST",
                          market_id="WRONG", package={}, forecast=fc,
                          forecast_mode=ForecastMode.PRIMARY_MODEL)

    def test_mode_mismatch_rejected(self, tmp_path: Path):
        fc = Forecast(market_id="M001", forecast_cutoff=datetime.now(timezone.utc),
                       forecast_mode=ForecastMode.PRIMARY_MODEL, p_yes=0.5,
                       interval_50=[0.45, 0.55], interval_80=[0.40, 0.60])
        d = tmp_path / "P0-TEST" / "forecasts" / "M001"
        d.mkdir(parents=True, exist_ok=True)
        (d / "v1.json").write_text(fc.model_dump_json(indent=2), encoding="utf-8")
        with pytest.raises(RuntimeError, match="Lock forecast argument consistency"):
            lock_forecast(experiments_root=str(tmp_path), experiment_id="P0-TEST",
                          market_id="M001", package={}, forecast=fc,
                          forecast_mode=ForecastMode.CHEAP_BASELINE)


# Test 3: BlindForecastRunner package validation
class TestRunnerPackageValidation:
    def test_price_taint_rejected(self):
        from phase0.schemas import PackageArtifact, ForecastMode
        from phase0.blind_forecast_runner import BlindForecastRunner
        pkg = {"market_id": "M001", "question": "?", "description": "d",
               "resolution_source": "test", "outcomes": ["Yes", "No"],
               "evidence": [], "package_created_at": datetime.now(timezone.utc).isoformat(),
               "bid": 0.5}
        with pytest.raises(MarketTaintError):
            validate_package(pkg)
        # Should also fail via BlindForecastRunner
        with pytest.raises(RuntimeError, match="Package hash mismatch|Package taint detected"):
            clean = CleanForecastPackage(
                market_id="M001", question="?", description="d",
                resolution_source="test", outcomes=["Yes", "No"],
                package_created_at=datetime.now(timezone.utc))
            canon = clean.model_dump(mode="json")
            canon["bid"] = 0.5  # inject taint after validation
            ph = hashlib.sha256(json.dumps(canon, sort_keys=True, default=str).encode()).hexdigest()
            art = PackageArtifact(package=clean, package_hash=ph)
            runner = BlindForecastRunner(provider=None)
            runner.run("M001", art, ForecastMode.PRIMARY_MODEL)

# Test 4: CLOB token_id mapping (replaced _last_provenance with condition_id→YES_token_id)
class TestCLOBTokenIdMapping:
    def test_token_ids_is_empty_dict(self):
        """CLOBSnapshotProvider accepts empty token_ids."""
        provider = CLOBSnapshotProvider(token_ids={})
        assert provider._token_ids == {}


# Test 5: CLOB eligibility filtering
class TestCLOBEligibility:
    def test_market_universe_record_has_clob_fields(self):
        from phase0.polymarket_client import PolymarketClient
        from phase0.schemas import MarketUniverseRecord
        rec = MarketUniverseRecord(market_id="M001", question="?", resolution_rules="R",
                                    enable_order_book=True, clob_token_ids=["123", "456"])
        assert rec.enable_order_book is True
        assert len(rec.clob_token_ids) == 2
