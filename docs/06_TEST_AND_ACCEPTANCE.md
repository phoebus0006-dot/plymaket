# Test Strategy and Acceptance Criteria

## 1. Testing philosophy

Test count is not a quality metric.

A component is accepted only when the test exercises the same contracts and data shape as the production path.

## 2. Required test layers

### TEST-001 Unit tests

Cover deterministic helpers and schema validation.

Examples:
- outcome/token mapping;
- canonical hashing;
- version parsing;
- strata assignment;
- transition validation.

### TEST-002 Contract tests

Provider mocks must return the same typed structure as production providers.

A mock that omits provenance fields and therefore bypasses production schema failures is invalid.

### TEST-003 Main-flow regression

At least one test must call the real orchestration entrypoint and exercise:

```text
Gamma raw payload
→ ingestion
→ eligibility
→ reversed outcome mapping
→ manifest
→ package
→ runner
→ lock
→ mock CLOB /book raw response
→ raw orderbook artifact
→ baseline artifact
→ EventStore binding
```

No `except Exception: pass` is permitted in an acceptance test.

### TEST-004 Adversarial tests

Must include:

- nested price taint;
- blocked prediction-market URL;
- manifest tampering;
- baseline-before-lock;
- forged resolution provenance;
- broken hash chain;
- duplicate sequence;
- market identity mismatch;
- forecast mode mismatch;
- malformed outcomes/token arrays;
- reversed outcomes;
- artifact tampering after evaluation.

The test must assert the intended failure reason. A taint test that actually fails earlier on hash mismatch does not count as a taint test.

### TEST-005 Concurrency tests

Multi-process, not only multi-thread, where file locking is relevant.

Required:
- simultaneous first append on nonexistent store;
- same-version forecast lock;
- concurrent baseline capture;
- concurrent reveal;
- concurrent same transition.

Verify:
- single winner;
- chain valid;
- no orphan artifacts.

## 3. Real integration smoke tests

Run separately from deterministic CI where external APIs are involved.

For CLOB:

- use eligible active market;
- verify YES token mapping;
- call `/book`;
- persist raw response;
- verify hash;
- derive price;
- create baseline artifact.

External API failures must be reported as failures or skips with reason, never replaced by fixture data under a real-integration label.

## 4. Evidence matrix

Every audit report should contain:

| Claim | Requirement IDs | Code Evidence | Test Evidence | Runtime Evidence | Artifact Evidence | Status |
|---|---|---|---|---|---|---|

Allowed status:
- NOT_IMPLEMENTED
- IMPLEMENTED_UNTESTED
- TESTED_WITH_FIXTURE
- TESTED_WITH_MOCK
- TESTED_WITH_REAL_DATA
- VERIFIED

`TESTED_WITH_MOCK` must not be presented as production verification.

## 5. Acceptance gates

### Gate A: Code integrity
- no secret committed;
- no hidden fallback;
- no swallowed exceptions on critical path;
- schemas fail closed.

### Gate B: Identity integrity
- market identity consistent end to end;
- forecast mode consistent end to end;
- YES token mapping proven.

### Gate C: Temporal integrity
- lock timestamp before baseline capture;
- resolution after forecast cutoff;
- point-in-time evidence rules satisfied.

### Gate D: Provenance integrity
- raw artifacts persisted;
- hashes match;
- EventStore references artifact hashes;
- tampering detected.

### Gate E: Concurrency integrity
- single-winner transitions;
- no orphan artifacts;
- recovery works.

A phase does not pass until all relevant gates pass.
