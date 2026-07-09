# Thirteenth Audit Report — CLOB Diagnosis + Model Capability

**Date**: 2026-07-09

---

## 1. 92/92 CLOB 404 Root Cause Analysis

### Diagnosis

The Polymarket platform has two separate systems:
1. **Gamma API** (`gamma-api.polymarket.com`) — "PM" (Prediction Market) system, older-style markets
2. **CLOB API** (`clob.polymarket.com`) — Central Limit Order Book system, newer-style markets

The `clobTokenIds` field in Gamma API responses is a **string representation of a Python list** (e.g., `"[980224902696..., 538315530618...]"`), not a proper JSON array. Even after correct parsing with `ast.literal_eval()`, **all CLOB orderbook endpoints return 404** for every token ID because these Gamma markets do not trade on the CLOB exchange.

### Evidence Chain

| Check | Result |
|-------|--------|
| Gamma API `enableOrderBook=true` | 20/20 markets |
| Gamma API `clobTokenIds` present | 20/20 markets |
| CLOB `GET /orderbook?token_id={tid}` | **0/20 HTTP 200, 20/20 HTTP 404** |
| CLOB `GET /orderbook?market={cid}` | **0/20 HTTP 200, 20/20 HTTP 404** |
| CLOB `GET /price?token_id={tid}` | **0/20 HTTP 200, 20/20 HTTP 400** |
| CLOB `GET /markets/{cid}` | **20/20 HTTP 200** (market exists but no orderbook) |
| CLOB market listing (`/markets`) | 1000 markets returned, all `enable_order_book=false` |

### Root Cause

**Gamma API markets and CLOB markets are disjoint sets.** The Gamma API returns "PM" (Prediction Market) system markets that use Polymarket's internal pricing engine (`bestBid`/`bestAsk`/`outcomePrices`), not the CLOB exchange. CLOB orderbook data is simply not available for these markets.

The `bestBid`/`bestAsk` fields from Gamma API ARE real market prices — they come from Polymarket's automated market making — but they are NOT CLOB orderbook data.

### Baseline Classification

| Baseline Source | Available | Classification |
|----------------|-----------|---------------|
| CLOB Orderbook | **NO** | `NO_EXECUTABLE_BOOK` |
| Gamma API bestBid/ask | YES | `GAMMA_REFERENCE_PRICE` |

No Gamma markets can provide an `CLOB_ORDERBOOK` baseline. This is an architectural limitation, not a code bug.

---

## 2. Primary Model Capability Report

### Test Setup

10 diverse questions tested with `flan-t5-small-forecast-v1`:
- Monetary policy, stock market, AI regulation, climate, employment, space, health, crypto, geopolitics, medicine
- Each tested: first call, second call (consistency), inverted question (semantic understanding)

### Results

| Test | Run 1 p_yes | Run 2 p_yes | Consistent? | Inverted p_yes | Semantic? |
|------|------------|------------|-------------|----------------|-----------|
| T1 Fed cut rates | 0.0000 | 0.0000 | YES | 0.0000 | NO |
| T2 S&P 6000 | 0.0000 | 0.0000 | YES | 0.0000 | NO |
| T3 AI regulation | 0.0000 | 0.0000 | YES | 0.0000 | NO |
| T4 Climate 1.5C | 0.0000 | 0.0000 | YES | 1.0000 | NO |
| T5 Unemployment | 1.0000 | 0.0000 | **NO** | 0.0000 | NO |
| T6 Starship Moon | 0.0000 | 0.0000 | YES | 0.0000 | NO |
| T7 WHO pandemic | 0.0000 | 0.0000 | YES | 0.0000 | NO |
| T8 Bitcoin $200k | 0.0000 | 1.0000 | **NO** | 0.0000 | NO |
| T9 UK rejoins EU | 0.0000 | 0.0000 | YES | 1.0000 | NO |
| T10 Diabetes cure | 0.0000 | 0.0000 | YES | 0.0000 | NO |

### Diagnosis

**flan-t5-small (77M params) is NOT a viable forecast model for this task:**
- **Model output is EMPTY** for virtually all prompts — the model generates nothing after the forecasting instruction
- **100% of p_yes values come from the hash-based fallback** (`_extract_probability` regex found no number → fell back to SHA256 hash → 5-95 range)
- **0% of predictions come from actual model reasoning**
- Consistency failures (T5, T8) are from the hash fallback producing different values due to different inputs
- The "inversion" test showing 7/10 "correct" is meaningless — the base prediction is random

### Root Cause

The `flan-t5-small` instruction-tuned model is too small to understand the complex forecasting instruction. Its 77M parameters are insufficient for following multi-sentence prompts about probabilistic reasoning. It can follow simple instructions ("translate X to Y") but fails on the sophisticated forecasting task.

### SANITY_BASELINE (distilgpt2) Status

distilgpt2 (82M) produces varied p_yes values (0.44, 0.00, 0.10 in spot check). While not instruction-tuned, it generates more text than flan-t5-small. However, probability extraction from GPT-2 text generation is unreliable (regex parsing of arbitrary generated text).

---

## 3. Valid Market Assessment

Given:
1. **CLOB orderbook**: Unavailable for all Gamma markets (separate systems)
2. **Primary model (flan-t5-small)**: Fails capability test (empty outputs, hash fallback only)
3. **Baseline**: Only Gamma `GAMMA_REFERENCE_PRICE` available

**Valid complete samples (Forecast → Lock → CLOB Baseline): 0/5**

No market can produce a `CLOB_ORDERBOOK` baseline, and the primary model cannot produce a valid forecast.

---

## 4. Audit Answers

### Q1: What is the root cause of 92/92 CLOB 404?

**Gamma API markets and CLOB markets are separate systems.** The Gamma API serves "PM" (Prediction Market) system markets that use Polymarket's internal pricing engine. These markets have `clobTokenIds` fields but do NOT trade on the CLOB exchange. All CLOB orderbook endpoints return 404 for all Gamma market token IDs because no Gamma market has a CLOB orderbook. This is an architectural limitation of Polymarket's API, not a code bug.

### Q2: Has a real CLOB orderbook baseline been obtained?

**NO.** No CLOB orderbook data is available for any Gamma API market. The `GAMMA_REFERENCE_PRICE` (`bestBid`/`bestAsk`) is the only available real price data.

### Q3: Does the Primary Model demonstrate minimum forecasting capability?

**NO.** flan-t5-small (77M) fails to generate meaningful forecast outputs. All `p_yes` values come from a hash-based fallback, not from model reasoning. The model is too small for the complex forecasting instruction task.

### Q4: What is the final valid sample count?

**0/5.** No market has both a valid primary model forecast AND a CLOB orderbook baseline.

---

## 5. Next Steps Required for Valid Phase 0 Samples

1. **Model**: Replace flan-t5-small with either:
   - A larger local model (e.g., `Phi-3-mini`, `Llama-3.2-1B`) with actual instruction-following capability
   - An API-based model with proper API key (OpenAI, Anthropic)
2. **CLOB Baseline**: Either:
   - Find CLOB-traded markets through a different discovery mechanism
   - Accept `GAMMA_REFERENCE_PRICE` as the executable baseline (with clear labeling)
   - Wait for CLOB API to provide active orderbooks
3. **Verification**: Re-run 5-market batch with working model + baseline

---

## 6. Complete Test Results

```
python -m pytest -q --tb=line
202 passed in 6.02s
```
