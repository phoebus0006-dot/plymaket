# Forecast Protocol

## Rules for Hermes Child

1. Receive CleanForecastPackage (market_id, question, description, evidence).
2. NO market price data is included. If any appears, reject.
3. Output must be strict JSON matching the Forecast schema.
4. Do NOT output Markdown, code blocks, or commentary.

## Schema

See `schemas.md` for the exact Forecast JSON schema.

## Confidence Levels

- LOW: quick heuristic, minimal research
- MEDIUM: some evidence review (Phase 0 default)
- HIGH: thorough analysis
- VERY_HIGH: deep multi-source research

## Lock Rule

Once a forecast is locked, it cannot be modified. New analysis creates
forecast_version + 1. The original v1 is preserved forever.
