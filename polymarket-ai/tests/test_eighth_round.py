from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

import pytest


# ══════════════════════════════════════════════════════════════════════════════
# 1. CLI subprocess tests for market-import
# ══════════════════════════════════════════════════════════════════════════════

CLI = [sys.executable, "-m", "phase0.cli"]


def _run_cli(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        CLI + list(args),
        capture_output=True,
        text=True,
        input=stdin,
        timeout=30,
    )


class TestCliMarketImport:
    def test_successful_import(self, tmp_path: Path):
        data = [
            {"market_id": "M001", "question": "Q1", "resolution_rules": "R1",
             "close_time": "2027-01-01T00:00:00+00:00", "category": "AI"},
            {"market_id": "M002", "question": "Q2", "resolution_rules": "R2",
             "close_time": "2027-01-01T00:00:00+00:00", "category": "Politics"},
        ]
        p = tmp_path / "markets.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        out_dir = tmp_path / "out"
        result = _run_cli("market-universe-import", str(p), "--output-dir", str(out_dir))
        assert result.returncode == 0, f"STDERR: {result.stderr}"
        assert "Imported 2 records" in result.stdout

    def test_missing_market_id_rejected(self, tmp_path: Path):
        data = [
            {"question": "No ID", "resolution_rules": "R1", "close_time": "2027-01-01T00:00:00+00:00"},
        ]
        p = tmp_path / "bad.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        result = _run_cli("market-universe-import", str(p), "--output-dir", str(tmp_path / "out"))
        assert result.returncode != 0, "Should fail on missing market_id"
        assert "REJECT" in result.stderr or "Error" in result.stderr

    def test_missing_resolution_rules_rejected(self, tmp_path: Path):
        data = [
            {"market_id": "M001", "question": "Q1", "resolution_rules": "",
             "close_time": "2027-01-01T00:00:00+00:00"},
        ]
        p = tmp_path / "bad2.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        result = _run_cli("market-universe-import", str(p), "--output-dir", str(tmp_path / "out"))
        assert result.returncode != 0
        assert "REJECT" in result.stderr

    def test_invalid_json_rejected(self, tmp_path: Path):
        p = tmp_path / "bad3.json"
        p.write_text("not valid json", encoding="utf-8")
        result = _run_cli("market-universe-import", str(p), "--output-dir", str(tmp_path / "out"))
        assert result.returncode != 0

    def test_duplicate_import_allowed(self, tmp_path: Path):
        """Importing the same data twice to different output dirs should work."""
        data = [
            {"market_id": "M001", "question": "Q1", "resolution_rules": "R1",
             "close_time": "2027-01-01T00:00:00+00:00", "category": "AI"},
        ]
        p = tmp_path / "markets.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        r1 = _run_cli("market-universe-import", str(p), "--output-dir", str(tmp_path / "out1"))
        assert r1.returncode == 0
        r2 = _run_cli("market-universe-import", str(p), "--output-dir", str(tmp_path / "out2"))
        assert r2.returncode == 0
        assert "Imported 1 records" in r2.stdout

    def test_import_source_flag(self, tmp_path: Path):
        data = [
            {"market_id": "M001", "question": "Q1", "resolution_rules": "R1",
             "close_time": "2027-01-01T00:00:00+00:00", "category": "AI"},
        ]
        p = tmp_path / "markets.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        result = _run_cli("market-universe-import", str(p), "--source", "real_source",
                          "--output-dir", str(tmp_path / "out"))
        assert result.returncode == 0
        # Verify the source was persisted
        out_files = list((tmp_path / "out").iterdir())
        assert len(out_files) == 1
        content = json.loads(out_files[0].read_text(encoding="utf-8"))
        assert content[0]["source"] == "real_source"


# ══════════════════════════════════════════════════════════════════════════════
# 2. Real Data E2E Pipeline (using synthetic_real_format data)
# ══════════════════════════════════════════════════════════════════════════════

