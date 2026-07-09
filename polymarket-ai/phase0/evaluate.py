from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .schemas import EvalResult, EvaluationSummary, ForecastLock, Resolution
from .state import ExperimentStateManager, MarketStatus


def _get_market_price(snapshot: dict[str, Any] | None) -> float | None:
    """Extract the mid price from a snapshot dict.

    Returns None if no snapshot or mid is None.
    """
    if snapshot is None:
        return None
    mid = snapshot.get("mid")
    if mid is None:
        return None
    return float(mid)


def _brier_score(y_true: float, y_pred: float) -> float:
    return (y_true - y_pred) ** 2


def _log_loss(y_true: float, y_pred: float, eps: float = 1e-15) -> float:
    y_pred = max(eps, min(1.0 - eps, y_pred))
    if y_true == 1.0:
        return -math.log(y_pred)
    return -math.log(1.0 - y_pred)


def evaluate_experiment(
    state_mgr: ExperimentStateManager,
    experiments_root: str,
    experiment_id: str,
) -> EvaluationSummary:
    """Run evaluation for markets that have both a forecast lock and a resolution.

    Markets without a resolution are listed as ``pending_markets``.
    Each evaluated market gets an EVALUATED state transition.
    """
    events = state_mgr.store.read_all()

    # collect data from events
    locks: dict[str, ForecastLock] = {}
    resolutions: dict[str, Resolution] = {}
    snapshots: dict[str, dict[str, Any]] = {}
    snapshot_events: dict[str, list[dict[str, Any]]] = {}

    for ev in events:
        mid = ev.market_id
        if ev.event_type == "forecast_locked":
            lock_data = ev.data.get("lock")
            if lock_data:
                locks[mid] = ForecastLock(**lock_data)
        elif ev.event_type == "price_revealed":
            snap = ev.data.get("snapshot")
            if snap:
                snapshots[mid] = snap
        elif ev.event_type == "price_unavailable":
            pass
        elif ev.event_type == "market_resolved":
            res_data = ev.data.get("resolution")
            if res_data:
                resolutions[mid] = Resolution(**res_data)

    results: list[EvalResult] = []
    pending: list[str] = []
    resolved_count = 0
    unresolved_count = 0
    extreme_errors = 0

    # determine all markets that got a forecast lock
    all_market_ids = set(locks.keys())

    for mid in sorted(all_market_ids):
        lock = locks[mid]

        if mid not in resolutions:
            pending.append(mid)
            unresolved_count += 1
            continue

        resolution = resolutions[mid]
        y_true = resolution.outcome.to_p_yes()

        # AI forecast
        p_ai = lock.raw_probability

        # Market price (if available)
        snapshot = snapshots.get(mid)
        p_market = _get_market_price(snapshot)

        ai_brier = _brier_score(y_true, p_ai)
        ai_log = _log_loss(y_true, p_ai)

        market_brier: float | None = None
        market_log: float | None = None
        delta_brier: float | None = None
        delta_log: float | None = None

        if p_market is not None:
            market_brier = _brier_score(y_true, p_market)
            market_log = _log_loss(y_true, p_market)
            delta_brier = ai_brier - market_brier
            delta_log = ai_log - market_log

        if ai_brier > 0.5:
            extreme_errors += 1

        resolved_count += 1
        results.append(
            EvalResult(
                market_id=mid,
                ai_brier=round(ai_brier, 6),
                market_brier=round(market_brier, 6) if market_brier is not None else None,
                delta_brier=round(delta_brier, 6) if delta_brier is not None else None,
                ai_log_loss=round(ai_log, 6),
                market_log_loss=round(market_log, 6) if market_log is not None else None,
                delta_log_loss=round(delta_log, 6) if delta_log is not None else None,
            )
        )

        # transition to EVALUATED (only if not already EVALUATED)
        if state_mgr.market_status(mid) == MarketStatus.RESOLVED:
            state_mgr.record_market_evaluated(
                experiment_id=experiment_id,
                market_id=mid,
            )

    # compute means
    def _safe_mean(vals: list[float]) -> float:
        return sum(vals) / len(vals) if vals else 0.0

    summary = EvaluationSummary(
        experiment_id=experiment_id,
        evaluated_at=datetime.now(timezone.utc),
        results=results,
        pending_markets=pending,
        forecast_count=len(all_market_ids),
        resolved_count=resolved_count,
        evaluated_count=len(results),
        unresolved_count=unresolved_count,
        mean_ai_brier=_safe_mean([r.ai_brier for r in results]),
        mean_market_brier=(
            _safe_mean([r.market_brier for r in results if r.market_brier is not None])
            if any(r.market_brier is not None for r in results)
            else None
        ),
        mean_delta_brier=(
            _safe_mean([r.delta_brier for r in results if r.delta_brier is not None])
            if any(r.delta_brier is not None for r in results)
            else None
        ),
        mean_ai_log_loss=_safe_mean([r.ai_log_loss for r in results]),
        mean_market_log_loss=(
            _safe_mean([r.market_log_loss for r in results if r.market_log_loss is not None])
            if any(r.market_log_loss is not None for r in results)
            else None
        ),
        mean_delta_log_loss=(
            _safe_mean([r.delta_log_loss for r in results if r.delta_log_loss is not None])
            if any(r.delta_log_loss is not None for r in results)
            else None
        ),
        extreme_error_count=extreme_errors,
    )

    return summary
