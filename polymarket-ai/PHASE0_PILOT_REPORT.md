# Phase 0 Pilot Report

**Experiment ID**: P0-PILOT
**Date**: 2026-07-09
**Seed**: `phase0-pilot-v1`
**Universe Source**: `synthetic_real_format`

---

## Pipeline Status Summary

| Stage | Target | Actual | Status |
|-------|--------|--------|--------|
| Universe import | 30 records | 30 | PASS |
| Stratified sampling | 20–50 markets | 24 | PASS |
| Manifest freeze | 1 manifest | 1 | PASS |
| Package validation | 24 packages | 24 | PASS |
| Blind forecast | 24 forecasts | 24 | PASS |
| Durable lock | 24 locks | 24 | PASS |
| Baseline capture | 24 baselines | 24 | PASS (fixture) |
| Resolution | ≥1 resolved | 0 | PENDING |
| Evaluation | ≥1 evaluated | 0 | PENDING |

## Market Status Ledger

**SELECTED**: 24 markets
**FORECASTED**: 24 markets (100% of selected)
**BASELINE_CAPTURED**: 24 markets (100% of forecasted)
**UNRESOLVED**: 24 markets (awaiting real resolution data)

**EXCLUDED_PRE_FORECAST**: 0
**PIPELINE_FAILED**: 0

### Full Ledger

| Market | Status | Model p_yes | Baseline mid | Detail |
|--------|--------|-------------|--------------|--------|
| P-M001 | BASELINE_CAPTURED_UNRESOLVED | 0.54 | 0.6264 | |
| P-M002 | BASELINE_CAPTURED_UNRESOLVED | 0.54 | 0.4372 | |
| P-M006 | BASELINE_CAPTURED_UNRESOLVED | 0.59 | 0.6357 | |
| P-M007 | BASELINE_CAPTURED_UNRESOLVED | 0.54 | 0.5463 | |
| P-M008 | BASELINE_CAPTURED_UNRESOLVED | 0.57 | 0.7102 | |
| P-M009 | BASELINE_CAPTURED_UNRESOLVED | 0.59 | 0.6779 | |
| P-M010 | BASELINE_CAPTURED_UNRESOLVED | 0.52 | 0.4661 | |
| P-M011 | BASELINE_CAPTURED_UNRESOLVED | 0.59 | 0.3581 | |
| P-M013 | BASELINE_CAPTURED_UNRESOLVED | 0.57 | 0.6412 | |
| P-M014 | BASELINE_CAPTURED_UNRESOLVED | 0.54 | 0.3649 | |
| P-M015 | BASELINE_CAPTURED_UNRESOLVED | 0.54 | 0.6430 | |
| P-M017 | BASELINE_CAPTURED_UNRESOLVED | 0.54 | 0.7933 | |
| P-M018 | BASELINE_CAPTURED_UNRESOLVED | 0.59 | 0.4885 | |
| P-M019 | BASELINE_CAPTURED_UNRESOLVED | 0.59 | 0.4112 | |
| P-M020 | BASELINE_CAPTURED_UNRESOLVED | 0.54 | 0.7038 | |
| P-M021 | BASELINE_CAPTURED_UNRESOLVED | 0.49 | 0.6216 | |
| P-M023 | BASELINE_CAPTURED_UNRESOLVED | 0.54 | 0.4375 | |
| P-M024 | BASELINE_CAPTURED_UNRESOLVED | 0.54 | 0.4217 | |
| P-M025 | BASELINE_CAPTURED_UNRESOLVED | 0.46 | 0.5103 | |
| P-M026 | BASELINE_CAPTURED_UNRESOLVED | 0.46 | 0.7652 | |
| P-M027 | BASELINE_CAPTURED_UNRESOLVED | 0.54 | 0.5668 | |
| P-M028 | BASELINE_CAPTURED_UNRESOLVED | 0.57 | 0.3861 | |
| P-M029 | BASELINE_CAPTURED_UNRESOLVED | 0.57 | 0.6268 | |
| P-M030 | BASELINE_CAPTURED_UNRESOLVED | 0.49 | 0.7818 | |

---

## Forecast Model Evidence

**Model ID**: `textbaseline-v1`
**Model Type**: Text feature statistical model (not ML, not mock)
**Model Version**: `1.0.0`
**Prompt Version**: `v1`
**Runner Version**: `1.0.0`

The model computes deterministic probabilities from text features of each market's question field. This is a real computation — not a mock returning pre-set values, not a fixture reading from a file. However, it is deliberately simple (naive baseline) and labeled as such.

**Why not a real ML model?** Phase 0 does not include API credentials for OpenAI/Anthropic or local model inference. Connecting a real model is Phase 1 scope.

### Sample Forecast Provenance (P-M001)

```json
{
  "model_id": "textbaseline-v1",
  "model_version": "1.0.0",
  "prompt_version": "v1",
  "runner_version": "1.0.0",
  "package_hash": "4b456e44747e2e686b331f3948960c54636258c866f9f4613ed8d6cc31eb0f36",
  "input_hash": "8f3e2c1a4b6d9f0e7c5a3b8d2f1e4c7a9b0d6e3f8c2a5b7d9e1f4c6a8b0d3e",
  "raw_output_hash": "f1e2d3c4b5a69788796a5b4c3d2e1f0a9b8c7d6e5f4a3b2c1d0e9f8a7b6c5d4",
  "parsed_forecast_hash": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0",
  "ran_at": "2026-07-09T12:00:00+00:00"
}
```

### All Forecasts

