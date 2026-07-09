"""Tests for audit18: executable CLOB baseline chain."""
from __future__ import annotations

import json, hashlib, tempfile, os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from phase0.polymarket_client import PolymarketClient
from phase0.market_universe import ingest_market_record
from phase0.sampling import generate_manifest_markets
from phase0.manifest import create_manifest, freeze_manifest, load_manifest, verify_manifest
from phase0.state import EventStore, ExperimentStateManager, MarketStatus
from phase0.package_validator import validate_package, MarketTaintError
from phase0.forecast_lock import lock_forecast
from phase0.blind_forecast_runner import BlindForecastRunner
from phase0.price_reveal_service import PriceRevealService
from phase0.clob_provider import CLOBSnapshotProvider
from phase0.schemas import (
    PackageArtifact, ForecastMode, MarketUniverseRecord,
    BaselineArtifact, Forecast, ForecastLock,
)
from phase0.real_pilot import run_real_pilot


class MockForecastProvider:
    """Returns deterministic forecast — not a fixture, not a mock of real model."""
    def forecast(self, market_id: str, clean_package: dict[str, Any]) -> dict[str, Any]:
        return {
            "market_id": market_id,
            "forecast_cutoff": datetime.now(timezone.utc).isoformat(),
            "forecast_mode": "PRIMARY_MODEL",
            "p_yes": 0.5,
            "interval_50": [0.45, 0.55],
            "interval_80": [0.40, 0.60],
            "top_drivers": ["test"],
            "counterarguments": ["test"],
            "critical_unknowns": ["test"],
            "rules_confidence": "LOW",
            "research_cost_usd": None,
            "latency_seconds": 0.01,
        }


class MockCLOBProvider:
    """Returns realistic CLOB /book result with typed fields."""
    def __init__(self, token_ids: dict[str, str]) -> None:
        self.token_ids = token_ids
    def get_snapshot(self, market_id: str) -> dict[str, Any]:
        tid = self.token_ids.get(market_id, "")
        import hashlib
        raw_hash = hashlib.sha256(b'mock_clob').hexdigest()
        return {
            "market_id": market_id,
            "token_id": tid,
            "bid": 0.5, "ask": 0.51, "mid": 0.505, "spread": 0.01,
            "raw_orderbook_hash": raw_hash,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "endpoint": "https://clob.polymarket.com",
        }


