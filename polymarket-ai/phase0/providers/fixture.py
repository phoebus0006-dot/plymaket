from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class FixtureForecastProvider:
    def __init__(self, fixture_path: str | Path) -> None:
        self.fixture_path = Path(fixture_path)
        with open(self.fixture_path, "r", encoding="utf-8") as f:
            self._outputs: dict[str, dict[str, Any]] = json.load(f)

    def forecast(self, market_id: str, clean_package: dict[str, Any]) -> dict[str, Any]:
        if market_id not in self._outputs:
            raise KeyError(f"No fixture forecast for market_id '{market_id}'")
        return dict(self._outputs[market_id])


class FixtureMarketSnapshotProvider:
    def __init__(self, fixtures_dir: str | Path) -> None:
        self.fixtures_dir = Path(fixtures_dir)

    def get_snapshot(self, market_id: str) -> dict[str, Any]:
        path = self.fixtures_dir / f"{market_id}.json"
        if not path.exists():
            path = self.fixtures_dir / "orderbooks" / f"{market_id}.json"
        if not path.exists():
            raise FileNotFoundError(f"No snapshot fixture for market_id '{market_id}'")
        with open(path, "r", encoding="utf-8") as f:
            return dict(json.load(f))
