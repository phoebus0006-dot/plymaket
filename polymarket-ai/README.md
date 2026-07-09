# Polymarket AI — Phase 0 Feasibility Probe

## Research Question

Can AI generate probabilistically calibrated forecasts with independent information value
when it has **zero access** to Polymarket price data (bid, ask, midpoint, spread, volume,
price history, betting odds, or prediction-market commentary)?

**Phase 0 is PAPER-ONLY.** No wallet, no keys, no trading, no order submission.

---

## Architecture

```
Market Manifest (frozen + hashed)
    ↓
CleanForecastPackage (validated by Research Firewall)
    ↓
ForecastProvider (fixture | hermes | future API)
    ↓
Forecast (validated by Pydantic schema)
    ↓
ForecastLock (immutable, hash-verified)
    ↓
Price Reveal (only after lock)
    ↓
Resolution
    ↓
Evaluation (Brier, Log Loss, delta vs market)
```

## Security Boundaries

| Layer | Protection |
|---|---|
| Research Firewall | Recursive scan blocks 17 forbidden price-related fields at any nesting level |
| Source Domain Firewall | Blocks polymarket.com, kalshi.com, predictionmarket.com evidence sources |
| Temporal Integrity | Evidence published_at/first_seen_at must be ≤ forecast_cutoff |
| Forecast Lock | Immutable after creation; hash verified before use |
| State Machine | Illegal transitions (e.g. price reveal before lock) are rejected |
| Provider Abstraction | All LLM calls behind uniform interface; tests use FixtureForecastProvider |

## Install

```bash
cd polymarket-ai
pip install -e ".[dev]"
```

## Unit Tests

```bash
python -m pytest tests/ -v
```

## Simulation

```bash
python -m phase0.cli simulate happy_path
python -m phase0.cli simulate market_taint
python -m phase0.cli simulate temporal_leakage
python -m phase0.cli simulate price_before_lock
python -m phase0.cli simulate invalid_forecast_json
python -m phase0.cli simulate manifest_tamper
python -m phase0.cli simulate extreme_forecast_error
```

Each simulation:
1. Creates a clean temp directory.
2. Sets up fixed inputs.
3. Runs the full pipeline (or expected failure path).
4. Prints PASS/FAIL and returns correct exit code.

## Hermes Skill Installation

```bash
ln -s "$(pwd)/skills/polymarket-forecasting" /path/to/hermes/skills/
```

See `skills/polymarket-forecasting/SKILL.md` for usage.

## Deployment Principles (Oracle Linux / Ubuntu)

- Python 3.11+ required.
- No external databases, vector stores, or message queues.
- All state is on local filesystem (JSON/JSONL).
- Cron or systemd timer for periodic experiment runs.
- Hermes Agent runs the skill; Python CLI handles all deterministic work.

## Data Directory Structure

```
data/
├── manifests/         # Frozen market manifests
├── packages/          # Clean forecast packages
├── forecasts/         # Generated forecasts
├── locks/             # Immutable forecast locks
├── market_snapshots/  # Price snapshots (revealed after lock)
├── resolutions/       # Market resolution outcomes
└── experiment_logs/   # Evaluation summaries + audit trail
```

## State Machine

```
MANIFEST_FROZEN → PACKAGE_READY → FORECAST_GENERATED → FORECAST_LOCKED
    → PRICE_REVEALED → RESOLVED → EVALUATED
```

Illegal transitions are enforced and tested.

## Implemented

- [x] Pydantic schemas with timezone enforcement
- [x] Deterministic SHA256 canonical hashing
- [x] Manifest creation, freeze, and integrity verification
- [x] Research Firewall (field + domain contamination detection)
- [x] Temporal integrity checks
- [x] ForecastProvider abstraction (FixtureForecastProvider, HermesForecastProvider skeleton)
- [x] Forecast locking (immutable, hash-verified)
- [x] Price reveal state machine
- [x] Brier score, Log Loss, evaluation math
- [x] CLI with 9 commands
- [x] 7 simulation scenarios
- [x] 59 pytest tests (all pass, no network, no LLM, no wallet)
- [x] Hermes Skill with documentation
- [x] Audit trail (JSONL append-only)

## Not Implemented (Phase 0)

- Real Polymarket API integration
- Real LLM API integration
- Wallet creation or key management
- Order submission or trading
- Historical price database
- Vector DB or embedding storage
- Web UI or dashboard
- Real-time data pipelines
- Phase 1+ features
