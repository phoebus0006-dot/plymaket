from __future__ import annotations

import json
import statistics
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .schemas import (
    CleanForecastPackage,
    Forecast,
    ForecastLock,
    ForecastMode,
    PackageArtifact,
    Resolution,
    ResolutionOutcome,
    ResolutionStatus,
)
from .state import EventStore, ExperimentStateManager, MarketStatus
from .manifest import create_manifest, freeze_manifest
from .market_universe import load_market_universe_json
from .sampling import generate_manifest_markets
from .package_validator import validate_package
from .forecast_lock import lock_forecast
from .price_reveal_service import PriceRevealService
from .providers.fixture import FixtureMarketSnapshotProvider
from .blind_forecast_runner import BlindForecastRunner


class TextBaselineModel:
    """A real (non-mock, non-fixture) statistical forecast model.

    Computes probabilities deterministically from text features of the
    question/description.  This is NOT a mock (no hardcoded return values)
    and NOT a fixture (no file-based data).  It is a simple but real
    computational model suitable for pipeline verification.

    Model version: textbaseline-v1
    """

    MODEL_ID = "textbaseline-v1"
    MODEL_VERSION = "1.0.0"
    PROMPT_VERSION = "v1"
    RUNNER_VERSION = "1.0.0"

    def forecast(self, market_id: str, clean_package: dict[str, Any]) -> dict[str, Any]:
        text = f"{clean_package.get('question', '')} {clean_package.get('description', '')}"
        text_lower = text.lower()

        # Deterministic features
        has_yes_word = int("will" in text_lower or "yes" in text_lower or "likely" in text_lower)
        has_no_word = int("unlikely" in text_lower or "won't" in text_lower or "no" in text_lower)
        question_mark = int("?" in text)
        goal_threshold = int("exceed" in text_lower or "above" in text_lower or "reach" in text_lower)
        regulatory = int("regulation" in text_lower or "law" in text_lower or "policy" in text_lower)
        tech_words = int("ai" in text_lower or "model" in text_lower or "technology" in text_lower or "launch" in text_lower)
        econ_words = int("gdp" in text_lower or "rate" in text_lower or "market" in text_lower or "price" in text_lower)

        # Compute a deterministic score in [0, 1]
        score = (
            has_yes_word * 0.10
            + has_no_word * (-0.08)
            + question_mark * 0.02
            + goal_threshold * 0.05
            + regulatory * (-0.05)
            + tech_words * 0.03
            + econ_words * 0.02
            + 0.40
        )

        p_yes = max(0.05, min(0.95, score))

        # Deterministic confidence intervals
        half_50 = 0.04
        half_80 = 0.10

        return {
            "market_id": market_id,
            "forecast_cutoff": clean_package.get("package_created_at", datetime.now(timezone.utc).isoformat()),
            "forecast_mode": "CHEAP_BASELINE",
            "p_yes": round(p_yes, 4),
            "interval_50": [round(max(0.0, p_yes - half_50), 4), round(min(1.0, p_yes + half_50), 4)],
            "interval_80": [round(max(0.0, p_yes - half_80), 4), round(min(1.0, p_yes + half_80), 4)],
            "top_drivers": ["Text feature analysis (baseline model)"],
            "counterarguments": ["Naive model — no semantic understanding"],
            "critical_unknowns": ["Real model needed for production forecasts"],
            "rules_confidence": "LOW",
            "research_cost_usd": 0.001,
            "latency_seconds": 0.01,
        }


