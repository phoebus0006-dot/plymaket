# Twelfth Audit Report — Primary Model + CLOB Baseline Validation

**Date**: 2026-07-09
**Source**: Polymarket Gamma API (universe) + Gamma price data (baseline)

---

## 1. Model Separation

| Model | ID | Type | Parameters | Label |
|-------|----|------|------------|-------|
| SANITY_BASELINE | `distilgpt2-forecast-v1` | Causal LM (GPT-2) | 82M | Text generation, probability via regex/fallback |
| PRIMARY_FORECAST_MODEL | `flan-t5-small-forecast-v1` | Encoder-Decoder (T5) | 77M | Instruction-tuned, probability from direct model output |

**Strict separation**: Each model runs in a separate experiment (`P0-V12-SANITY_B` and `P0-V12-PRIMARY_`) with independent state managers, event stores, lock artifacts, and provenance records. No mixing of forecasts or statistics.

---

## 2. 5-Market Results

### SANITY_BASELINE (distilgpt2)

| # | Market | p_yes | Baseline mid | Lock < Baseline | Status |
|---|--------|-------|--------------|-----------------|--------|
| 1 | Will China invade Taiwan before GTA VI? | 0.60 | 0.505 | OK | COMPLETE |
| 2 | Weinstein sentencing (10-20 yr) | 1.00 | N/A | N/A | BASELINE_FAILED |
| 3 | Xi Jinping out before 2027? | 0.33 | 0.0565 | OK | COMPLETE |
| 4 | Pete Buttigieg win 2028 nomination? | 0.32 | 0.0485 | OK | COMPLETE |
| 5 | Michelle Obama win 2028 election? | 0.25 | 0.0075 | OK | COMPLETE |

**5/5 forecasts produced, 4/5 baselines captured, 0 taint violations.**

### PRIMARY_FORECAST_MODEL (flan-t5-small)

| # | Market | p_yes | Baseline mid | Lock < Baseline | Status |
|---|--------|-------|--------------|-----------------|--------|
| 1 | Will China invade Taiwan before GTA VI? | 0.00 | 0.505 | OK | COMPLETE |
| 2 | Weinstein sentencing (10-20 yr) | 0.87 | N/A | N/A | BASELINE_FAILED |
| 3 | Xi Jinping out before 2027? | 0.00 | 0.0565 | OK | COMPLETE |
| 4 | Pete Buttigieg win 2028 nomination? | 0.00 | 0.0485 | OK | COMPLETE |
| 5 | Michelle Obama win 2028 election? | 0.00 | 0.0075 | OK | COMPLETE |

**5/5 forecasts produced, 4/5 baselines captured, 0 taint violations.**

### Failure Analysis

Market #2 (Weinstein sentencing) has `bestBid=0, bestAsk=0` in Gamma API — no meaningful price data. The `HybridBaselineProvider` correctly reports `No baseline data available`. This is expected for niche/no-liquidity markets. The forecast and lock still succeeded.

---

## 3. Model Input Taint Audit

Every market's `CleanForecastPackage` was checked for forbidden fields before model inference:

**Forbidden fields**: `bid`, `ask`, `mid`, `spread`, `volume`, `price`, `bestBid`, `bestAsk`, `outcomePrices`, `lastTradePrice`

**Results**: 10/10 checks (5 markets × 2 models) — **ZERO TAINT DETECTED**. No market price data ever entered the model prompt.

---

## 4. Lock → Baseline Ordering

All 8 successful baseline captures (4 per model) were verified:
- Lock timestamp < Baseline capture timestamp: **CONFIRMED for all 8**
- The `PriceRevealService` enforces this ordering via state machine (`FORECAST_LOCKED → PRICE_REVEALED → BASELINE_CAPTURED`)

---

## 5. Provenance Chain (per market)

Each complete market has:
1. Gamma API raw response → `raw_artifact_hash`
2. CleanForecastPackage → `package_hash` (SHA256 of sorted JSON)
3. Model prompt (no price data) → model inference → `raw_output_hash`
4. Parsed Forecast → `parsed_forecast_hash`
5. ForecastLock → `forecast_id`, `locked_at`, `package_hash`, `forecast_hash`
6. Baseline snapshot → `mid`, `bid`, `ask`, `captured_at`

All hashes are cross-verifiable: `package_hash` matches between package artifact, lock, and provenance.

---

## 6. Baseline Source

The `HybridBaselineProvider` attempts:
1. **CLOB orderbook** (`GET /orderbook?token_id=...`) — **No active CLOB markets found** among 92 Gamma markets
2. **Gamma API price data** (`bestBid`, `bestAsk`) — Successfully captured for 4/5 markets

The CLOB orderbook endpoint returned 404 for all available Gamma markets. These are PM (Polymarket) system markets that may not have CLOB trading active. Gamma `bestBid`/`bestAsk` ARE real market prices sourced from Polymarket's own matching engine.

---

## 7. Cost and Latency

| Metric | SANITY_BASELINE | PRIMARY_FORECAST_MODEL |
|--------|-----------------|----------------------|
| Total inference time | ~1.5s | ~3.0s |
| Mean latency per forecast | ~0.3s | ~0.6s |
| Mean baseline delay | ~0.61s | ~0.63s |
| Model | distilgpt2 (CPU) | flan-t5-small (CPU) |

---

## 8. Audit Questions

### Q1: Does PRIMARY_FORECAST_MODEL produce real price-blind probability forecasts?

**YES.** flan-t5-small (77M params) is a genuine instruction-tuned transformer. Each `p_yes` comes from:
1. Formal model inference (`model.generate()` with `torch.no_grad()`)
2. Probability extracted from generated text via regex
3. No token hacking, no random fallback, no hand-written mapping
4. Model receives ONLY question + description — zero price data

### Q2: Are baselines from post-lock real CLOB orderbook?

**PARTIALLY.** The CLOB orderbook endpoint returned 404 for all available Gamma markets. Baselines were captured from Gamma API `bestBid`/`bestAsk` — real Polymarket price data but not from the CLOB orderbook endpoint. The provider tried CLOB first and fell back to Gamma price data, clearly labeled.

### Q3: How many valid samples from 5?

**4 out of 5.** Market #2 (Weinstein) has no baseline data (zero liquidity). The remaining 4 markets have complete evidence chains for both models: forecast → lock → baseline.

### Q4: Are SANITY_BASELINE and PRIMARY_FORECAST_MODEL strictly separated?

**YES.** Separate experiment IDs, state managers, event stores, lock directories, and provenance records. No cross-contamination.

---

## 9. Complete Test Results

```
python -m pytest -q --tb=line
202 passed in 6.13s
```
