# Phase 0 Experiment Protocol

## 1. Objective

Phase 0 asks whether a price-blind AI forecast contains independent probabilistic signal worth further research.

It does not ask whether the full trading system is profitable.

## 2. Pre-registration

### EXP-001 Universe cutoff

Create a point-in-time universe artifact at `selection_cutoff`.

### EXP-002 Deterministic sampling

Run stratified sampling with fixed:
- seed
- rule version
- target count
- cutoff
- universe artifact

Formal target: 20–50 markets.

### EXP-003 Freeze before forecast

No forecast may be generated until the manifest is frozen and verified.

No market may be removed because of forecast quality or model failure.

## 3. Stratification

The formal manifest shall freeze:

- Category
- Horizon
- Rule Complexity
- Liquidity Bucket

Definitions and thresholds must be versioned.

If a dimension cannot be populated from current data, the experiment must be explicitly labeled incomplete rather than pretending to satisfy the design.

## 4. Forecast arms in current phase

### SANITY_BASELINE

Purpose: pipeline smoke test only.

A small local text model may be used, but results must remain separate from the primary experiment.

### PRIMARY_FORECAST_MODEL

Purpose: actual price-blind probability forecasting.

Minimum validity checks:
- schema compliance;
- parse reliability;
- non-degenerate probability spread;
- semantic sensitivity;
- no fallback probability generation.

## 5. Forecast protocol

For each selected market:

1. verify manifest membership;
2. build clean package;
3. validate package hash;
4. run recursive taint audit;
5. execute primary model in blind context;
6. parse forecast;
7. save raw output hash;
8. create forecast artifact;
9. durable lock;
10. verify lock.

Only after step 10 may market price data be read.

## 6. Baseline protocol

Formal executable baseline:

`Forecast Lock → Verify Lock → YES Token Mapping → CLOB /book`

Gamma reference prices may be saved as separate reference data but must be labeled:

`GAMMA_REFERENCE_PRICE`

They must not be counted as:

`CLOB_ORDERBOOK`

No silent fallback is allowed.

## 7. Failure statuses

At minimum:

```text
SELECTED
PACKAGE_FAILED
MODEL_CALL_FAILED
MODEL_PARSE_FAILED
FORECAST_LOCKED
BASELINE_CAPTURE_FAILED
BASELINE_CAPTURED
PENDING
RESOLVED_VALID
RESOLUTION_DISPUTED
PIPELINE_FAILED
EVALUATED
```

First failures must remain visible.

## 8. Evaluation

### Forecast quality
- Brier Score
- Log Loss
- Extreme Error Count
- Probability Spread
- Directional Discrimination
- Calibration bins/reliability diagram when sample size permits

### Research reliability
- Rules Fatal Error Rate
- Unsupported Claim Rate
- Fact Hallucination Rate
- Temporal Leakage Rate

### Engineering feasibility
- Median latency
- Cost per forecast
- Failure rate
- Manual intervention rate

### Market-relative signal
- AI Brier versus market baseline
- AI Log Loss versus market
- gap direction accuracy
- baseline coverage
- baseline capture delay

## 9. GO / NO-GO discipline

Do not declare GO because:
- 30 forecasts were generated;
- tests passed;
- a model call was real;
- one model beat a handful of markets;
- paper P&L is positive.

GO requires enough resolved real samples to evaluate:
- no catastrophic systematic forecast failure;
- manageable reliability errors;
- acceptable latency/cost;
- credible market-relative signal worth deeper testing.

## 10. Point-in-time integrity

Historical backtests require evidence snapshots valid at the forecast cutoff.

Reading today's updated webpage to reconstruct a historical forecast is `TEMPORALLY_UNSAFE` and must not enter formal benchmark results.
