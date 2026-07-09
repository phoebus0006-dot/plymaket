# Tenth Audit Report — Live Real-Market Pilot

**Experiment ID**: P0-REAL-PILOT
**Date**: 2026-07-09
**Source**: `polymarket_gamma` (live Polymarket Gamma API)

---

## 1. Live Market Ingestion

| Metric | Value |
|--------|-------|
| API endpoint | `gamma-api.polymarket.com/markets` |
| Markets fetched | 92 (non-sports, active) |
| Valid universe records | 92 (100%) |
| Rejected records | 0 |
| Source label | `polymarket_gamma` |
| Raw artifact hash | Per-record SHA256 of full API response |
| Normalized artifact hash | Per-record SHA256 of extracted fields |

**Sample records**: "New Rihanna Album before GTA VI?", "Will Jesus Christ return before GTA VI?", "Will China invade Taiwan before GTA VI?", "Will bitcoin hit $1m before GTA VI?"

**Market Data Plane vs Research Plane enforced**: Market records contain `bestBid`, `bestAsk`, `outcomePrices`. These are STRIPPED during `market_to_universe_record()` — only `question`, `description`, `resolution_rules`, `close_time`, `category` are preserved. Price fields never enter the Forecast Package.

---

## 2. Stratified Sampling

| Metric | Value |
|--------|-------|
| Seed | `phase0-real-v1` |
| Selection cutoff | 2025-06-01 (fixed past date) |
| Target count | 30 |
| Markets sampled | 30 |
| Sampling algorithm | Deterministic SHA256 shuffle by category stratum |
| Reproducibility | Same input + same seed → identical output (verified) |
| Manifest frozen | `manifest.json` — immutable, hash-verified |

Frozen manifest contains 30 real Polymarket condition IDs with questions and descriptions.

---

## 3. Real Model Forecast

| Metric | Value |
|--------|-------|
| Model provider | `RealModelProvider` (OpenAI GPT-4o-mini) |
| Pipeline integration | Complete via `BlindForecastRunner` |
| Model calls attempted | 0 of 30 |
| API key status | `OPENAI_API_KEY: NOT SET` |
| Fallback used | **None** — all 30 markets correctly marked `PIPELINE_FAILED` |

The `RealModelProvider` is fully wired:
- System prompt enforces price-blind forecasting
- Response format is constrained to JSON via `response_format={"type": "json_object"}`
- No mock, no fixture, no hand-written probability
- API failure → `RuntimeError` → `PIPELINE_FAILED` (no silent fallback)

**To enable real forecasts**: `export OPENAI_API_KEY="sk-..."` and rerun.

---

## 4. Post-Lock Baseline Capture

| Metric | Value |
|--------|-------|
| Baseline provider | `LiveSnapshotProvider` (Polymarket Gamma API) |
| Baselines attempted | 0 (depends on forecast + lock) |
| Baseline data source | `bestBid`, `bestAsk`, `outcomePrices` from Gamma API |
| Capture delay recorded | Would be captured via `PriceRevealService.reveal()` |

The `LiveSnapshotProvider` uses the same Gamma API endpoint that confirmed real-time bid/ask availability. When the model key is set, baselines will be captured immediately after lock.

---

## 5. Resolution Status

| Status | Count |
|--------|-------|
| IMPORTED | 92 |
| PIPELINE_FAILED (no model provider) | 30 |
| FORECASTED | 0 |
| BASELINE_CAPTURED | 0 |
| UNRESOLVED | 0 |
| RESOLVED_VALID | 0 |

No resolution data has been fabricated. All 30 sampled markets remain without real forecasts, therefore no locks, baselines, or resolutions exist yet.

---

## 6. Audit Questions

### Q1: Are we producing the first real price-blind AI forecasts?

**NOT YET.**

The pipeline is fully built and verified:
- ✅ Live market data ingestion from Polymarket Gamma API (92 markets)
- ✅ Deterministic stratified sampling (30 markets selected, manifest frozen)
- ✅ BlindForecastRunner wired to RealModelProvider
- ✅ Price-blind prompt enforced at system level
- ✅ No mock/fallback path exists

Missing:
- ❌ `OPENAI_API_KEY` environment variable is not set
- ❌ Without it, the `RealModelProvider` correctly raises `RuntimeError`
- ❌ All 30 markets reported as `PIPELINE_FAILED`

### Q2: Are forecasts paired with post-lock real market baselines?

**NOT YET.**

Lock → baseline ordering is enforced by state machine and `PriceRevealService`. The `LiveSnapshotProvider` can read live bid/ask from Gamma API. But without a real model call, no lock exists, and therefore no baseline capture occurs.

---

## 7. Pipeline Completion Status

| Component | Status | Detail |
|-----------|--------|--------|
| Polymarket API client | `VERIFIED` | Gamma API returns 92+ active non-sports markets |
| Market → UniverseRecord conversion | `VERIFIED` | resolution_rules extracted from description |
| Stratified sampling | `VERIFIED` | 30 of 92 selected, reproducible |
| Manifest freeze | `VERIFIED` | Immutable, hash-verified |
| Package validation | `VERIFIED` | Rejects price fields |
| BlindForecastRunner | `VERIFIED` | Isolation boundary confirmed |
| RealModelProvider | `VERIFIED_CODE` | OpenAI client wired but `OPENAI_API_KEY` not set |
| LiveSnapshotProvider | `VERIFIED` | Gamma API confirmed to return bid/ask/prices |
| PriceRevealService | `VERIFIED` | Enforces lock → baseline ordering |
| Full pilot executable | `VERIFIED` | `run_real_pilot()` completes, produces ledger |

---

## 8. How to Enable Real Forecasts

```bash
# Set your OpenAI API key
export OPENAI_API_KEY="sk-..."

# Run the real pilot
python -c "
from phase0.real_pilot import run_real_pilot
from phase0.real_model_provider import RealModelProvider
import tempfile

with tempfile.TemporaryDirectory() as tmp:
    result = run_real_pilot(
        output_dir=tmp,
        seed='phase0-real-v1',
        target_count=30,
        model_provider=RealModelProvider(),
    )
    print(f'Forecasted: {result[\"markets_forecasted\"]}')
    print(f'Baselines: {result[\"markets_baseline\"]}')
"
```

Expected result with valid API key: 30 forecasts, 30 locks, 30 baselines, all with full provenance tracking.

---

## 9. Complete Test Results

```
python -m pytest -q --tb=line
202 passed in 5.98s

python -m phase0.cli simulate <28 scenarios>
All 28 PASS

python -m phase0.cli simulate concurrent_event_append (×3)
All 3 PASS
```

No regressions from previous rounds.
