# Phase 0 Protocol

## Research Question

Can AI generate probabilistically calibrated forecasts with independent information value
when it has zero access to Polymarket price data (bid, ask, midpoint, volume, history,
betting odds, or prediction-market commentary)?

## Principle

Paper-only. All analysis is based on publicly available evidence collected before the
forecast cutoff. No market price is consulted before the forecast is locked.

## Data Flow

1. Market Manifest is created and frozen (hash verified).
2. CleanForecastPackage is built from public evidence only.
3. Package is validated against the Research Firewall (no price fields allowed).
4. Evidence timestamps are checked against forecast_cutoff.
5. ForecastProvider generates a forecast (fixture or Hermes child).
6. Forecast is validated against Forecast schema.
7. Forecast is locked (immutable file + hash).
8. Price is revealed from market snapshot (fixture or API).
9. Market resolves.
10. Evaluation computes Brier, Log Loss, and delta vs market baseline.

## State Machine

```
MANIFEST_FROZEN → PACKAGE_READY → FORECAST_GENERATED → FORECAST_LOCKED
→ PRICE_REVEALED → RESOLVED → EVALUATED
```

Illegal transitions (tested):
- PACKAGE_READY → PRICE_REVEALED
- FORECAST_GENERATED → PRICE_REVEALED
