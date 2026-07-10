# State Machine, Durability, and Concurrency

## 1. Canonical lifecycle

Recommended market lifecycle:

```text
CREATED
→ MANIFEST_FROZEN
→ PACKAGE_READY
→ FORECAST_LOCKED
→ PRICE_REVEALED
→ BASELINE_CAPTURED
→ PENDING
→ RESOLVED
→ AUDITED
→ EVALUATED
```

Some implementations may separate experiment state and market state. The transition semantics must remain explicit and versioned.

## 2. Transaction rule

### STATE-001 Guarded mutation

Every mutation with a state precondition must execute atomically:

```text
acquire lock
→ read current state
→ validate transition
→ validate identity/hash preconditions
→ append event
→ fsync/commit
→ release lock
```

A read-then-later-append sequence outside a single lock is non-compliant.

## 3. Single-winner requirements

Concurrency tests must prove single winner for:

- same forecast version lock;
- same baseline capture;
- same state transition;
- same price reveal;
- first EventStore append when file does not exist.

The loser must fail deterministically.

## 4. Artifact atomicity

### STATE-010 No orphan artifacts

A failed state transition must not leave committed artifacts that appear valid.

Price reveal requires careful ordering.

Acceptable strategies include:

1. transaction reservation event first, write artifacts, finalize event; or
2. write into temporary path, guarded transition, atomic rename on success; or
3. transactional storage with rollback.

The invariant is:

> A concurrency loser must not leave a committed snapshot, raw CLOB artifact, or BaselineArtifact.

## 5. EventStore invariants

Every event shall include:

```text
seq
experiment_id
event_type
market_id when applicable
timestamp
payload
prev_hash
event_hash
```

Verification must check:

- strictly increasing unique sequence numbers;
- previous-hash linkage;
- event hash correctness;
- experiment_id consistency;
- embedded market_id consistency;
- legal lifecycle transitions.

## 6. Restart recovery

After process interruption and restart:

- event count remains consistent;
- hash chain verifies;
- duplicate logical event is rejected;
- state is reconstructed from durable events;
- pending temporary artifacts are either recovered or safely removed;
- no probability or market baseline is silently regenerated.

## 7. Tamper detection

After evaluation, modification of any critical artifact shall be detectable:

- manifest
- package
- forecast artifact
- forecast lock
- raw orderbook artifact
- BaselineArtifact
- resolution artifact

A later mutation or explicit verification must fail closed when the chain is broken.

## 8. Versioning

Forecast version comparison must be numeric, not lexical.

Correct:
`v10 > v9`

Incorrect:
lexical sorting that places `v10 < v9`.