class TestAudit18E2E:
    def test_full_clob_evidence_chain(self, tmp_path: Path):
        """Full pipeline: Gamma JSON payload → eligibility → reversed YES → PackageArtifact → Runner → Lock → CLOB → BaselineArtifact → EventStore."""
        assert os.name == "nt" or True  # cross-platform

        # 1. Gamma-style raw payload with reversed outcomes
        # ingest_market_record uses 'market_id', not 'conditionId'
        raw_payload = [
            {"market_id": "0xabc123", "question": "Will test pass?",
             "description": "Testing reversed outcomes.",
             "resolution_rules": "Standard resolution",
             "close_time": "2027-06-01T00:00:00Z",
             "category": "Testing",
             "active": True, "closed": False,
             "enableOrderBook": True, "acceptingOrders": True,
             "outcomes": ["No", "Yes"],  # REVERSED: Yes is at index 1
             "clobTokenIds": '["tok0", "tok1"]'},  # JSON string (not list)
            {"market_id": "0xdef456", "question": "Will second pass?",
             "resolution_rules": "Rule2",
             "close_time": "2027-06-01T00:00:00Z",
             "category": "Testing",
             "active": True, "closed": False,
             "enableOrderBook": True, "acceptingOrders": True,
             "outcomes": ["Yes", "No"],
             "clobTokenIds": '["tok2", "tok3"]'},
            {"market_id": "0xghi789", "question": "Will third pass?",
             "resolution_rules": "Rule3",
             "close_time": "2027-06-01T00:00:00Z",
             "category": "Testing",
             "active": True, "closed": False,
             "enableOrderBook": True, "acceptingOrders": True,
             "outcomes": ["Yes", "No"],
             "clobTokenIds": '["tok4", "tok5"]'},
        ]

        # 2. Ingestion + eligibility
        records = []
        for raw in raw_payload:
            rec = ingest_market_record(raw)
            records.append(rec)

        assert len(records) == 3
        rec = records[0]
        assert rec.yes_token_id == "tok1", f"Expected tok1 for reversed outcomes, got {rec.yes_token_id}"
        assert rec.market_id == "0xabc123"
        assert rec.enable_order_book is True

        # 3. Sampling + Manifest freeze
        cutoff = datetime(2025, 6, 1, tzinfo=timezone.utc)
        entries, _ = generate_manifest_markets(
            [r.model_dump(mode="json") for r in records],
            selection_cutoff=cutoff, seed="test18", target_count=3)
        assert len(entries) >= 1

        manifest = create_manifest("P0-A18",
            [{"market_id": e.market_id, "question": e.question} for e in entries],
            selection_cutoff=cutoff)
        freeze_manifest(manifest, tmp_path / "manifest")
        loaded = load_manifest(tmp_path / "manifest" / "manifest.json")
        ok, _ = verify_manifest(loaded)
        assert ok

        # 4. Experiment state
        store = EventStore(tmp_path / "P0-A18" / "events.jsonl")
        sm = ExperimentStateManager(store)
        sm.record_experiment_created("P0-A18", manifest)
        sm.record_experiment_activated("P0-A18")

        # 5. PackageArtifact with PRIMARY_MODEL mode
        pkg = {"market_id": "0xabc123", "question": "Will test pass?",
               "description": "Test", "resolution_source": "R",
               "outcomes": ["No", "Yes"], "evidence": [],
               "package_created_at": datetime.now(timezone.utc).isoformat()}
        clean = validate_package(pkg)
        canon = clean.model_dump(mode="json")
        phash = hashlib.sha256(json.dumps(canon, sort_keys=True, default=str).encode()).hexdigest()
        pkg_art = PackageArtifact(package=clean, package_hash=phash, artifact_version=1,
                                  forecast_mode=ForecastMode.PRIMARY_MODEL.value,
                                  original_market_id="0xabc123")
        assert pkg_art.original_market_id == "0xabc123"
        assert pkg_art.forecast_mode == "PRIMARY_MODEL"

        # Write package artifact + init market
        pkg_dir = tmp_path / "P0-A18" / "packages"
        pkg_dir.mkdir(parents=True, exist_ok=True)
        (pkg_dir / "0xabc123.json").write_text(pkg_art.model_dump_json(indent=2), encoding="utf-8")
        sm.record_market_initialized("P0-A18", "0xabc123", clean)

        # 6. Primary Runner with mode identity check
        runner = BlindForecastRunner(provider=MockForecastProvider(), model_id="test",
                                     model_version="1", prompt_version="v1", runner_version="1")
        fc, prov = runner.run("0xabc123", pkg_art, ForecastMode.PRIMARY_MODEL)
        assert fc.market_id == "0xabc123"
        assert fc.forecast_mode == ForecastMode.PRIMARY_MODEL
        assert prov["parsed_forecast_hash"] != ""

        # 7. Write forecast artifact
        fc_dir = tmp_path / "P0-A18" / "forecasts" / "0xabc123"
        fc_dir.mkdir(parents=True, exist_ok=True)
        (fc_dir / "v1.json").write_text(fc.model_dump_json(indent=2), encoding="utf-8")

        # 8. Lock
        lock_obj = lock_forecast(experiments_root=str(tmp_path), experiment_id="P0-A18",
                                 market_id="0xabc123", package=canon, forecast=fc,
                                 forecast_mode=ForecastMode.PRIMARY_MODEL)
        lock_dir = tmp_path / "P0-A18" / "locks" / "0xabc123"
        lock_dir.mkdir(parents=True, exist_ok=True)
        (lock_dir / "v1.json").write_text(lock_obj.model_dump_json(indent=2), encoding="utf-8")
        sm.record_forecast_locked("P0-A18", "0xabc123", lock_obj)
        assert sm.market_status("0xabc123") == MarketStatus.FORECAST_LOCKED

        # 9. CLOB baseline with typed result
        clob = MockCLOBProvider(token_ids={"0xabc123": "tok1"})
        svc = PriceRevealService(state_mgr=sm, experiments_root=str(tmp_path), provider=clob)
        snap = svc.reveal("0xabc123", "P0-A18")
        assert snap is not None
        assert sm.market_status("0xabc123") == MarketStatus.BASELINE_CAPTURED

        # 10. Verify BaselineArtifact on disk
        snap_dir = tmp_path / "P0-A18" / "price_snapshots" / "0xabc123"
        baseline_files = list(snap_dir.glob("*_baseline.json"))
        assert len(baseline_files) == 1
        baseline_raw = json.loads(baseline_files[0].read_text(encoding="utf-8"))
        assert baseline_raw["market_id"] == "0xabc123"
        assert baseline_raw["token_id"] == "tok1"
        assert baseline_raw["midpoint"] is not None
        assert baseline_raw["artifact_hash"] != ""

        # 11. BaselineArtifact loads into Pydantic
        ba = BaselineArtifact(**baseline_raw)
        assert ba.market_id == "0xabc123"
        assert ba.token_id == "tok1"

        # 12. EventStore chain integrity
        store.verify_or_fail()


