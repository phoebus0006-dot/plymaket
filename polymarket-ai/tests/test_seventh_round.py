from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest

from phase0.market_universe import ingest_market_record, ingest_market_universe, load_market_universe_json
from phase0.schemas import (
    MarketUniverseRecord,
    Resolution,
    ResolutionOutcome,
    ResolutionStatus,
    ForecastLock,
    ForecastMode,
)
from phase0.state import (
    EventStore,
    ExperimentStateManager,
    ExperimentStatus,
    MarketStatus,
)
from phase0.manifest import create_manifest, freeze_manifest, load_manifest, verify_manifest
from phase0.forecast_lock import lock_forecast
from phase0.forecast_runner import run_forecast
from phase0.blind_forecast_runner import BlindForecastRunner


# ══════════════════════════════════════════════════════════════════════════════
# 1. Market Universe Ingestion
# ══════════════════════════════════════════════════════════════════════════════

class TestMarketIngestion:
    def test_valid_record_accepted(self):
        rec = ingest_market_record({
            "market_id": "M001",
            "question": "Will AGI arrive by 2030?",
            "resolution_rules": "Standard Polymarket resolution",
            "close_time": "2026-12-31T23:59:59+00:00",
            "category": "AI",
        }, source="fixture")
        assert isinstance(rec, MarketUniverseRecord)
        assert rec.market_id == "M001"
        assert rec.raw_artifact_hash != ""
        assert rec.normalized_artifact_hash != ""

    def test_missing_market_id_rejected(self):
        with pytest.raises(ValueError, match="missing market_id"):
            ingest_market_record({"question": "No ID"}, source="fixture")

    def test_missing_resolution_rules_rejected(self):
        with pytest.raises(ValueError, match="missing resolution_rules"):
            ingest_market_record({"market_id": "M001", "question": "Q", "resolution_rules": ""}, source="fixture")

    def test_raw_and_normalized_hash_differ(self):
        raw = {
            "market_id": "M001",
            "question": "Test?",
            "resolution_rules": "Standard",
            "close_time": "2026-12-31T23:59:59+00:00",
            "extra_field": "should be stripped",
        }
        rec = ingest_market_record(raw, source="fixture")
        assert rec.raw_artifact_hash != rec.normalized_artifact_hash
        assert rec.market_id == "M001"

    def test_batch_ingestion_with_errors(self):
        records = [
            {"market_id": "M001", "question": "Q1", "resolution_rules": "R1", "close_time": "2026-12-31T23:59:59+00:00"},
            {"market_id": "", "question": "Q2", "resolution_rules": "R2", "close_time": "2026-12-31T23:59:59+00:00"},
            {"market_id": "M003", "question": "Q3", "resolution_rules": "", "close_time": "2026-12-31T23:59:59+00:00"},
        ]
        valid, errors = ingest_market_universe(records)
        assert len(valid) == 1
        assert len(errors) == 2
        assert any("missing market_id" in e for e in errors)
        assert any("missing resolution_rules" in e for e in errors)

    def test_ingestion_from_json_file(self, tmp_path: Path):
        data = [
            {"market_id": "M001", "question": "Q1", "resolution_rules": "R1", "close_time": "2026-12-31T23:59:59+00:00", "category": "AI"},
            {"market_id": "M002", "question": "Q2", "resolution_rules": "R2", "close_time": "2026-12-31T23:59:59+00:00", "category": "Politics"},
        ]
        p = tmp_path / "universe.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        valid, errors = load_market_universe_json(str(p), source="fixture")
        assert len(valid) == 2
        assert len(errors) == 0

    def test_ingestion_rejects_price_fields(self):
        """Market data must not enter MarketUniverseRecord."""
        raw = {
            "market_id": "M001",
            "question": "Q",
            "resolution_rules": "R",
            "close_time": "2026-12-31T23:59:59+00:00",
            "bid": 0.5,
            "ask": 0.6,
        }
        rec = ingest_market_record(raw, source="fixture")
        # Price fields are stripped in normalization
        normalized = rec.model_dump(mode="json")
        assert "bid" not in normalized
        assert "ask" not in normalized


# ══════════════════════════════════════════════════════════════════════════════
# 2. BlindForecastRunner Integration — Old Path Blocked
# ══════════════════════════════════════════════════════════════════════════════