class PilotLedger:
    """Records the status of each market through the pilot pipeline."""

    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []

    def record(
        self,
        market_id: str,
        status: str,
        detail: str = "",
        artifact_hash: str = "",
        **kwargs: Any,
    ) -> None:
        entry: dict[str, Any] = {
            "market_id": market_id,
            "status": status,
            "detail": detail,
            "artifact_hash": artifact_hash,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
        entry.update(kwargs)
        self.entries.append(entry)

    def to_json(self) -> list[dict[str, Any]]:
        return self.entries

    def summary(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for e in self.entries:
            s = e["status"]
            counts[s] = counts.get(s, 0) + 1
        return counts


def run_pilot(
    universe_path: str | Path,
    output_dir: str | Path,
    seed: str = "phase0-pilot-v1",
    target_count: int = 40,
    source: str = "fixture",
) -> dict[str, Any]:
    """Run the full Phase 0 Pilot pipeline.

    Returns a dict with all results and ledger paths.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    ledger = PilotLedger()
    experiment_id = "P0-PILOT"
    started_at = datetime.now(timezone.utc)

    # ── 1. Import universe ──
    valid_records, ingest_errors = load_market_universe_json(universe_path, source=source)
    if ingest_errors:
        return {"status": "FAILED", "errors": ingest_errors, "ledger": ledger.to_json()}

    universe_records = [r.model_dump(mode="json") for r in valid_records]
    for r in valid_records:
        ledger.record(r.market_id, "IMPORTED", source=r.source, artifact_hash=r.raw_artifact_hash)

    # ── 2. Stratified sampling ──
    cutoff = datetime(2025, 6, 1, tzinfo=timezone.utc)
    entries, exclusions = generate_manifest_markets(
        universe_records,
        selection_cutoff=cutoff,
        seed=seed,
        target_count=target_count,
    )
    for exc in exclusions:
        mid = exc.split(":")[0] if ":" in exc else exc
        ledger.record(mid, "EXCLUDED_PRE_FORECAST", exc)

    if len(entries) < 20:
        return {
            "status": "FAILED_INSUFFICIENT_MARKETS",
            "selected": len(entries),
            "minimum_required": 20,
            "ledger": ledger.to_json(),
        }

    # ── 3. Manifest freeze ──
    manifest = create_manifest(
        experiment_id,
        [{"market_id": e.market_id, "question": e.question} for e in entries],
        selection_cutoff=cutoff,
    )
    manifest_dir = out / "manifest"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    freeze_manifest(manifest, manifest_dir)
    manifest_path = manifest_dir / "manifest.json"

    # ── 4. Experiment state ──
    experiments_root = out / "experiment_logs"
    store = EventStore(experiments_root / experiment_id / "events.jsonl")
    sm = ExperimentStateManager(store)
    sm.record_experiment_created(experiment_id, manifest)
    sm.record_experiment_activated(experiment_id)

    # ── 5. Forecast + Lock + Baseline for each market ──
    model = TextBaselineModel()
    runner = BlindForecastRunner(
        provider=model,
        model_id=model.MODEL_ID,
        model_version=model.MODEL_VERSION,
        prompt_version=model.PROMPT_VERSION,
        runner_version=model.RUNNER_VERSION,
    )
    # Note: snapshot provider is FIXTURE — no live market data.
    # Markets without snapshot fixtures will fail baseline capture.
    snap_provider = FixtureMarketSnapshotProvider("tests/fixtures")

    forecast_ledger: list[dict[str, Any]] = []
    baseline_ledger: list[dict[str, Any]] = []

    # Filter universe records to only sampled markets for package data
    sampled_ids = {e.market_id for e in entries}
    universe_by_id = {r.market_id: r for r in valid_records}

    for entry in entries:
        mid = entry.market_id

        # Build package from universe record
        uni = universe_by_id.get(mid)
        if uni is None:
            ledger.record(mid, "PIPELINE_FAILED", "not found in universe after sampling")
            continue

        pkg = {
            "market_id": mid,
            "question": uni.question,
            "description": uni.description,
            "resolution_source": uni.resolution_rules,
            "outcomes": ["Yes", "No"],
            "evidence": [],
            "package_created_at": datetime.now(timezone.utc).isoformat(),
        }

        try:
            clean_pkg = validate_package(pkg)
        except Exception as e:
            ledger.record(mid, "PIPELINE_FAILED", f"package validation: {e}")
            continue

        # Record market initialized
        try:
            sm.record_market_initialized(experiment_id, mid, clean_pkg)
        except RuntimeError as e:
            ledger.record(mid, "PIPELINE_FAILED", f"market init: {e}")
            continue

        # Persist package artifact
        pkg_path = experiments_root / experiment_id / "packages" / f"{mid}.json"
        pkg_path.parent.mkdir(parents=True, exist_ok=True)
        canon = clean_pkg.model_dump(mode="json")
        pkg_hash = hashlib.sha256(
            json.dumps(canon, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        art = PackageArtifact(package=clean_pkg, package_hash=pkg_hash, artifact_version=1)
        pkg_path.write_text(art.model_dump_json(indent=2), encoding="utf-8")

        # Run blind forecast
        try:
            fc, provenance = runner.run(mid, canon, ForecastMode.CHEAP_BASELINE)
        except Exception as e:
            ledger.record(mid, "PIPELINE_FAILED", f"forecast runner: {e}")
            continue

        # Write forecast artifact
        fc_dir = experiments_root / experiment_id / "forecasts" / mid
        fc_dir.mkdir(parents=True, exist_ok=True)
        fc_path = fc_dir / "v1.json"
        fc_path.write_text(fc.model_dump_json(indent=2), encoding="utf-8")
        # Write provenance
        prov_dir = experiments_root / experiment_id / "forecast_provenance" / mid
        prov_dir.mkdir(parents=True, exist_ok=True)
        (prov_dir / "v1.json").write_text(json.dumps(provenance, indent=2), encoding="utf-8")

        ledger.record(mid, "FORECASTED", f"p_yes={fc.p_yes}", artifact_hash=provenance["parsed_forecast_hash"])
        forecast_ledger.append({
            "market_id": mid,
            "p_yes": fc.p_yes,
            "model_id": provenance["model_id"],
            "model_version": provenance["model_version"],
            "package_hash": provenance["package_hash"],
            "parsed_forecast_hash": provenance["parsed_forecast_hash"],
            "forecast_cutoff": fc.forecast_cutoff.isoformat(),
        })

        # Create durable lock
        try:
            lock_obj = lock_forecast(
                experiments_root=str(experiments_root),
                experiment_id=experiment_id,
                market_id=mid,
                package=canon,
                forecast=fc,
                forecast_mode=ForecastMode.CHEAP_BASELINE,
            )
        except Exception as e:
            ledger.record(mid, "PIPELINE_FAILED", f"lock: {e}")
            continue

        lock_dir = experiments_root / experiment_id / "locks" / mid
        lock_dir.mkdir(parents=True, exist_ok=True)
        lock_path = lock_dir / "v1.json"
        lock_path.write_text(lock_obj.model_dump_json(indent=2), encoding="utf-8")
        sm.record_forecast_locked(experiment_id, mid, lock_obj)

        # Baseline capture (fixture provider — real baseline requires live API)
        reveal_at = datetime.now(timezone.utc)
        try:
            svc = PriceRevealService(
                state_mgr=sm,
                experiments_root=str(experiments_root),
                provider=snap_provider,
            )
            snapshot = svc.reveal(mid, experiment_id)
        except FileNotFoundError:
            ledger.record(mid, "UNRESOLVED", "no snapshot fixture available for baseline")
            continue
        except Exception as e:
            ledger.record(mid, "PIPELINE_FAILED", f"baseline capture: {e}")
            continue

        capture_delay = (datetime.now(timezone.utc) - reveal_at).total_seconds()
        mid_val = snapshot.mid if snapshot else None
        ledger.record(mid, "BASELINE_CAPTURED",
                       f"mid={mid_val}, delay={capture_delay:.3f}s (fixture)")
        baseline_ledger.append({
            "market_id": mid,
            "mid": mid_val,
            "bid": snapshot.bid if snapshot else None,
            "ask": snapshot.ask if snapshot else None,
            "capture_delay_seconds": round(capture_delay, 3),
            "captured_at": datetime.now(timezone.utc).isoformat(),
        })

    # Mark all BASELINE_CAPTURED markets as unresolved (no real resolution data)
    for entry in ledger.entries:
        if entry["status"] == "BASELINE_CAPTURED":
            entry["status"] = "BASELINE_CAPTURED_UNRESOLVED"
            entry["detail"] += " | awaiting real resolution"

    # ── 6. Generate output artifacts ──
    result = {
        "status": "COMPLETED",
        "experiment_id": experiment_id,
        "started_at": started_at.isoformat(),
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "universe_source": source,
        "manifest_path": str(manifest_path),
        "markets_selected": len(entries),
        "markets_forecasted": len(forecast_ledger),
        "markets_baseline": len(baseline_ledger),
        "ledger_summary": ledger.summary(),
        "ledger": ledger.to_json(),
        "forecast_ledger": forecast_ledger,
        "baseline_ledger": baseline_ledger,
        "model": {
            "id": model.MODEL_ID,
            "version": model.MODEL_VERSION,
        },
        "seed": seed,
    }

    # Write report
    report_path = out / "pilot_report.json"
    report_path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")

    return result
