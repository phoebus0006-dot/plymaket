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
    category_weight: float = 1.0,
    horizon_weight: float = 1.0,
) -> tuple[list[ManifestMarketEntry], list[str]]:
    """Deterministic stratified sampling from market universe.

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

    # Determine number of strata
    categories: dict[str, list[dict[str, Any]]] = {}
    for rec in passed:
        cat = rec.get("category", "unknown")
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(rec)

    selected: list[dict[str, Any]] = []
    total_slots = min(max_count, max(min_count, target_count))

    # Distribute slots across strata proportionally, then sample deterministically
    sorted_cats = sorted(categories.keys())
    if sorted_cats:
        per_cat = max(1, total_slots // len(sorted_cats))
        remainder = total_slots - per_cat * len(sorted_cats)

        for i, cat in enumerate(sorted_cats):
            pool = categories[cat]
            pool = _deterministic_shuffle(pool, seed, salt=f"cat:{cat}")
            slots = per_cat + (1 if i < remainder else 0)
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