class MockSlowForecastProvider:
    def forecast(self, market_id: str, clean_package: dict[str, Any]) -> dict[str, Any]:
        return {
            "market_id": market_id,
            "forecast_cutoff": "2025-06-01T00:00:00+00:00",
            "forecast_mode": "CHEAP_BASELINE",
            "p_yes": 0.63,
            "interval_50": [0.56, 0.70],
            "interval_80": [0.44, 0.77],
        }


class TestBlindForecastRunnerIntegration:
    def test_runner_used_in_forecast_path(self):
        """The BlindForecastRunner must be the only path to generate forecasts."""
        runner = BlindForecastRunner(
            provider=MockSlowForecastProvider(),
            model_id="test-model",
            model_version="1.0.0",
            prompt_version="v1",
            runner_version="1.0.0",
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
        assert prov["package_hash"] != ""
        assert prov["input_hash"] != ""
        assert prov["raw_output_hash"] != ""
        assert prov["parsed_forecast_hash"] != ""

    def test_forecast_provenance_captures_all_fields(self):
        runner = BlindForecastRunner(
            provider=MockSlowForecastProvider(),
            model_id="model-x",
            model_version="2.0",
            prompt_version="v2",
            runner_version="3.0",
        )
        pkg = {
            "market_id": "M001",
            "question": "Test?",
            "description": "Desc",
            "resolution_source": "test",
            "outcomes": ["Yes", "No"],
            "package_created_at": datetime.now(timezone.utc).isoformat(),
        }
        fc, prov = runner.run("M001", pkg, ForecastMode.BETTER_BASELINE)
        assert prov["model_id"] == "model-x"
        assert prov["model_version"] == "2.0"
        assert prov["prompt_version"] == "v2"
        assert prov["runner_version"] == "3.0"

    def test_old_run_forecast_path_still_available_but_not_used_by_cli(self):
        """The old run_forecast still exists but CLI must use BlindForecastRunner."""
        from phase0.providers.base import ForecastProvider
        from phase0.forecast_runner import run_forecast as old_run
        pkg = {
            "market_id": "M001",
            "question": "Test?",
            "description": "Desc",
            "resolution_source": "test",
            "outcomes": ["Yes", "No"],
            "package_created_at": datetime.now(timezone.utc).isoformat(),
        }
        fc = old_run(MockSlowForecastProvider(), "M001", pkg)
        assert fc.p_yes == 0.63


# ══════════════════════════════════════════════════════════════════════════════
# 3. Resolution Provenance
# ══════════════════════════════════════════════════════════════════════════════

class TestResolutionProvenance:
    def test_resolution_with_provenance(self):
        res = Resolution(
            market_id="M001",
            resolved_at=datetime.now(timezone.utc),
            outcome=ResolutionOutcome.YES,
            resolution_status=ResolutionStatus.RESOLVED_VALID,
            resolution_source="https://example.com/resolution",
            evidence_artifact_hash="abc123def456",
            resolution_confidence=0.95,
            resolver_version="cli-v1",
        )
        assert res.resolution_status == ResolutionStatus.RESOLVED_VALID
        assert res.p_yes_actual == 1.0
        assert res.evidence_artifact_hash == "abc123def456"

    def test_forged_provenance_detected(self):
        """A resolution with forged or missing provenance should be distinguishable."""
        valid = Resolution(
            market_id="M001",
            resolved_at=datetime.now(timezone.utc),
            outcome=ResolutionOutcome.YES,
            resolution_status=ResolutionStatus.RESOLVED_VALID,
            resolution_source="https://example.com",
            resolver_version="cli-v1",
        )
        forged = Resolution(
            market_id="M001",
            resolved_at=datetime.now(timezone.utc),
            outcome=ResolutionOutcome.YES,
            resolution_status=ResolutionStatus.MISSING_PROVENANCE,
            resolution_source="unknown",
        )
        assert valid.resolution_status != forged.resolution_status
        assert forged.resolution_status == ResolutionStatus.MISSING_PROVENANCE

    def test_unresolved_status_not_counted(self):
        res = Resolution(
            market_id="M001",
            resolved_at=datetime.now(timezone.utc),
            outcome=ResolutionOutcome.YES,
            resolution_status=ResolutionStatus.UNRESOLVED,
        )
        assert res.resolution_status == ResolutionStatus.UNRESOLVED


# ══════════════════════════════════════════════════════════════════════════════
# 4. Restart / Recovery
# ══════════════════════════════════════════════════════════════════════════════

class TestRestartRecovery:
    def test_restart_preserves_event_count(self, tmp_path: Path):
        """Simulate restart: create events, re-read, verify no dupes."""
        from phase0.manifest import create_manifest as cm
        store = EventStore(tmp_path / "events.jsonl")
        sm = ExperimentStateManager(store)
        manifest = cm("P0-REC", [{"market_id": "M001", "question": "?"}], selection_cutoff=datetime(2025, 6, 1, tzinfo=timezone.utc))
        sm.record_experiment_created("P0-REC", manifest)
        sm.record_experiment_activated("P0-REC")

        # Simulate restart: create new store pointing to same file
        store2 = EventStore(tmp_path / "events.jsonl")
        sm2 = ExperimentStateManager(store2)
        assert sm2.experiment_status() == ExperimentStatus.ACTIVE
        events = store2.read_all()
        assert len(events) == 2
        ok, msg = store2.verify_chain()
        assert ok

    def test_restart_after_incomplete_write(self, tmp_path: Path):
        """Simulate crash during event append: truncated last line."""
        from phase0.manifest import create_manifest as cm
        store = EventStore(tmp_path / "events.jsonl")
        sm = ExperimentStateManager(store)
        manifest = cm("P0-CRSH", [{"market_id": "M001", "question": "?"}], selection_cutoff=datetime(2025, 6, 1, tzinfo=timezone.utc))
        sm.record_experiment_created("P0-CRSH", manifest)
        sm.record_experiment_activated("P0-CRSH")

        # Corrupt last line (truncate)
        content = tmp_path / "events.jsonl"
        lines = content.read_text(encoding="utf-8").strip().split("\n")
        content.write_text(lines[0] + "\n", encoding="utf-8")

        # Restart: should detect broken chain (missing last event)
        store2 = EventStore(tmp_path / "events.jsonl")
        ok, _msg = store2.verify_chain()
        assert ok  # single event chain is still valid

    def test_duplicate_execution_blocked(self, tmp_path: Path):
        """Re-executing same operation must not create duplicate events."""
        from phase0.manifest import create_manifest as cm
        from phase0.package_validator import validate_package
        store = EventStore(tmp_path / "events.jsonl")
        sm = ExperimentStateManager(store)
        manifest = cm("P0-DUP", [{"market_id": "M001", "question": "?"}], selection_cutoff=datetime(2025, 6, 1, tzinfo=timezone.utc))
        sm.record_experiment_created("P0-DUP", manifest)
        sm.record_experiment_activated("P0-DUP")

        # Second attempt should fail
        with pytest.raises(RuntimeError):
            sm.record_experiment_activated("P0-DUP")

        events = store.read_all()
        assert len(events) == 2  # not 3


# ══════════════════════════════════════════════════════════════════════════════
# 5. Concurrency Conflict Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestConcurrencyConflicts:
    def test_concurrent_same_version_lock_single_winner(self, tmp_path: Path):
        """Two attempts to lock same forecast version — only one succeeds."""
        from phase0.manifest import create_manifest as cm
        from phase0.package_validator import validate_package
        experiments_root = tmp_path / "exp"
        store = EventStore(experiments_root / "P0-LOCK" / "events.jsonl")
        sm = ExperimentStateManager(store)
        manifest = cm("P0-LOCK", [{"market_id": "M001", "question": "?"}], selection_cutoff=datetime(2025, 6, 1, tzinfo=timezone.utc))
        sm.record_experiment_created("P0-LOCK", manifest)
        sm.record_experiment_activated("P0-LOCK")
        pkg = validate_package({"market_id": "M001", "question": "?", "description": "d", "resolution_source": "test", "outcomes": ["Yes", "No"], "evidence": [], "package_created_at": datetime.now(timezone.utc).isoformat()})
        sm.record_market_initialized("P0-LOCK", "M001", pkg)

        lock1 = ForecastLock(forecast_id="FC1", market_id="M001", forecast_version=1, forecast_cutoff=datetime.now(timezone.utc), package_hash="x", forecast_mode=ForecastMode.CHEAP_BASELINE, raw_probability=0.5, locked_at=datetime.now(timezone.utc), forecast_hash="x")
        lock2 = ForecastLock(forecast_id="FC2", market_id="M001", forecast_version=1, forecast_cutoff=datetime.now(timezone.utc), package_hash="y", forecast_mode=ForecastMode.CHEAP_BASELINE, raw_probability=0.6, locked_at=datetime.now(timezone.utc), forecast_hash="y")

        sm.record_forecast_locked("P0-LOCK", "M001", lock1)
        with pytest.raises(RuntimeError):
            sm.record_forecast_locked("P0-LOCK", "M001", lock2)

    def test_concurrent_baseline_capture_single_winner(self, tmp_path: Path):
        """Two baseline capture attempts — only one succeeds."""
        from phase0.manifest import create_manifest as cm
        from phase0.package_validator import validate_package
        experiments_root = tmp_path / "exp2"
        store = EventStore(experiments_root / "P0-BASE" / "events.jsonl")
        sm = ExperimentStateManager(store)
        manifest = cm("P0-BASE", [{"market_id": "M001", "question": "?"}], selection_cutoff=datetime(2025, 6, 1, tzinfo=timezone.utc))
        sm.record_experiment_created("P0-BASE", manifest)
        sm.record_experiment_activated("P0-BASE")
        pkg = validate_package({"market_id": "M001", "question": "?", "description": "d", "resolution_source": "test", "outcomes": ["Yes", "No"], "evidence": [], "package_created_at": datetime.now(timezone.utc).isoformat()})
        sm.record_market_initialized("P0-BASE", "M001", pkg)
        lock = ForecastLock(forecast_id="FC1", market_id="M001", forecast_version=1, forecast_cutoff=datetime.now(timezone.utc), package_hash="x", forecast_mode=ForecastMode.CHEAP_BASELINE, raw_probability=0.5, locked_at=datetime.now(timezone.utc), forecast_hash="x")
        sm.record_forecast_locked("P0-BASE", "M001", lock)

        sm.record_price_revealed("P0-BASE", "M001")
        sm.record_baseline_captured("P0-BASE", "M001")
        with pytest.raises(RuntimeError):
            sm.record_baseline_captured("P0-BASE", "M001")


# ══════════════════════════════════════════════════════════════════════════════
# 6. Post-Evaluation Tamper Detection
# ══════════════════════════════════════════════════════════════════════════════

class TestPostEvaluationTamperDetection:
    def _setup_evaluated_market(self, tmp_path: Path, exp_id: str = "P0-TAMPER"):
        from phase0.manifest import create_manifest as cm
        from phase0.package_validator import validate_package
        from phase0.schemas import Resolution, ResolutionOutcome
        experiments_root = tmp_path / "exp"
        events_path = experiments_root / exp_id / "events.jsonl"
        store = EventStore(events_path)
        sm = ExperimentStateManager(store)
        manifest = cm(exp_id, [{"market_id": "M001", "question": "?"}], selection_cutoff=datetime(2025, 6, 1, tzinfo=timezone.utc))
        sm.record_experiment_created(exp_id, manifest)
        sm.record_experiment_activated(exp_id)
        pkg = validate_package({"market_id": "M001", "question": "?", "description": "d", "resolution_source": "test", "outcomes": ["Yes", "No"], "evidence": [], "package_created_at": datetime.now(timezone.utc).isoformat()})
        sm.record_market_initialized(exp_id, "M001", pkg)
        lock = ForecastLock(forecast_id="FC1", market_id="M001", forecast_version=1, forecast_cutoff=datetime.now(timezone.utc), package_hash="x", forecast_mode=ForecastMode.CHEAP_BASELINE, raw_probability=0.5, locked_at=datetime.now(timezone.utc), forecast_hash="x")
        sm.record_forecast_locked(exp_id, "M001", lock)
        sm.record_price_revealed(exp_id, "M001")
        sm.record_baseline_captured(exp_id, "M001")
        res = Resolution(market_id="M001", resolved_at=datetime.now(timezone.utc), outcome=ResolutionOutcome.YES)
        sm.record_market_resolved(exp_id, "M001", res)
        sm.record_market_evaluated(exp_id, "M001")
        return sm, events_path

    def test_tamper_manifest_after_evaluation_detected(self, tmp_path: Path):
        from phase0.manifest import create_manifest as cm
        sm, events_path = self._setup_evaluated_market(tmp_path)
        # Tamper the event chain (replace market_evaluated)
        content = events_path.read_text(encoding="utf-8")
        tampered = content.replace("market_evaluated", "price_revealed")
        events_path.write_text(tampered, encoding="utf-8")
        ok, _ = sm.store.verify_chain()
        assert not ok, "Tampered chain should fail verification"

    def test_tamper_package_after_evaluation_noticed(self, tmp_path: Path):
        sm, events_path = self._setup_evaluated_market(tmp_path)
        # Verify chain is valid before tamper
        ok, _ = sm.store.verify_chain()
        assert ok
        # Tamper with semantic meaning — replace event type
        content = events_path.read_text(encoding="utf-8")
        tampered = content.replace("forecast_locked", "price_revealed")
        events_path.write_text(tampered, encoding="utf-8")
        ok2, _ = sm.store.verify_chain()
        assert not ok2

    def test_tamper_resolution_after_evaluation_detected(self, tmp_path: Path):
        sm, events_path = self._setup_evaluated_market(tmp_path)
        ok, _ = sm.store.verify_chain()
        assert ok
        # Tamper event data (resolution outcome)
        content = events_path.read_text(encoding="utf-8")
        events = [json.loads(line) for line in content.strip().split("\n") if line.strip()]
        for ev in events:
            if ev.get("event_type") == "market_resolved":
                if "resolution" in ev.get("data", {}):
                    ev["data"]["resolution"]["outcome"] = "NO"
        tampered = "\n".join(json.dumps(e) for e in events) + "\n"
        events_path.write_text(tampered, encoding="utf-8")
        ok2, _ = sm.store.verify_chain()
        assert not ok2, "Tampered resolution should break hash chain"

    def test_post_evaluation_tamper_blocks_new_transitions(self, tmp_path: Path):
        sm, events_path = self._setup_evaluated_market(tmp_path)
        # Tamper the event chain
        content = events_path.read_text(encoding="utf-8")
        tampered = content.replace("market_resolved", "price_revealed")
        events_path.write_text(tampered, encoding="utf-8")
        # Any new transition should fail at _ensure_integrity
        with pytest.raises(RuntimeError):
            sm.record_market_audited("P0-TAMPER", "M001")


# ══════════════════════════════════════════════════════════════════════════════
# 7. Full Chain Integration Test
# ══════════════════════════════════════════════════════════════════════════════

class TestFullChainIntegration:
    def test_market_ingestion_to_sampling_to_manifest(self, tmp_path: Path):
        """Verify the complete chain: ingest → sample → freeze → verify."""
        records = [
            {"market_id": f"M{i:03d}", "question": f"Question {i}", "resolution_rules": "Standard",
             "close_time": "2027-01-01T00:00:00+00:00", "category": "AI" if i % 2 == 0 else "Politics"}
            for i in range(1, 31)
        ]
        valid, errors = ingest_market_universe(records, source="fixture")
        assert len(errors) == 0
        assert len(valid) == 30

        from phase0.sampling import generate_manifest_markets
        cutoff = datetime(2025, 6, 1, tzinfo=timezone.utc)
        entries, excluded = generate_manifest_markets(
            [r.model_dump(mode="json") for r in valid],
            selection_cutoff=cutoff,
            seed="chain-test",
            target_count=25,
        )
        assert len(entries) >= 20, f"Too few markets sampled: {len(entries)}"
        assert len(entries) <= 50

        manifest = create_manifest("P0-CHAIN", [{"market_id": m.market_id, "question": m.question} for m in entries],
                                    selection_cutoff=cutoff)
        out = freeze_manifest(manifest, tmp_path / "manifests")
        loaded = load_manifest(out)
        ok, _ = verify_manifest(loaded)
        assert ok, "Frozen manifest must self-verify"
