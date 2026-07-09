from __future__ import annotations

from typing import Any, Protocol


class ForecastProvider(Protocol):
    def forecast(self, market_id: str, clean_package: dict[str, Any]) -> dict[str, Any]:
        ...


class MarketSnapshotProvider(Protocol):
    def get_snapshot(self, market_id: str) -> dict[str, Any]:
        ...
