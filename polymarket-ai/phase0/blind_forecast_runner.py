from __future__ import annotations

import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from .schemas import Forecast, ForecastMode


class ForecastProvider(Protocol):
    """Protocol for forecast providers that accept only CleanForecastPackage data."""

    def forecast(self, market_id: str, clean_package: dict[str, Any]) -> dict[str, Any]:
        ...


class BlindForecastRunner:
    """Isolated forecast runner that ONLY accepts validated Package Artifacts.

    No access to Market Universe Record, market prices, or any market data.
    """

    def __init__(
        self,
        provider: ForecastProvider,
        model_id: str = "fixture-v1",
        model_version: str = "1.0.0",
        prompt_version: str = "v1",
        runner_version: str = "1.0.0",
    ) -> None:
        self._provider = provider
        self.model_id = model_id
        self.model_version = model_version
        self.prompt_version = prompt_version
        self.runner_version = runner_version

    def run(
        self,
        market_id: str,
        clean_package: dict[str, Any],
        forecast_mode: ForecastMode = ForecastMode.CHEAP_BASELINE,
    ) -> tuple[Forecast, dict[str, Any]]:
        """Run forecast in isolation.

        Args:
            market_id: Target market ID.
            clean_package: The CleanForecastPackage dict (from validated PackageArtifact).
            forecast_mode: Forecast mode.

        Returns:
            (Forecast, provenance_dict) where provenance_dict contains:
                - model_id, model_version, prompt_version, runner_version
                - package_hash, input_hash, raw_output_hash, parsed_forecast_hash
                - ran_at timestamp

        Raises:
            RuntimeError: If any isolation boundary is violated.
        """
        # Compute hashes
        package_hash = hashlib.sha256(
            json.dumps(clean_package, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()

        input_hash = hashlib.sha256(
            json.dumps({
                "market_id": market_id,
                "package_hash": package_hash,
                "forecast_mode": forecast_mode.value,
            }, sort_keys=True).encode("utf-8")
        ).hexdigest()

        ran_at = datetime.now(timezone.utc)

        # Call provider (only receives clean package data, no market data)
        raw_output = self._provider.forecast(
            market_id=market_id,
            clean_package=clean_package,
        )

        raw_output_hash = hashlib.sha256(
            json.dumps(raw_output, sort_keys=True).encode("utf-8")
        ).hexdigest()

        # Parse and validate forecast
        forecast_obj = Forecast(**raw_output)
        parsed_forecast_hash = hashlib.sha256(
            json.dumps(forecast_obj.model_dump(mode="json"), sort_keys=True).encode("utf-8")
        ).hexdigest()

        provenance = {
            "model_id": self.model_id,
            "model_version": self.model_version,
            "prompt_version": self.prompt_version,
            "runner_version": self.runner_version,
            "package_hash": package_hash,
            "input_hash": input_hash,
            "raw_output_hash": raw_output_hash,
            "parsed_forecast_hash": parsed_forecast_hash,
            "ran_at": ran_at.isoformat(),
        }

        return forecast_obj, provenance