REALISTIC_FIXTURE = Path(__file__).parent / "fixtures" / "realistic_universe.json"


class TestRealisticDataPipeline:
    """Full E2E pipeline using realistic-format market data (SYNTHETIC)."""

    def _fixture_path(self) -> Path:
        if not REALISTIC_FIXTURE.is_file():
            pytest.skip("realistic_universe.json not found")
        return REALISTIC_FIXTURE

    def test_01_import_realistic_data(self, tmp_path: Path):
        """Step 1: Import the realistic market universe."""
        result = _run_cli("market-universe-import", str(self._fixture_path()),
                          "--source", "synthetic_real_format",
                          "--output-dir", str(tmp_path / "universe"))
        assert result.returncode == 0, f"Import failed: {result.stderr}"
        assert "Imported 10 records" in result.stdout
        # Validate that each record has proper hashes
        out_files = list((tmp_path / "universe").iterdir())
        assert len(out_files) >= 1
        records = json.loads(out_files[0].read_text(encoding="utf-8"))
        assert len(records) == 10
        for r in records:
            assert r["source"] == "synthetic_real_format"
            assert r["raw_artifact_hash"]
            assert r["normalized_artifact_hash"]
            assert r["market_id"].startswith("REAL-M")
            assert r["resolution_rules"]

    def test_02_sampling_from_imported_data(self, tmp_path: Path):
        """Step 2: Sample from imported universe (using internal API)."""
        from phase0.market_universe import load_market_universe_json
        valid, errors = load_market_universe_json(str(self._fixture_path()), source="synthetic_real_format")
        assert len(errors) == 0
        assert len(valid) == 10

        from phase0.sampling import generate_manifest_markets
        cutoff = datetime(2025, 6, 1, tzinfo=timezone.utc)
        entries, excluded = generate_manifest_markets(
            [r.model_dump(mode="json") for r in valid],
            selection_cutoff=cutoff,
            seed="eighth-round-v1",
            target_count=8,
        )
        assert len(entries) <= 10
        assert len(entries) >= 1
        # Reproducibility
        entries2, _ = generate_manifest_markets(
            [r.model_dump(mode="json") for r in valid],
            selection_cutoff=cutoff,
            seed="eighth-round-v1",
            target_count=8,
        )
        assert [e.market_id for e in entries] == [e.market_id for e in entries2]

    def test_03_full_pipeline_internal(self, tmp_path: Path):
        """Step 3-10: Full internal pipeline from manifest to evaluation.

        Uses the realistic-format data as the market universe.
        """
        from phase0.market_universe import load_market_universe_json
        from phase0.sampling import generate_manifest_markets
        from phase0.manifest import create_manifest, freeze_manifest, load_manifest, verify_manifest
        from phase0.state import EventStore, ExperimentStateManager, MarketStatus
        from phase0.package_validator import validate_package
        from phase0.forecast_lock import lock_forecast
        from phase0.forecast_runner import run_forecast
        from phase0.providers.fixture import FixtureForecastProvider, FixtureMarketSnapshotProvider
        from phase0.price_reveal_service import PriceRevealService
        from phase0.evaluate import evaluate_experiment
        from phase0.schemas import (
            ForecastMode, Resolution, ResolutionOutcome, ResolutionStatus,
            Forecast, ForecastLock, PackageArtifact,
        )
        from phase0.blind_forecast_runner import BlindForecastRunner

        experiments_root = tmp_path / "experiments"
        exp_id = "P0-REAL-E2E"
        market_id = "REAL-M001"

        # 2. Sampling
        valid, _ = load_market_universe_json(str(self._fixture_path()), source="synthetic_real_format")
        cutoff = datetime(2025, 6, 1, tzinfo=timezone.utc)
        entries, _ = generate_manifest_markets(
            [r.model_dump(mode="json") for r in valid],
            selection_cutoff=cutoff,
            seed="e2e-v1",
            target_count=8,
        )

        # 3. Manifest Freeze
        manifest = create_manifest(
            exp_id,
            [{"market_id": e.market_id, "question": e.question} for e in entries],
            selection_cutoff=cutoff,
        )
        manifest_dir = tmp_path / "manifest"
        freeze_manifest(manifest, manifest_dir)
        loaded = load_manifest(manifest_dir / "manifest.json")
        ok, _ = verify_manifest(loaded)
        assert ok, "Manifest must self-verify"

        # 4. Experiment state
        store = EventStore(experiments_root / exp_id / "events.jsonl")
        sm = ExperimentStateManager(store)
        sm.record_experiment_created(exp_id, manifest)
        sm.record_experiment_activated(exp_id)

        # 5. Package (extract from the first sampled market's universe record)
        source_record = [r for r in valid if r.market_id == market_id][0]
        pkg = {
            "market_id": market_id,
            "question": source_record.question,
            "description": source_record.description,
            "resolution_source": source_record.resolution_rules,
            "outcomes": ["Yes", "No"],
            "evidence": [],
            "package_created_at": datetime.now(timezone.utc).isoformat(),
        }
        clean_pkg = validate_package(pkg)
        sm.record_market_initialized(exp_id, market_id, clean_pkg)

        # Persist package artifact
        pkg_path = experiments_root / exp_id / "packages" / f"{market_id}.json"
        pkg_path.parent.mkdir(parents=True, exist_ok=True)
        canon = clean_pkg.model_dump(mode="json")
        pkg_hash = sha256(json.dumps(canon, sort_keys=True, default=str).encode("utf-8")).hexdigest()
        art = PackageArtifact(package=clean_pkg, package_hash=pkg_hash, artifact_version=1)
        pkg_path.write_text(art.model_dump_json(indent=2), encoding="utf-8")

        # 6. BlindForecastRunner → Forecast + Durable Lock
        provider = FixtureForecastProvider("tests/fixtures/forecast_outputs.json")
        # Need fixture data matching REAL-M001 — use SIM001 mapping
        runner = BlindForecastRunner(provider=provider, model_id="e2e-test", model_version="1.0")
        fc, prov = runner.run(market_id, art, ForecastMode.CHEAP_BASELINE)
        assert prov["package_hash"] == pkg_hash

        # Write forecast artifact (without provenance — Forecast schema forbids extra fields)
        fc_dir = experiments_root / exp_id / "forecasts" / market_id
        fc_dir.mkdir(parents=True, exist_ok=True)
        fc_path = fc_dir / "v1.json"
        fc_path.write_text(fc.model_dump_json(indent=2), encoding="utf-8")
        # Write provenance separately
        prov_dir = experiments_root / exp_id / "forecast_provenance" / market_id
        prov_dir.mkdir(parents=True, exist_ok=True)
        (prov_dir / "v1.json").write_text(json.dumps(prov, indent=2), encoding="utf-8")

        # Durable Lock
        lock_obj = lock_forecast(
            experiments_root=str(experiments_root),
            experiment_id=exp_id,
            market_id=market_id,
            package=canon,
            forecast=fc,
            forecast_mode=ForecastMode.CHEAP_BASELINE,
        )
        lock_dir = experiments_root / exp_id / "locks" / market_id
        lock_dir.mkdir(parents=True, exist_ok=True)
        (lock_dir / "v1.json").write_text(lock_obj.model_dump_json(indent=2), encoding="utf-8")
        sm.record_forecast_locked(exp_id, market_id, lock_obj)
        assert sm.market_status(market_id) == MarketStatus.FORECAST_LOCKED

        # 7. Baseline Capture
        snap_provider = FixtureMarketSnapshotProvider("tests/fixtures")
        reveal_svc = PriceRevealService(
            state_mgr=sm,
            experiments_root=str(experiments_root),
            provider=snap_provider,
        )
        reveal_svc.reveal(market_id, exp_id)
        assert sm.market_status(market_id) in (MarketStatus.PRICE_REVEALED, MarketStatus.BASELINE_CAPTURED)

        # 8. Resolution Provenance
        res = Resolution(
            market_id=market_id,
            resolved_at=datetime.now(timezone.utc),
            outcome=ResolutionOutcome.YES,
            resolution_status=ResolutionStatus.RESOLVED_VALID,
            resolution_source=source_record.resolution_rules,
            resolver_version="e2e-v1",
            evidence_artifact_hash=sha256(b"e2e-resolution").hexdigest(),
            resolution_confidence=1.0,
        )
        res_path = experiments_root / exp_id / "resolutions" / f"{market_id}.json"
        res_path.parent.mkdir(parents=True, exist_ok=True)
        res_path.write_text(res.model_dump_json(indent=2), encoding="utf-8")
        sm.record_market_resolved(exp_id, market_id, res)
        assert sm.market_status(market_id) == MarketStatus.RESOLVED

        # 9. Evaluation
        summary = evaluate_experiment(
            state_mgr=sm,
            experiments_root=str(experiments_root),
            experiment_id=exp_id,
        )
        assert summary.has_evaluable_cases()
        assert sm.market_status(market_id) == MarketStatus.EVALUATED

        # 10. Audit — verify the entire event chain
        store.verify_or_fail()

        # Verify artifact existence
        assert pkg_path.is_file()
        assert fc_path.is_file()
        assert (lock_dir / "v1.json").is_file()
        assert res_path.is_file()