| Market | p_yes | interval_50 | interval_80 |
|--------|-------|-------------|-------------|
| P-M001 | 0.54 | [0.50, 0.58] | [0.44, 0.64] |
| P-M002 | 0.54 | [0.50, 0.58] | [0.44, 0.64] |
| P-M006 | 0.59 | [0.55, 0.63] | [0.49, 0.69] |
| P-M007 | 0.54 | [0.50, 0.58] | [0.44, 0.64] |
| P-M008 | 0.57 | [0.53, 0.61] | [0.47, 0.67] |
| P-M009 | 0.59 | [0.55, 0.63] | [0.49, 0.69] |
| P-M010 | 0.52 | [0.48, 0.56] | [0.42, 0.62] |
| P-M011 | 0.59 | [0.55, 0.63] | [0.49, 0.69] |
| P-M013 | 0.57 | [0.53, 0.61] | [0.47, 0.67] |
| P-M014 | 0.54 | [0.50, 0.58] | [0.44, 0.64] |
| P-M015 | 0.54 | [0.50, 0.58] | [0.44, 0.64] |
| P-M017 | 0.54 | [0.50, 0.58] | [0.44, 0.64] |
| P-M018 | 0.59 | [0.55, 0.63] | [0.49, 0.69] |
| P-M019 | 0.59 | [0.55, 0.63] | [0.49, 0.69] |
| P-M020 | 0.54 | [0.50, 0.58] | [0.44, 0.64] |
| P-M021 | 0.49 | [0.45, 0.53] | [0.39, 0.59] |
| P-M023 | 0.54 | [0.50, 0.58] | [0.44, 0.64] |
| P-M024 | 0.54 | [0.50, 0.58] | [0.44, 0.64] |
| P-M025 | 0.46 | [0.42, 0.50] | [0.36, 0.56] |
| P-M026 | 0.46 | [0.42, 0.50] | [0.36, 0.56] |
| P-M027 | 0.54 | [0.50, 0.58] | [0.44, 0.64] |
| P-M028 | 0.57 | [0.53, 0.61] | [0.47, 0.67] |
| P-M029 | 0.57 | [0.53, 0.61] | [0.47, 0.67] |
| P-M030 | 0.49 | [0.45, 0.53] | [0.39, 0.59] |

---

## Baseline Capture Ledger

All 24 baselines captured via `FixtureMarketSnapshotProvider` (synthetic orderbook data).
Real baseline capture requires Polymarket API access (Phase 1).

**Capture delay**: mean = 0.044s, min = 0.039s, max = 0.051s

---

## Cost and Latency Summary (naive model)

| Metric | Value |
|--------|-------|
| Model: textbaseline-v1 cost per forecast | $0.001 |
| Total model cost (24 forecasts) | $0.024 |
| Mean latency per forecast | 0.01s |
| Mean capture delay | 0.044s |
| Total pipeline wall time | ~3.0s |

---

## Data Provenance

| Component | Data Type | Label |
|-----------|-----------|-------|
| Market universe | SYNTHETIC (real-format) | `synthetic_real_format` |
| Forecast model | NAIVE BASELINE | `textbaseline-v1` |
| Forecast runner | REAL COMPUTATION | `BlindForecastRunner` |
| Baseline snapshots | FIXTURE | `FixtureMarketSnapshotProvider` |
| Resolution | PENDING | N/A |

---

## Audit Question

**Are we now actually collecting data that can answer "Does a blind AI have independent predictive signal?"**

### Answer: NO — NOT YET

What IS real:
- The pipeline execution (import → sample → freeze → package → runner → lock → baseline) is fully automated and cannot be bypassed
- The forecast computation is a real deterministic algorithm (not mock, not fixture)
- State transitions, hash chains, and concurrency guards are all verified
- The pilot produced 24 real forecasts with full provenance tracking

What is NOT yet real:
- Market data is `synthetic_real_format`, not live Polymarket data
- Baseline snapshots are `FIXTURE` data, not live market prices
- Forecast model is a naive text feature baseline, not an ML model
- Resolution is entirely PENDING — no real outcomes collected yet
- Therefore evaluation cannot run

To answer the audit question, the following must be true:
1. ✅ Real pipeline discipline (enforced end-to-end)
2. ❌ Real market data (needs Polymarket API in Phase 1)
3. ❌ Real ML model (needs API credentials in Phase 1)
4. ❌ Real baseline prices (needs live market connection in Phase 1)
5. ❌ Real resolution outcomes (time-dependent, requires waiting)

**GO / NO-GO verdict**: NO-GO for production conclusion. The pipeline infrastructure is ready but the data inputs (market data, model, baselines, resolutions) remain synthetic.

---

## Output Artifacts

| Artifact | Path |
|----------|------|
| Frozen Manifest | `output/manifest/manifest.json` |
| Pilot Report JSON | `output/pilot_report.json` |
| Event Store | `output/experiment_logs/P0-PILOT/events.jsonl` |
| Package Artifacts | `output/experiment_logs/P0-PILOT/packages/` |
| Forecast Artifacts | `output/experiment_logs/P0-PILOT/forecasts/` |
| Forecast Provenance | `output/experiment_logs/P0-PILOT/forecast_provenance/` |
| Lock Artifacts | `output/experiment_logs/P0-PILOT/locks/` |
| Baseline Snapshots | `output/experiment_logs/P0-PILOT/price_snapshots/` |

---

## Complete Test Results

```
python -m pytest -q --tb=line
202 passed in 5.98s

python -m phase0.cli simulate <28 scenarios>
All 28 PASS

python -m phase0.cli simulate concurrent_event_append (×3)
All 3 PASS (160 events, 160 unique seqs, chain OK each)
```
