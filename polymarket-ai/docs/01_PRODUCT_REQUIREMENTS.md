# Product and Research Requirements

## 1. Purpose

The system exists to test a narrow research question:

> Can an AI system produce probability forecasts with independent informational value when market prices and prediction-market signals are hidden from the forecasting process?

The system is not primarily an automated betting bot. Its first duty is to produce a clean experiment that can honestly prove or disprove the existence of independent forecasting signal.

## 2. Product goals

### PRD-001 Independent blind forecast

The system shall generate a `p_yes` probability without exposing the forecast model or research plane to:

- current price
- bid
- ask
- midpoint
- spread
- volume
- price history
- orderbook
- betting odds
- trader positions
- prediction-market commentary

Acceptance requires code-level enforcement, not prompt-only instructions.

### PRD-002 Forecast immutability

Once a forecast is locked, it shall not be modified.

New information may create Forecast V2, but Forecast V1 remains immutable and auditable.

### PRD-003 Forecast versus market comparison

The system shall capture the market baseline only after durable forecast lock and shall preserve evidence that proves ordering.

### PRD-004 Pre-registered sample

The experiment sample must be selected and frozen before forecasts begin.

The manifest must contain 20–50 markets for a formal Phase 0 run and must be reproducible from:

- universe artifact
- selection cutoff
- selection rule version
- deterministic seed
- strata assignment logic

### PRD-005 Four-dimensional stratification

Formal Phase 0 sampling shall use and freeze:

- Category
- Horizon
- Rule Complexity
- Liquidity Bucket

A field may be `UNKNOWN` only when the data source cannot supply it and the limitation is explicitly recorded. An experiment may not claim full four-dimensional stratification when a dimension is effectively constant or unknown for all samples.

### PRD-006 Honest failure retention

Pipeline failures shall remain in the experiment record.

The system must not:
- delete failed markets;
- silently replace them;
- backfill probabilities;
- use fixture baselines when live capture fails;
- hide first failures by rerunning only failed samples.

### PRD-007 Resolution integrity

Only resolutions with auditable provenance may enter formal evaluation.

Valid states include:

- `PENDING`
- `RESOLVED_VALID`
- `RESOLUTION_DISPUTED`
- `TEMPORALLY_INVALID`
- `MISSING_PROVENANCE`

### PRD-008 Evaluation scope

Phase 0 evaluation shall cover four dimensions:

1. Forecast quality
2. Research reliability
3. Engineering feasibility
4. Market-relative signal

A single Brier Score, win rate, or paper ROI is not sufficient for a GO decision.

## 3. Non-goals for current phase

The following are explicitly out of scope until Phase 0 exits:

- live trading
- automated position sizing
- portfolio risk engine
- MoA aggregation
- probability calibration service
- learned model pooling
- execution optimization
- HFT or news-shock competition
- complex UI
- full agent swarm
- vector database unless justified by a later phase requirement

## 4. Phase 0 success question

The current system must answer:

> Has data collection begun that can validly compare a price-blind AI forecast against a post-lock market baseline for the same pre-registered market?

The answer may be `YES` only when all of the following exist for a sample:

1. real source market identity;
2. frozen manifest membership;
3. validated clean package;
4. real model inference;
5. parsed probability from the model's forecast output;
6. durable lock;
7. verified lock;
8. correct YES token mapping;
9. post-lock market baseline;
10. provenance artifacts and hash bindings.

## 5. Model validity requirement

A model call is not automatically a meaningful forecast.

A primary forecast model must demonstrate at least:

- stable schema compliance;
- no synthetic/hash-based probability fallback;
- probability spread across heterogeneous questions;
- reasonable reaction to semantic inversion;
- explicit distinction from sanity baselines.

Small local models may be used as `SANITY_BASELINE`, but must not be mislabeled as evidence of production-grade forecasting ability.
