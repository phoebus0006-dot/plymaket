from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from phase0.evaluate import evaluate_experiment
from phase0.forecast_lock import lock_forecast
from phase0.manifest import create_manifest
from phase0.package_validator import validate_package
from phase0.schemas import (
    EvalResult,
    EvaluationSummary,
    Forecast,
    ForecastMode,
    Resolution,
    ResolutionOutcome,
)
from phase0.state import EventStore, ExperimentStateManager


def _fc(market_id: str, p_yes: float, cutoff=None) -> Forecast:
    return Forecast(
        market_id=market_id,
        forecast_cutoff=cutoff or datetime(2025, 6, 1, tzinfo=timezone.utc),
        forecast_mode="CHEAP_BASELINE",
        p_yes=p_yes,
        interval_50=[max(0.0, p_yes - 0.05), min(1.0, p_yes + 0.05)],
        interval_80=[max(0.0, p_yes - 0.15), min(1.0, p_yes + 0.15)],
    )


def _base_pkg(market_id: str) -> dict:
    return {
        "market_id": market_id,
        "question": "Test?",
        "description": "Desc",
        "resolution_source": "https://example.com",
        "outcomes": ["Yes", "No"],
        "evidence": [],
        "package_created_at": datetime.now(timezone.utc).isoformat(),
    }


def _setup_state_with_resolution(
    tmp_path: Path,
    forecasts: list[Forecast],
    resolutions: list[Resolution],
    snapshots: list[dict] | None = None,
) -> tuple[ExperimentStateManager, str]:
    """Create an experiment state with given forecasts and resolutions.

    Returns (state_mgr, experiments_root).
    """
    experiments_root = str(tmp_path / "experiments")
    exp_id = "P0-EVAL"

    markets = [{"market_id": f.market_id, "question": f"Q for {f.market_id}"} for f in forecasts]
    manifest = create_manifest(
        exp_id,
        markets,
        selection_cutoff=datetime(2025, 6, 1, tzinfo=timezone.utc),
    )
    store = EventStore(Path(experiments_root) / exp_id / "events.jsonl")
    sm = ExperimentStateManager(store)
    sm.record_experiment_created(exp_id, manifest)
    sm.record_experiment_activated(exp_id)

    snap_by_mid: dict[str, dict] = {}
    if snapshots:
        for s in snapshots:
            mid = s.get("market_id", "")
            if mid:
                snap_by_mid[mid] = s

    for fc in forecasts:
        mid = fc.market_id
        pkg = _base_pkg(mid)
        clean_pkg = validate_package(pkg)
        sm.record_market_initialized(exp_id, mid, clean_pkg)

        # Write forecast artifact
        fc_dir = Path(experiments_root) / exp_id / "forecasts" / mid
        fc_dir.mkdir(parents=True, exist_ok=True)
        (fc_dir / "v1.json").write_text(fc.model_dump_json(indent=2), encoding="utf-8")

        # Write package artifact
        pkg_path = Path(experiments_root) / exp_id / "packages" / f"{mid}.json"
        pkg_path.parent.mkdir(parents=True, exist_ok=True)
        pkg_path.write_text(json.dumps(pkg, default=str), encoding="utf-8")

        # Lock forecast
        lock_obj = lock_forecast(
            experiments_root=experiments_root,
            experiment_id=exp_id,
            market_id=mid,
            package=pkg,
            forecast=fc,
            forecast_mode=ForecastMode.CHEAP_BASELINE,
        )
        lock_dir = Path(experiments_root) / exp_id / "locks" / mid
        lock_dir.mkdir(parents=True, exist_ok=True)
        (lock_dir / "v1.json").write_text(lock_obj.model_dump_json(indent=2), encoding="utf-8")
        sm.record_forecast_locked(exp_id, mid, lock_obj)

        # Reveal if snapshot exists
        if mid in snap_by_mid:
            from phase0.schemas import PriceSnapshot
            snap_data = snap_by_mid[mid]
            sn = PriceSnapshot(
                market_id=mid,
                snapshot_timestamp=datetime.now(timezone.utc),
                bid=snap_data.get("bid"),
                ask=snap_data.get("ask"),
                mid=snap_data.get("mid"),
                spread=snap_data.get("spread"),
            )
            sm.record_price_revealed(exp_id, mid, snapshot=sn)
        else:
            sm.record_price_revealed(exp_id, mid)

    for res in resolutions:
        sm.record_market_resolved(exp_id, res.market_id, res)

    return sm, experiments_root


