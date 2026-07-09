from __future__ import annotations

from typing import Any


class HermesForecastProvider:
    """
    Adapter skeleton for Hermes Agent forecast provider.

    Phase 0: This is a documented adapter skeleton only.
    No real Hermes commands or API calls are implemented yet.

    Usage in Phase 1:
        hermes = HermesForecastProvider()
        result = hermes.forecast(market_id="M001", clean_package={...})

    Responsibilities:
        1. Read the CleanForecastPackage.
        2. Spawn an isolated child forecast task with NO market price data.
        3. Require the child to output strict JSON matching the Forecast schema.
        4. Return the raw JSON dict for Python-side validation and locking.

    Constraints:
        - NEVER pass market prices into the child context.
        - NEVER let the LLM modify a locked forecast.
        - NEVER let the LLM handle hashing, time checks, or schema validation.
    """

    def forecast(self, market_id: str, clean_package: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError(
            "HermesForecastProvider is a Phase 0 skeleton. "
            "Use FixtureForecastProvider for testing."
        )
