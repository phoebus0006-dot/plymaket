from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from .schemas import ManifestMarketEntry


def _deterministic_shuffle(
    items: list[dict[str, Any]],
    seed: str,
    salt: str = "",
) -> list[dict[str, Any]]:
    """Deterministic shuffle using SHA256-based sorting key."""
    def _sort_key(item: dict[str, Any]) -> str:
        mid = item.get("market_id", "")
        return hashlib.sha256(f"{seed}:{salt}:{mid}".encode()).hexdigest()
    return sorted(items, key=_sort_key)


def stratify_markets(
    universe: list[dict[str, Any]],
    selection_cutoff: datetime | None = None,
    seed: str = "phase0-v1-seed",
    target_count: int = 40,
    min_count: int = 20,
    max_count: int = 50,
) -> tuple[list[ManifestMarketEntry], list[str]]:
    """Deterministic stratified sampling from market universe.

    Uses Category, Horizon, Rule Complexity, and Liquidity Bucket
    for four-dimension stratification.

    Returns (selected_markets, exclusion_reasons).
    """
    from datetime import timezone as _tz

    if selection_cutoff is None:
        selection_cutoff = datetime.now(_tz.utc)

    excluded: list[str] = []
    passed: list[dict[str, Any]] = []

    for rec in universe:
        mid = rec.get("market_id", "")
        reasons: list[str] = []

        # Reject missing identity
        if not mid:
            excluded.append("(no market_id): missing market_id")
            continue

        # Reject missing resolution rules
        if not rec.get("resolution_rules"):
            excluded.append(f"{mid}: missing resolution_rules")
            continue

        # Reject missing close_time
        close_str = rec.get("close_time")
        if not close_str:
            excluded.append(f"{mid}: missing close_time")
            continue
        try:
            if isinstance(close_str, str):
                close_dt = datetime.fromisoformat(close_str)
            else:
                close_dt = close_str
            if close_dt.tzinfo is None:
                close_dt = close_dt.replace(tzinfo=_tz.utc)
        except Exception:
            excluded.append(f"{mid}: invalid close_time")
            continue

        # Reject already-closed markets
        if close_dt < selection_cutoff:
            excluded.append(f"{mid}: already closed ({close_dt.isoformat()})")
            continue

        passed.append(rec)

    # Compute four dimensions for each passed record
    for rec in passed:
        close_str = rec.get("close_time")
        if isinstance(close_str, str):
            close_dt = datetime.fromisoformat(close_str)
        else:
            close_dt = close_str
        if close_dt.tzinfo is None:
            close_dt = close_dt.replace(tzinfo=_tz.utc)
        horizon_days = max(0, (close_dt - selection_cutoff).days)

        # Horizon bucket
        if horizon_days < 30:
            horizon_bucket = "<30"
        elif horizon_days < 90:
            horizon_bucket = "30-90"
        elif horizon_days < 180:
            horizon_bucket = "90-180"
        else:
            horizon_bucket = "180+"

        # Rule complexity
        rules = rec.get("resolution_rules", "")
        if len(rules) < 100:
            rule_complexity = "short"
        elif len(rules) < 500:
            rule_complexity = "medium"
        else:
            rule_complexity = "long"

        # Liquidity bucket
        liquidity_bucket = rec.get("liquidity_bucket", "unknown")

        rec["_horizon_days"] = horizon_days
        rec["_horizon_bucket"] = horizon_bucket
        rec["_rule_complexity"] = rule_complexity
        rec["_liquidity_bucket"] = liquidity_bucket
        rec["_category"] = rec.get("category", "unknown")

    # Create composite strata keys across all four dimensions
    strata: dict[str, list[dict[str, Any]]] = {}
    for rec in passed:
        key = f"{rec['_category']}|{rec['_horizon_bucket']}|{rec['_rule_complexity']}|{rec['_liquidity_bucket']}"
        if key not in strata:
            strata[key] = []
        strata[key].append(rec)

    selected: list[dict[str, Any]] = []
    total_slots = min(max_count, max(min_count, target_count))

    # Distribute slots evenly across unique stratum combinations
    sorted_keys = sorted(strata.keys())
    if sorted_keys:
        per_stratum = max(1, total_slots // len(sorted_keys))
        remainder = total_slots - per_stratum * len(sorted_keys)

        for i, key in enumerate(sorted_keys):
            pool = strata[key]
            pool = _deterministic_shuffle(pool, seed, salt=f"stratum:{key}")
            slots = per_stratum + (1 if i < remainder else 0)
            selected.extend(pool[:slots])
    else:
        selected = passed[:total_slots]

    # Reshuffle final selection deterministically
    selected = _deterministic_shuffle(selected, seed, salt="final")

    entries = [
        ManifestMarketEntry(
            market_id=rec.get("market_id", ""),
            question=rec.get("question", ""),
            description=rec.get("description", ""),
            tags=rec.get("tags", []),
            horizon_days=rec.get("_horizon_days", 0),
            rule_complexity=rec.get("_rule_complexity", ""),
            liquidity_bucket=rec.get("_liquidity_bucket", ""),
        )
        for rec in selected
    ]

    return entries[:max_count], excluded


def generate_manifest_markets(
    universe: list[dict[str, Any]],
    selection_cutoff: datetime | None = None,
    seed: str = "phase0-v1-seed",
    target_count: int = 40,
) -> tuple[list[ManifestMarketEntry], list[str]]:
    """Convenience wrapper for stratified sampling.

    Returns (selected_markets, exclusion_reasons).
    """
    return stratify_markets(
        universe=universe,
        selection_cutoff=selection_cutoff,
        seed=seed,
        target_count=target_count,
    )