class TestEvaluate:
    def test_single_perfect_forecast(self, tmp_path: Path):
        fc = _fc("M001", 1.0)
        res = Resolution(
            market_id="M001",
            resolved_at=datetime.now(timezone.utc),
            outcome=ResolutionOutcome.YES,
        )
        sm, root = _setup_state_with_resolution(tmp_path, [fc], [res])
        summary = evaluate_experiment(sm, root, "P0-EVAL")
        assert summary.forecast_count == 1
        assert summary.resolved_count == 1
        assert summary.evaluated_count == 1
        assert summary.mean_ai_brier == 0.0

    def test_single_wrong_forecast(self, tmp_path: Path):
        fc = _fc("M001", 0.0)
        res = Resolution(
            market_id="M001",
            resolved_at=datetime.now(timezone.utc),
            outcome=ResolutionOutcome.YES,
        )
        sm, root = _setup_state_with_resolution(tmp_path, [fc], [res])
        summary = evaluate_experiment(sm, root, "P0-EVAL")
        assert summary.mean_ai_brier == 1.0

    def test_unresolved_market_excluded(self, tmp_path: Path):
        fc = _fc("M001", 0.5)
        sm, root = _setup_state_with_resolution(tmp_path, [fc], [])
        summary = evaluate_experiment(sm, root, "P0-EVAL")
        assert summary.evaluated_count == 0
        assert summary.unresolved_count == 1

    def test_mid_zero_is_valid_probability(self, tmp_path: Path):
        fc = _fc("M001", 0.2)
        res = Resolution(
            market_id="M001",
            resolved_at=datetime.now(timezone.utc),
            outcome=ResolutionOutcome.YES,
        )
        snap = {"market_id": "M001", "mid": 0.0}
        sm, root = _setup_state_with_resolution(tmp_path, [fc], [res], [snap])
        summary = evaluate_experiment(sm, root, "P0-EVAL")
        assert summary.mean_ai_brier is not None
        assert summary.mean_market_brier is not None

    def test_mid_one_is_valid_probability(self, tmp_path: Path):
        fc = _fc("M001", 0.8)
        res = Resolution(
            market_id="M001",
            resolved_at=datetime.now(timezone.utc),
            outcome=ResolutionOutcome.NO,
        )
        snap = {"market_id": "M001", "mid": 1.0}
        sm, root = _setup_state_with_resolution(tmp_path, [fc], [res], [snap])
        summary = evaluate_experiment(sm, root, "P0-EVAL")
        assert summary.mean_market_brier is not None

    def test_multiple_markets(self, tmp_path: Path):
        forecasts = [_fc("M001", 0.9), _fc("M002", 0.2), _fc("M003", 0.5)]
        resolutions = [
            Resolution(market_id="M001", resolved_at=datetime.now(timezone.utc), outcome=ResolutionOutcome.YES),
            Resolution(market_id="M002", resolved_at=datetime.now(timezone.utc), outcome=ResolutionOutcome.NO),
        ]
        sm, root = _setup_state_with_resolution(tmp_path, forecasts, resolutions)
        summary = evaluate_experiment(sm, root, "P0-EVAL")
        assert summary.forecast_count == 3
        assert summary.resolved_count == 2
        assert summary.evaluated_count == 2
        assert summary.unresolved_count == 1

    def test_no_evaluable_cases(self, tmp_path: Path):
        fc = _fc("M001", 0.5)
        sm, root = _setup_state_with_resolution(tmp_path, [fc], [])
        summary = evaluate_experiment(sm, root, "P0-EVAL")
        assert not summary.has_evaluable_cases()

    def test_has_evaluable_cases(self, tmp_path: Path):
        fc = _fc("M001", 0.5)
        res = Resolution(market_id="M001", resolved_at=datetime.now(timezone.utc), outcome=ResolutionOutcome.YES)
        sm, root = _setup_state_with_resolution(tmp_path, [fc], [res])
        summary = evaluate_experiment(sm, root, "P0-EVAL")
        assert summary.has_evaluable_cases()

    def test_extreme_error_count_zero(self, tmp_path: Path):
        fc = _fc("M001", 0.9)
        res = Resolution(market_id="M001", resolved_at=datetime.now(timezone.utc), outcome=ResolutionOutcome.YES)
        sm, root = _setup_state_with_resolution(tmp_path, [fc], [res])
        summary = evaluate_experiment(sm, root, "P0-EVAL")
        assert summary.extreme_error_count == 0

    def test_extreme_error_count_positive(self, tmp_path: Path):
        fc = _fc("M001", 0.02)
        res = Resolution(market_id="M001", resolved_at=datetime.now(timezone.utc), outcome=ResolutionOutcome.YES)
        sm, root = _setup_state_with_resolution(tmp_path, [fc], [res])
        summary = evaluate_experiment(sm, root, "P0-EVAL")
        assert summary.extreme_error_count == 1

    def test_delta_with_market_snapshot(self, tmp_path: Path):
        fc = _fc("M001", 0.7)
        res = Resolution(market_id="M001", resolved_at=datetime.now(timezone.utc), outcome=ResolutionOutcome.YES)
        snap = {"market_id": "M001", "mid": 0.6}
        sm, root = _setup_state_with_resolution(tmp_path, [fc], [res], [snap])
        summary = evaluate_experiment(sm, root, "P0-EVAL")
        assert summary.mean_delta_brier is not None
        assert summary.mean_market_log_loss is not None

    def test_delta_not_computed_when_no_snapshot(self, tmp_path: Path):
        fc = _fc("M001", 0.7)
        res = Resolution(market_id="M001", resolved_at=datetime.now(timezone.utc), outcome=ResolutionOutcome.YES)
        sm, root = _setup_state_with_resolution(tmp_path, [fc], [res])
        summary = evaluate_experiment(sm, root, "P0-EVAL")
        assert summary.mean_delta_brier is None
        assert summary.mean_market_brier is None


