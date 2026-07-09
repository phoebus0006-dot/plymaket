from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from phase0.manifest import create_manifest
from phase0.package_validator import validate_package
from phase0.schemas import Resolution, ResolutionOutcome
from phase0.state import (
    EventStore,
    ExperimentStateManager,
    ExperimentStatus,
    MarketStatus,
)


def _make_manifest(experiment_id: str = "P0-TEST"):
    return create_manifest(
        experiment_id=experiment_id,
        markets=[{"market_id": "M001", "question": "Test?"}],
        selection_cutoff=datetime(2025, 6, 1, tzinfo=timezone.utc),
    )


def _make_pkg(market_id: str = "M001") -> dict:
    return {
        "market_id": market_id,
        "question": "Test?",
        "description": "Desc",
        "resolution_source": "https://example.com",
        "outcomes": ["Yes", "No"],
        "evidence": [],
        "package_created_at": datetime.now(timezone.utc).isoformat(),
    }


def _sm(tmp_path: Path, exp_id: str = "P0-TEST") -> ExperimentStateManager:
    store = EventStore(tmp_path / "events.jsonl")
    return ExperimentStateManager(store)


class TestEventStore:
    def test_initialize_and_read(self, tmp_path: Path):
        sm = _sm(tmp_path)
        manifest = _make_manifest()
        sm.record_experiment_created("P0-TEST", manifest)
        assert sm.experiment_status() == ExperimentStatus.CREATED

    def test_double_initialize_raises(self, tmp_path: Path):
        sm = _sm(tmp_path)
        manifest = _make_manifest()
        sm.record_experiment_created("P0-TEST", manifest)
        with pytest.raises(RuntimeError):
            sm.record_experiment_created("P0-TEST", manifest)

    def test_no_state_returns_none(self, tmp_path: Path):
        sm = _sm(tmp_path, "P0-NONEXIST")
        assert sm.experiment_status() is None

    def test_experiment_transition(self, tmp_path: Path):
        sm = _sm(tmp_path)
        manifest = _make_manifest()
        sm.record_experiment_created("P0-TEST", manifest)
        sm.record_experiment_activated("P0-TEST")
        sm.record_experiment_completed("P0-TEST")
        assert sm.experiment_status() == ExperimentStatus.COMPLETE

    def test_market_lifecycle(self, tmp_path: Path):
        sm = _sm(tmp_path)
        manifest = _make_manifest()
        sm.record_experiment_created("P0-TEST", manifest)
        sm.record_experiment_activated("P0-TEST")

        pkg = _make_pkg("M001")
        clean = validate_package(pkg)
        sm.record_market_initialized("P0-TEST", "M001", clean)
        assert sm.market_status("M001") == MarketStatus.PACKAGE_READY

    def test_multi_market_independent_lifecycle(self, tmp_path: Path):
        sm = _sm(tmp_path)
        manifest = create_manifest(
            "P0-TEST",
            [{"market_id": "M001", "question": "Q1"}, {"market_id": "M002", "question": "Q2"}],
            selection_cutoff=datetime(2025, 6, 1, tzinfo=timezone.utc),
        )
        sm.record_experiment_created("P0-TEST", manifest)
        sm.record_experiment_activated("P0-TEST")

        pkg1 = validate_package(_make_pkg("M001"))
        pkg2 = validate_package(_make_pkg("M002"))
        sm.record_market_initialized("P0-TEST", "M001", pkg1)
        sm.record_market_initialized("P0-TEST", "M002", pkg2)

        assert sm.market_status("M001") == MarketStatus.PACKAGE_READY
        assert sm.market_status("M002") == MarketStatus.PACKAGE_READY
        assert sm.experiment_status() == ExperimentStatus.ACTIVE

    def test_illegal_experiment_transition_blocked(self, tmp_path: Path):
        sm = _sm(tmp_path)
        manifest = _make_manifest()
        sm.record_experiment_created("P0-TEST", manifest)
        sm.record_experiment_activated("P0-TEST")
        with pytest.raises(RuntimeError):
            sm.record_experiment_created("P0-TEST", manifest)

    def test_illegal_market_transition_blocked(self, tmp_path: Path):
        sm = _sm(tmp_path)
        manifest = _make_manifest()
        sm.record_experiment_created("P0-TEST", manifest)
        sm.record_experiment_activated("P0-TEST")
        pkg = validate_package(_make_pkg("M001"))
        sm.record_market_initialized("P0-TEST", "M001", pkg)
        with pytest.raises(RuntimeError):
            sm.record_price_revealed("P0-TEST", "M001")

    def test_market_state_independent_of_experiment(self, tmp_path: Path):
        sm = _sm(tmp_path)
        manifest = _make_manifest()
        sm.record_experiment_created("P0-TEST", manifest)
        sm.record_experiment_activated("P0-TEST")
        pkg = validate_package(_make_pkg("M001"))
        sm.record_market_initialized("P0-TEST", "M001", pkg)
        assert sm.market_status("M001") == MarketStatus.PACKAGE_READY
        assert sm.experiment_status() == ExperimentStatus.ACTIVE


class TestEventChainIntegrity:
    def test_event_tamper_detected(self, tmp_path: Path):
        sm = _sm(tmp_path)
        manifest = _make_manifest()
        sm.record_experiment_created("P0-TEST", manifest)
        sm.record_experiment_activated("P0-TEST")

        events_path = tmp_path / "events.jsonl"
        content = events_path.read_text(encoding="utf-8")
        tampered = content.replace("experiment_activated", "experiment_completed")
        events_path.write_text(tampered, encoding="utf-8")

        ok, msg = sm.store.verify_chain()
        assert not ok

    def test_event_delete_detected(self, tmp_path: Path):
        sm = _sm(tmp_path)
        manifest = _make_manifest()
        sm.record_experiment_created("P0-TEST", manifest)
        sm.record_experiment_activated("P0-TEST")
        sm.record_experiment_completed("P0-TEST")

        events_path = tmp_path / "events.jsonl"
        lines = events_path.read_text(encoding="utf-8").strip().split("\n")
        events_path.write_text(lines[0] + "\n" + lines[2] + "\n", encoding="utf-8")

        ok, msg = sm.store.verify_chain()
        assert not ok
        assert "previous_event_hash" in msg or "sequence error" in msg

    def test_verify_chain_empty_file(self, tmp_path: Path):
        store = EventStore(tmp_path / "empty.jsonl")
        ok, msg = store.verify_chain()
        assert ok
        assert "empty chain" in msg

    def test_chain_verification_detects_tamper(self, tmp_path: Path):
        sm = _sm(tmp_path)
        manifest = _make_manifest()
        sm.record_experiment_created("P0-TEST", manifest)
        sm.record_experiment_activated("P0-TEST")
        pkg = validate_package(_make_pkg("M001"))
        sm.record_market_initialized("P0-TEST", "M001", pkg)

        events_path = tmp_path / "events.jsonl"
        content = events_path.read_text(encoding="utf-8")
        tampered = content.replace("market_initialized", "price_revealed")
        events_path.write_text(tampered, encoding="utf-8")

        ok, msg = sm.store.verify_chain()
        assert not ok
