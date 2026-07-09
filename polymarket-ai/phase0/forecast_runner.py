from __future__ import annotations

from typing import Any

from phase0.schemas import Forecast, CleanForecastPackage
from phase0.providers.base import ForecastProvider


class MarketIdentityMismatchError(ValueError):
    pass


def run_forecast(
    provider: ForecastProvider,
    market_id: str,
    clean_package: dict[str, Any],
) -> Forecast:
    clean = CleanForecastPackage(**clean_package) if not isinstance(clean_package, CleanForecastPackage) else clean_package

    if clean.market_id != market_id:
        raise MarketIdentityMismatchError(
            f"market_id mismatch: requested={market_id}, "
            f"package.market_id={clean.market_id}"
        )

    raw = provider.forecast(market_id, clean.model_dump())
    fc = Forecast(**raw)

    if fc.market_id != market_id:
        raise MarketIdentityMismatchError(
            f"market_id mismatch: requested={market_id}, "
            f"forecast.market_id={fc.market_id}"
        )

    return fc
