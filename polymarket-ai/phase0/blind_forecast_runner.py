from __future__ import annotations

import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from .schemas import Forecast, ForecastMode, PackageArtifact
from .forecast_lock import compute_package_hash
from .package_validator import validate_package


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

    def _taint_audit(self, data: Any, path: str = "") -> list[str]:
        """Recursively scan for forbidden market signal fields."""
        forbidden = {"bid", "ask", "mid", "spread", "volume", "price", "bestBid", "bestAsk", "best_bid", "best_ask", "outcomePrices", "lastTradePrice", "market_price", "current_price"}
        violations = []
        if isinstance(data, dict):
            for key, val in data.items():
                norm = key.lower().replace("-", "_").replace(" ", "_")
                if norm in forbidden:
                    violations.append(f"{path}.{key}")
                violations.extend(self._taint_audit(val, f"{path}.{key}" if path else key))
        elif isinstance(data, list):
            for i, val in enumerate(data):
                violations.extend(self._taint_audit(val, f"{path}[{i}]"))
        return violations

    def run(
        self,
        market_id: str,
        package_artifact: PackageArtifact,
        forecast_mode: ForecastMode = ForecastMode.CHEAP_BASELINE,
    ) -> tuple[Forecast, dict[str, Any]]:
        """Run forecast in isolation.

        Args:
            market_id: Target market ID.
            package_artifact: Validated PackageArtifact with CleanForecastPackage inside.
            forecast_mode: Forecast mode.

        Returns:
            (Forecast, provenance_dict) where provenance_dict contains:
                - model_id, model_version, prompt_version, runner_version
                - package_hash, input_hash, raw_output_hash, parsed_forecast_hash
                - ran_at timestamp

        Raises:
            RuntimeError: If any isolation boundary is violated.
        """
        # Extract clean package dict
        clean_package = package_artifact.package.model_dump(mode="json")

        # Verify artifact hash
        computed_hash = hashlib.sha256(
            json.dumps(clean_package, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        if computed_hash != package_artifact.package_hash:
            raise RuntimeError(
                f"Package hash mismatch for {market_id}: "
                f"computed={computed_hash}, artifact={package_artifact.package_hash}"
            )

        # Verify market_id matches
        clean_market_id = clean_package.get("market_id", "")
        if clean_market_id != market_id:
            raise RuntimeError(
                f"market_id mismatch: run({market_id}) vs package({clean_market_id})"
            )

        # Taint audit: comprehensive recursive scan
        taint = self._taint_audit(clean_package)
        if taint:
            raise RuntimeError(f"Package taint detected: {', '.join(taint)}")

        # Also re-run validate_package for nested safety
        validate_package(clean_package)

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
