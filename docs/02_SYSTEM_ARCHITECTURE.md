# System Architecture

## 1. Architectural principles

### ARCH-001 Plane separation

The architecture is separated into:

1. **Market Data Plane**
   - Gamma market discovery
   - CLOB token/orderbook data
   - baseline capture
   - market regime data in later phases

2. **Research Plane**
   - rules interpretation
   - evidence collection
   - base rate work
   - contrarian analysis
   - clean forecast package generation

3. **Forecast Plane**
   - isolated runner
   - primary forecast model
   - sanity baseline
   - forecast artifact creation
   - durable lock

4. **Evaluation Plane**
   - resolution provenance
   - forecast metrics
   - market-relative comparison
   - reliability and cost metrics

Market signals may move from the Market Data Plane into the Evaluation Plane only after forecast lock. They must not enter Research or Forecast inputs.

## 2. Phase 0 reference flow

The canonical Phase 0 flow is:

```text
Real Market Source
    ↓
Market Universe Ingestion
    ↓
Eligibility Classification
    ↓
Deterministic Stratified Sampling
    ↓
Manifest Freeze + Hash
    ↓
Clean Package Construction
    ↓
Package Validation + Taint Audit
    ↓
Blind Forecast Runner
    ↓
Forecast Artifact
    ↓
Durable Forecast Lock
    ↓
Lock Verification
    ↓
YES Token Mapping
    ↓
CLOB /book Capture
    ↓
Raw Orderbook Artifact
    ↓
Baseline Artifact
    ↓
EventStore Hash Binding
    ↓
Resolution Provenance
    ↓
Audit
    ↓
Evaluation
```

Any implementation path that bypasses a step is non-compliant.

## 3. Core components

### ARCH-010 Market ingestion

Responsibilities:

- fetch market universe from real source;
- preserve raw source artifact;
- normalize records;
- save source identity and retrieval time;
- preserve market identity fields;
- preserve `active`, `closed`, `enableOrderBook`, `acceptingOrders`;
- preserve `outcomes` and `clobTokenIds`.

### ARCH-011 Market eligibility

Formal CLOB pilot eligibility must require:

- `active == true`
- `closed == false`
- `enableOrderBook == true`
- `acceptingOrders == true`
- unique valid YES token mapping

An ineligible market must be recorded with an exclusion reason.

### ARCH-012 Sampling service

Inputs:

- normalized universe
- selection cutoff
- rule version
- seed
- target count
- strata classification rules

Output:

- exact selected market IDs
- frozen strata fields
- inclusion/exclusion reasons
- reproducibility metadata
- manifest hash

### ARCH-013 Package builder

Produces a `PackageArtifact` containing:

- market identity
- question
- description
- resolution rules/logic
- permitted research context
- temporal cutoff
- forecast mode
- package hash

The package must not contain market signals.

### ARCH-014 Blind forecast runner

The runner must:

1. accept only validated PackageArtifact input;
2. recursively validate taint and blocked sources;
3. verify package hash;
4. verify market identity;
5. verify requested mode equals package mode;
6. call the model provider;
7. verify returned market identity;
8. verify returned mode;
9. reject parse failures;
10. produce immutable forecast artifact.

### ARCH-015 Forecast lock

Lock creation must validate:

- argument market ID matches forecast;
- argument mode matches forecast;
- disk forecast artifact matches in-memory forecast;
- canonical hash matches;
- cutoff is valid;
- version ordering is numeric and monotonic.

### ARCH-016 CLOB provider

The CLOB provider shall query:

`GET /book?token_id=<YES_TOKEN_ID>`

It shall not use a Gamma price field as a substitute for an executable baseline.

The provider result must be typed and include provenance fields.

### ARCH-017 Price reveal service

The service shall:

- require verified forecast lock;
- retrieve the correct YES token orderbook;
- persist raw orderbook evidence;
- derive price fields;
- create BaselineArtifact;
- bind artifact hash into EventStore;
- guarantee concurrency safety.

### ARCH-018 EventStore

EventStore is the append-only experiment history.

It must provide:

- monotonic sequence numbers;
- hash chain;
- experiment identity consistency;
- market identity consistency;
- atomic guarded transitions;
- restart/recovery validation;
- tamper detection.

## 4. Isolation requirements

### SEC-001 Tool isolation

Forecast model must not have access to market price APIs or prediction-market browsing tools.

### SEC-002 Input isolation

Even if the model has no tools, the input artifact must be recursively checked for tainted fields and blocked URLs/domains.

### SEC-003 Context isolation

The formal forecast should execute in a fresh isolated context. Parent processes that have seen market prices must not modify the model probability after the call.

### SEC-004 Fail closed

On identity mismatch, hash mismatch, taint detection, parse failure, CLOB mapping failure, provenance failure, or illegal state transition, the system shall stop that sample and record failure. No fallback may silently turn failure into success.
