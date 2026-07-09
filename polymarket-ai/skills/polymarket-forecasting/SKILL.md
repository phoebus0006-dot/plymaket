# Polymarket Forecasting Skill (Phase 0)

## Purpose

Run a Phase 0 Feasibility Probe: can AI generate probability forecasts with independent
information value, without ever seeing Polymarket prices?

## Scope

- Phase 0 only. No real trading, no wallet, no order submission, no market data before lock.
- All tests use `FixtureForecastProvider` — zero LLM cost.

## Skill Responsibilities

1. **Detect** when the user wants to run a Phase 0 forecast experiment.
2. **Invoke** the Python CLI (`polymarket-ai` or `python -m phase0.cli`).
3. **Check current state** via the state machine (manifest frozen → package validated → forecast generated → locked → revealed → resolved → evaluated).
4. **Spawn an isolated child forecast** ONLY when semantic reasoning is needed.
5. **Delegate all deterministic work** to Python:
   - Hash computation
   - Schema validation
   - Temporal checks
   - State transitions
   - Evaluation math

## Hard Rules

| Rule | Enforcement |
|---|---|
| No real Polymarket data before forecast lock | `package_validator.py` blocks forbidden fields |
| No wallet creation | Not implemented in any module |
| No order submission | Not implemented in any module |
| No LLM hash/timing/schema work | Python handles all deterministic logic |
| Forecast Lock is immutable | `forecast_lock.py` prevents overwrite |
| Price must never enter forecast context | Provider adapter enforces clean package |
| All tests use fixtures | `FixtureForecastProvider` is the test default |

## CLI Commands

```bash
# Create manifest
python -m phase0.cli manifest-create --experiment-id P0-001

# Verify manifest
python -m phase0.cli manifest-verify <path>

# Validate package
python -m phase0.cli validate-package <path>

# Run forecast (uses fixtures)
python -m phase0.cli forecast --market-id M001 --package <path>

# Lock forecast
python -m phase0.cli lock --forecast <path> --package <path>

# Reveal price (after lock)
python -m phase0.cli reveal --market-id M001 --lock <path>

# Resolve
python -m phase0.cli resolve --market-id M001 --outcome YES

# Evaluate
python -m phase0.cli evaluate

# Simulate scenarios
python -m phase0.cli simulate happy_path
python -m phase0.cli simulate market_taint
python -m phase0.cli simulate temporal_leakage
python -m phase0.cli simulate price_before_lock
python -m phase0.cli simulate invalid_forecast_json
python -m phase0.cli simulate manifest_tamper
python -m phase0.cli simulate extreme_forecast_error
```

## Reference Documents

See `references/` for detailed protocol documentation:
- `phase0_protocol.md` — overall system design
- `forecast_protocol.md` — forecast generation rules
- `firewall_policy.md` — contamination rules
- `schemas.md` — all JSON schemas