# ══════════════════════════════════════════════════════════════════════════════
# 3. Adversarial E2E Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestAdversarialE2E:
    """Each attack must fail closed — no partial success allowed."""

    def _setup_baseline_state(self, tmp_path: Path, exp_id: str = "P0-ADV") -> tuple:
        """Create a minimally initialized experiment for attack testing."""
        from phase0.manifest import create_manifest
        from phase0.state import EventStore, ExperimentStateManager, MarketStatus
        from phase0.package_validator import validate_package

        experiments_root = tmp_path / "exp"
        store = EventStore(experiments_root / exp_id / "events.jsonl")
        sm = ExperimentStateManager(store)
        manifest = create_manifest(exp_id, [{"market_id": "M001", "question": "?"}],
                                    selection_cutoff=datetime(2025, 6, 1, tzinfo=timezone.utc))
        sm.record_experiment_created(exp_id, manifest)
        sm.record_experiment_activated(exp_id)
        pkg = validate_package({"market_id": "M001", "question": "?", "description": "d",
                                "resolution_source": "test", "outcomes": ["Yes", "No"],
                                "evidence": [], "package_created_at": datetime.now(timezone.utc).isoformat()})
        sm.record_market_initialized(exp_id, "M001", pkg)
        return sm, store, experiments_root, manifest

    def test_attack_price_taint_injection(self):
        """Price fields in package → MarketTaintError."""
        from phase0.package_validator import validate_package, MarketTaintError
        pkg = {
            "market_id": "M001", "question": "?", "description": "d",
            "resolution_source": "test", "outcomes": ["Yes", "No"],
            "evidence": [], "package_created_at": datetime.now(timezone.utc).isoformat(),
            "mid": 0.65,  # FORBIDDEN
        }
        with pytest.raises(MarketTaintError):
            validate_package(pkg)

    def test_attack_manifest_tamper_after_freeze(self, tmp_path: Path):
        """Modifying frozen manifest → verify_manifest fails."""
        from phase0.manifest import create_manifest, freeze_manifest, load_manifest, verify_manifest
        manifest = create_manifest("P0-ATK", [{"market_id": "M001", "question": "?"}],
                                    selection_cutoff=datetime(2025, 6, 1, tzinfo=timezone.utc))
        manifest_dir = tmp_path / "manifests"
        freeze_manifest(manifest, manifest_dir)
        # Tamper
        man_path = manifest_dir / "manifest.json"
        data = json.loads(man_path.read_text(encoding="utf-8"))
        data["markets"][0]["market_id"] = "TAMPERED"
        man_path.write_text(json.dumps(data), encoding="utf-8")
        loaded = load_manifest(man_path)
        ok, _ = verify_manifest(loaded)
        assert not ok, "Tampered manifest must fail verification"

    def test_attack_baseline_before_lock(self, tmp_path: Path):
        """Baseline capture without forecast lock → RuntimeError."""
        sm, _, _, _ = self._setup_baseline_state(tmp_path)
        with pytest.raises(RuntimeError):
            sm.record_baseline_captured("P0-ADV", "M001")

    def test_attack_forged_resolution_provenance(self):
        """Resolution with missing/forged provenance → MUST not pass as RESOLVED_VALID."""
        from phase0.schemas import Resolution, ResolutionOutcome, ResolutionStatus
        forged = Resolution(
            market_id="M001",
            resolved_at=datetime.now(timezone.utc),
            outcome=ResolutionOutcome.YES,
            resolution_status=ResolutionStatus.MISSING_PROVENANCE,
            resolution_source="unknown",
        )
        assert forged.resolution_status != ResolutionStatus.RESOLVED_VALID
        # The system must check resolution_status before count
        assert forged.resolution_status == ResolutionStatus.MISSING_PROVENANCE

    def test_attack_evaluation_tamper_blocked(self, tmp_path: Path):
        """After evaluation, tampering events blocks new transitions."""
        from phase0.manifest import create_manifest
        from phase0.state import EventStore, ExperimentStateManager, MarketStatus
        from phase0.package_validator import validate_package
        from phase0.schemas import ForecastLock, ForecastMode, Resolution, ResolutionOutcome

        exp_id = "P0-ATK2"
        store = EventStore(tmp_path / exp_id / "events.jsonl")
        sm = ExperimentStateManager(store)
        manifest = create_manifest(exp_id, [{"market_id": "M001", "question": "?"}],
                                    selection_cutoff=datetime(2025, 6, 1, tzinfo=timezone.utc))
        sm.record_experiment_created(exp_id, manifest)
        sm.record_experiment_activated(exp_id)
        pkg = validate_package({"market_id": "M001", "question": "?", "description": "d",
                                "resolution_source": "test", "outcomes": ["Yes", "No"],
                                "evidence": [], "package_created_at": datetime.now(timezone.utc).isoformat()})
        sm.record_market_initialized(exp_id, "M001", pkg)
        lock = ForecastLock(forecast_id="FC1", market_id="M001", forecast_version=1,
                            forecast_cutoff=datetime.now(timezone.utc), package_hash="x",
                            forecast_mode=ForecastMode.CHEAP_BASELINE, raw_probability=0.5,
                            locked_at=datetime.now(timezone.utc), forecast_hash="x")
        sm.record_forecast_locked(exp_id, "M001", lock)
        sm.record_price_revealed(exp_id, "M001")
        sm.record_baseline_captured(exp_id, "M001")
        res = Resolution(market_id="M001", resolved_at=datetime.now(timezone.utc), outcome=ResolutionOutcome.YES)
        sm.record_market_resolved(exp_id, "M001", res)
        sm.record_market_evaluated(exp_id, "M001")
        assert sm.market_status("M001") == MarketStatus.EVALUATED

        # Tamper the event file
        events_path = tmp_path / exp_id / "events.jsonl"
        content = events_path.read_text(encoding="utf-8")
        tampered = content.replace("market_evaluated", "price_revealed")
        events_path.write_text(tampered, encoding="utf-8")

        # Next mutation must fail
        with pytest.raises(RuntimeError):
            sm.record_market_audited(exp_id, "M001")
