# Roadmap and Progress Baseline

## 1. Purpose

This document is the handover progress ledger. Update it only after code and runtime evidence are reviewed.

## 2. Phase roadmap

### Phase 0 — Feasibility Probe
Goal: determine whether price-blind AI forecasting has enough independent signal to justify further investment.

Status: **IN PROGRESS**

### Phase 1 — Research Integrity Foundation
Target:
- research firewall;
- source filtering;
- evidence schema;
- snapshot store;
- historical event schema;
- taxonomy v1.

Status: **NOT STARTED as a formal phase**

Some supporting code may exist, but the phase must not be declared complete until Phase 0 integrity gates are accepted.

### Phase 2 — Research Pipeline
Rules Agent, Evidence Agent, De-noise, Base Rate, Contrarian, Verifier.

Status: NOT STARTED.

### Phase 3 — Forecast Experiments
Market Only, Cheap Baseline, Normal, Reference Models, Equal Pool, Aggregator.

Status: NOT STARTED.

### Phase 4 — Calibration
Status: NOT STARTED.

### Phase 5 — Execution Research
Status: NOT STARTED.

### Phase 6 — Learned Decision Systems
Status: NOT STARTED.

## 3. Current code baseline

Repository:
`https://github.com/phoebus0006-dot/plymaket`

Implementation baseline under review:
`3ba56f4`

Audit disposition:
**NOT ACCEPTED**

Reason: static review found unresolved main-path integration and provenance concerns after audit17.

## 4. Known audit17 blockers at handover

The next reviewer must verify the current master rather than assuming this list remains current.

### BLOCKER-017-01 CLOB result/schema integration
Check whether the real CLOB provider's typed/provenance fields are compatible with PriceRevealService and PriceSnapshot schemas.

### BLOCKER-017-02 Real Pilot YES token use
Check whether `run_real_pilot()` uses the validated `yes_token_id`, not `clob_token_ids[0]`.

### BLOCKER-017-03 Baseline token provenance
Check whether token ID is taken from the actual CLOB request, never inferred from forecast ID text.

### BLOCKER-017-04 Raw orderbook persistence
Check that the real Pilot configures persistence of raw `/book` responses and binds their hashes.

### BLOCKER-017-05 E2E test authenticity
Check that E2E tests:
- invoke real orchestration path;
- use production-shaped provider result;
- do not swallow model exceptions;
- assert every stage.

### BLOCKER-017-06 Manifest strata preservation
Check that Category, Horizon, Rule Complexity, Liquidity Bucket are saved into the frozen manifest.

### BLOCKER-017-07 Package mode identity
Check that PRIMARY PackageArtifact uses PRIMARY mode and Runner verifies package/request/returned/lock mode consistency.

### BLOCKER-017-08 Reveal atomicity
Check that concurrent losers do not leave orphan snapshot/raw/baseline artifacts.

## 5. Phase 0 exit criteria

Phase 0 engineering readiness requires all:

- real market universe provenance;
- deterministic 20–50 market manifest;
- frozen four-dimensional strata;
- primary forecast model proven capable of schema-compliant probability output;
- price-blind input path;
- forecast artifact and durable lock;
- verified lock-before-price ordering;
- correct YES token mapping;
- real CLOB orderbook baseline;
- raw orderbook artifact persistence;
- baseline hash binding;
- resolution provenance path;
- transactional state mutation;
- restart recovery;
- tamper detection;
- authentic main-flow E2E test;
- adversarial tests;
- concurrency single-winner tests.

Phase 0 scientific conclusion additionally requires enough resolved real samples to evaluate forecast and market-relative metrics.

## 6. Progress update rule

A task moves to DONE only when the reviewer records:

```text
Requirement IDs:
Commit SHA:
Code evidence:
Test evidence:
Runtime evidence:
Artifact evidence:
Reviewer verdict:
```

Developer self-report is not sufficient.