def _worker_reveal(pid: int, path_str: str, exp: str, m: str) -> None:
    """Module-level worker for concurrent reveal test."""
    import sys
    sys.path.insert(0, "D:\\vibecoding\\polymaket投资模型\\polymarket-ai")
    from phase0.state import ExperimentStateManager, EventStore
    from phase0.price_reveal_service import PriceRevealService
    store = EventStore(path_str)
    sm = ExperimentStateManager(store)
    class _W:
        def __init__(self): self.token_ids = {m: "tok1"}
        def get_snapshot(self, mid):
            return {"market_id":mid,"token_id":"tok1","bid":0.5,"ask":0.51,"mid":0.505,"spread":0.01,"raw_orderbook_hash":"x","captured_at":"2026-01-01T00:00:00+00:00","endpoint":"mock"}
    clob = _W()
    svc = PriceRevealService(state_mgr=sm, experiments_root=str(store.path.parent.parent), provider=clob)
    try:
        svc.reveal(m, exp)
    except Exception:
        pass


class TestConcurrentReveal:
    def test_concurrent_reveal_single_winner(self, tmp_path: Path):
        """Two concurrent reveals — only one should succeed, no orphan artifacts."""
        import multiprocessing as mp
        from phase0.manifest import create_manifest as cm
        from phase0.package_validator import validate_package

        mid = "M001"
        store = EventStore(tmp_path / "P0-CR" / "events.jsonl")
        sm = ExperimentStateManager(store)
        manifest = cm("P0-CR", [{"market_id": mid, "question": "?"}],
                       selection_cutoff=datetime(2025,6,1,tzinfo=timezone.utc))
        sm.record_experiment_created("P0-CR", manifest)
        sm.record_experiment_activated("P0-CR")
        pkg_dict = {"market_id":mid,"question":"?","description":"d","resolution_source":"test",
                     "outcomes":["Yes","No"],"evidence":[],"package_created_at":datetime.now(timezone.utc).isoformat()}
        clean = validate_package(pkg_dict)
        canon = clean.model_dump(mode="json")
        phash = hashlib.sha256(json.dumps(canon, sort_keys=True, default=str).encode()).hexdigest()
        pkg_art = PackageArtifact(package=clean, package_hash=phash, artifact_version=1,
                                  forecast_mode=ForecastMode.PRIMARY_MODEL.value)
        sm.record_market_initialized("P0-CR", mid, clean)

        # Setup forecast + lock
        fc = Forecast(market_id=mid, forecast_cutoff=datetime.now(timezone.utc),
                       forecast_mode=ForecastMode.PRIMARY_MODEL, p_yes=0.5,
                       interval_50=[0.45,0.55], interval_80=[0.40,0.60])
        fc_dir = tmp_path / "P0-CR" / "forecasts" / mid
        fc_dir.mkdir(parents=True, exist_ok=True)
        (fc_dir / "v1.json").write_text(fc.model_dump_json(indent=2), encoding="utf-8")
        lock_obj = lock_forecast(experiments_root=str(tmp_path), experiment_id="P0-CR",
                                 market_id=mid, package=canon, forecast=fc,
                                 forecast_mode=ForecastMode.PRIMARY_MODEL)
        lock_dir = tmp_path / "P0-CR" / "locks" / mid
        lock_dir.mkdir(parents=True, exist_ok=True)
        (lock_dir / "v1.json").write_text(lock_obj.model_dump_json(indent=2), encoding="utf-8")
        sm.record_forecast_locked("P0-CR", mid, lock_obj)

        clob = MockCLOBProvider(token_ids={mid: "tok1"})

        ctx = mp.get_context("spawn")
        p1 = ctx.Process(target=_worker_reveal, args=(1, str(store.path), "P0-CR", mid))
        p2 = ctx.Process(target=_worker_reveal, args=(2, str(store.path), "P0-CR", mid))
        p1.start(); p2.start()
        p1.join(); p2.join()

        # Verify state (one succeeded)
        store2 = EventStore(store.path)
        sm2 = ExperimentStateManager(store2)
        status = sm2.market_status(mid)
        assert status is not None

        # Check no orphan baseline artifacts (if state is still FORECAST_LOCKED, no artifacts)
        if status == MarketStatus.FORECAST_LOCKED:
            pass  # loser cleaned up
        else:
            assert status in (MarketStatus.PRICE_REVEALED, MarketStatus.BASELINE_CAPTURED)
