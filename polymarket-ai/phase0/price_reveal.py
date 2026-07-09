from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from phase0.schemas import PriceSnapshot
from phase0.providers.base import MarketSnapshotProvider


class RevealStateError(RuntimeError):
    pass


class RevealState(Enum):
    MANIFEST_FROZEN = "MANIFEST_FROZEN"
    PACKAGE_READY = "PACKAGE_READY"
    FORECAST_GENERATED = "FORECAST_GENERATED"
    FORECAST_LOCKED = "FORECAST_LOCKED"
    PRICE_REVEALED = "PRICE_REVEALED"
    RESOLVED = "RESOLVED"
    EVALUATED = "EVALUATED"


_ALLOWED_TRANSITIONS: dict[RevealState, set[RevealState]] = {
    RevealState.MANIFEST_FROZEN: {RevealState.PACKAGE_READY},
    RevealState.PACKAGE_READY: {RevealState.FORECAST_GENERATED, RevealState.MANIFEST_FROZEN},
    RevealState.FORECAST_GENERATED: {RevealState.FORECAST_LOCKED, RevealState.PACKAGE_READY},
    RevealState.FORECAST_LOCKED: {RevealState.PRICE_REVEALED},
    RevealState.PRICE_REVEALED: {RevealState.RESOLVED},
    RevealState.RESOLVED: {RevealState.EVALUATED},
}


def validate_transition(current: RevealState, target: RevealState) -> None:
    allowed = _ALLOWED_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise RevealStateError(
            f"Illegal state transition: {current.value} -> {target.value}. "
            f"Allowed from {current.value}: {[s.value for s in allowed]}"
        )


def reveal_price(
    market_id: str,
    lock_path: str | Path,
    snapshot_provider: MarketSnapshotProvider,
    snapshots_dir: str | Path,
) -> PriceSnapshot:
    lock_exist = Path(lock_path).exists()
    if not lock_exist:
        raise RevealStateError(
            f"Cannot reveal price: no lock file found at {lock_path}. "
            "Forecast must be locked before price reveal."
        )

    snapshot_data = snapshot_provider.get_snapshot(market_id)
    snapshot = PriceSnapshot(
        market_id=market_id,
        snapshot_timestamp=datetime.now(timezone.utc),
        **{k: v for k, v in snapshot_data.items() if k != "market_id"},
    )

    snapshots_dir_path = Path(snapshots_dir)
    snapshots_dir_path.mkdir(parents=True, exist_ok=True)
    out_path = snapshots_dir_path / f"{market_id}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(snapshot.model_dump_json(indent=2))

    return snapshot
