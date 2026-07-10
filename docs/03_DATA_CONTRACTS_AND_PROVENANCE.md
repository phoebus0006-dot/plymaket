# Data Contracts and Provenance

## 1. General rule

Every probability, baseline, and evaluation record must have identity and provenance.

A plain value such as `p_yes = 0.63` is insufficient.

## 2. MarketUniverseRecord

Required fields:

```text
market_id
question
description
resolution_rules
close_time
category
active
closed
enable_order_book
accepting_orders
outcomes
clob_token_ids
source
retrieved_at
raw_artifact_hash
parser_version
normalized_artifact_hash
```

### DATA-001 Market identity

`market_id` must be stable and must match through:

Universe → Manifest → Package → Forecast → Lock → Baseline → Resolution.

### DATA-002 Outcomes/token mapping

`outcomes` and `clobTokenIds` may arrive as JSON strings or arrays.

Normalization must:
- parse both forms;
- reject malformed inputs;
- reject length mismatch;
- find exactly one YES outcome;
- map YES by index to its token ID;
- never assume token index 0 means YES.

The mapping artifact must be hashed.

## 3. ManifestEntry

Required:

```text
market_id
question
category
horizon_bucket
rule_complexity
liquidity_bucket
inclusion_reason
source_record_hash
```

Manifest-level metadata:

```text
experiment_id
created_at
selection_cutoff
selection_rule_version
sampling_strategy
seed
exclusion_rules
universe_artifact_hash
manifest_hash
```

## 4. PackageArtifact

Required identity:

```text
market_id
forecast_mode
cutoff
package
package_hash
builder_version
created_at
```

Package validation must be recursive. Hash verification alone does not replace taint validation.

## 5. ForecastArtifact

Required:

```text
forecast_id
forecast_version
market_id
forecast_mode
forecast_cutoff
p_yes
interval_50
interval_80
confidence
top_drivers
strongest_counterarguments
critical_unknowns
forecast_reversal_conditions
model_id
model_version
provider
prompt_version
runner_version
request_timestamp
raw_output_hash
parsed_forecast_hash
latency_seconds
cost
```

### DATA-010 Probability origin

`p_yes` must come from a parsed model forecast output.

Forbidden:
- hash-to-probability mapping;
- random fallback;
- token probability hack not defined by experiment protocol;
- handwritten replacement probability;
- fixture probability in real experiment.

Parse failure must become `PIPELINE_FAILED`.

## 6. ForecastLock

Required:

```text
forecast_id
forecast_version
market_id
forecast_mode
forecast_cutoff
forecast_artifact_hash
package_hash
raw_probability
calibrated_probability
locked_at
```

Phase 0 may leave calibrated probability null.

## 7. CLOBBookArtifact

Required:

```text
market_id
token_id
outcome_side
endpoint
captured_at
raw_response_path
raw_response_hash
best_bid
best_ask
midpoint
spread
mapping_artifact_hash
```

The raw response must be persisted before it can be referenced.

## 8. BaselineArtifact

Required:

```text
baseline_id
market_id
forecast_id
forecast_version
token_id
outcome_side
best_bid
best_ask
midpoint
spread
captured_at
capture_delay_seconds
endpoint
raw_orderbook_hash
mapping_artifact_hash
artifact_hash
```

### DATA-020 Baseline identity

Token ID must come from the actual CLOB request result. It must never be inferred from forecast ID text.

### DATA-021 Artifact binding

The BaselineArtifact hash must be stored in the EventStore event.

Modifying:
- raw orderbook;
- mapping artifact;
- baseline artifact

must cause verification failure.

## 9. ResolutionRecord

Required provenance:

```text
market_id
outcome
resolution_status
resolution_source
source_retrieved_at
source_published_at
resolved_at
resolution_recorded_at
resolver_version
evidence_hash
resolution_confidence
manual_intervention
```

Only `RESOLVED_VALID` with complete provenance may enter formal scoring.

## 10. Hashing rules

Use canonical serialization before hashing.

Hash chain guarantees tamper evidence, not cryptographic non-repudiation against an attacker with authority to rewrite the entire repository and all external evidence. Documentation and reports must not overclaim.