class TestMidZeroBug:
    def test_mid_zero_not_treated_as_missing(self, tmp_path: Path):
        fc = _fc("M001", 0.2)
        res = Resolution(market_id="M001", resolved_at=datetime.now(timezone.utc), outcome=ResolutionOutcome.YES)
        snap = {"market_id": "M001", "mid": 0.0}
        sm, root = _setup_state_with_resolution(tmp_path, [fc], [res], [snap])
        summary = evaluate_experiment(sm, root, "P0-EVAL")
        assert summary.mean_market_brier is not None
        assert summary.mean_delta_brier is not None

    def test_no_mid_no_price_no_delta(self, tmp_path: Path):
        fc = _fc("M001", 0.2)
        res = Resolution(market_id="M001", resolved_at=datetime.now(timezone.utc), outcome=ResolutionOutcome.YES)
        # snapshot with volume but no mid
        snap = {"market_id": "M001", "volume": 100}
        sm, root = _setup_state_with_resolution(tmp_path, [fc], [res], [snap])
        summary = evaluate_experiment(sm, root, "P0-EVAL")
        assert summary.mean_market_brier is None


class TestEvaluationSummary:
    def test_write_evaluation(self, tmp_path):
        summary = EvaluationSummary(
            experiment_id="P0",
            evaluated_at=datetime.now(timezone.utc),
            results=[EvalResult(market_id="M001", ai_brier=0.0, ai_log_loss=0.0)],
            evaluated_count=1,
        )
        out = tmp_path / "evaluation.json"
        out.write_text(summary.model_dump_json(indent=2), encoding="utf-8")
        assert out.exists()
        import json
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["experiment_id"] == "P0"
