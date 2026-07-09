# Schemas

## MarketManifest

```json
{
  "experiment_id": "P0-001",
  "created_at": "2025-06-01T00:00:00+00:00",
  "selection_cutoff": "2025-06-01T00:00:00+00:00",
  "selection_rule_version": "v1",
  "sampling_strategy": "stratified",
  "markets": [{"id": "M001", "question": "Will X happen?"}],
  "exclusion_rules": [],
  "manifest_hash": "sha256hex..."
}
```

## CleanForecastPackage

```json
{
  "market_id": "M001",
  "question": "Will X happen?",
  "description": "Market description",
  "resolution_source": "https://...",
  "outcomes": ["Yes", "No"],
  "evidence": [
    {
      "published_at": "2025-05-01T00:00:00+00:00",
      "source_url": "https://...",
      "claim": "Evidence text"
    }
  ],
  "package_created_at": "2025-05-15T00:00:00+00:00"
}
```

## Forecast

```json
{
  "market_id": "M001",
  "forecast_cutoff": "2025-06-01T00:00:00+00:00",
  "forecast_mode": "CHEAP_BASELINE",
  "p_yes": 0.63,
  "interval_50": [0.56, 0.70],
  "interval_80": [0.44, 0.77],
  "top_drivers": ["Driver 1"],
  "counterarguments": ["Counter 1"],
  "critical_unknowns": ["Unknown 1"],
  "rules_confidence": "MEDIUM",
  "research_cost_usd": 0.0,
  "latency_seconds": 0.0
}
```

## ForecastLock

```json
{
  "forecast_id": "FC-XXXX",
  "forecast_version": 1,
  "forecast_cutoff": "2025-06-01T00:00:00+00:00",
  "package_hash": "sha256hex...",
  "forecast_mode": "CHEAP_BASELINE",
  "raw_probability": 0.63,
  "locked_at": "2025-06-01T12:00:00+00:00",
  "forecast_hash": "sha256hex..."
}
```

All timestamps must be timezone-aware (UTC).
