# Code Audit Playbook

## 1. Reviewer posture

Assume an execution model may:

- say it implemented something without wiring it into the real path;
- add a helper but leave the production caller unchanged;
- name a test “E2E” while using a different data structure;
- swallow exceptions;
- use fallback values;
- report mock results as real;
- increase test counts without testing the critical path;
- write a report that does not match code.

The purpose of audit is to detect these patterns.

## 2. Review sequence

For every update:

1. obtain branch and full commit SHA;
2. inspect commit history;
3. identify the full diff range, including parent commits;
4. inspect source changes;
5. trace the real entrypoint;
6. inspect tests for path equivalence;
7. run tests when environment allows;
8. inspect runtime artifacts;
9. only then read reports.

## 3. Real-path tracing checklist

Trace from:

`run_real_pilot()`

Verify each edge:

- source client actually called;
- normalized record preserves required fields;
- eligibility enforced;
- YES token mapping used;
- selected market enters frozen manifest;
- manifest entry preserves strata;
- PRIMARY package mode set;
- Runner validates artifact;
- model output parsed without fallback;
- forecast artifact written;
- lock cross-checks artifact;
- lock verified before price read;
- actual YES token sent to `/book`;
- provider result mapped into schemas correctly;
- raw response persisted;
- raw hash enters baseline artifact;
- baseline artifact hash enters EventStore.

If any edge is only implemented in a helper that is not called, the requirement is not complete.

## 4. High-risk code smells

Search for:

```text
except Exception:
    pass
```

or broad catch returning success.

Search for:

- `fallback`
- `hash` near probability creation
- `random`
- fixture usage in real path
- Gamma price fallback in CLOB path
- `token_ids[0]`
- forecast ID parsing used as token identity
- hard-coded cutoff dates
- default CHEAP mode in PRIMARY path
- file writes before state guard
- read-state then append outside one lock

## 5. Test authenticity questions

For each acceptance test:

- Does it call the production entrypoint?
- Does the mock return the real provider schema?
- Can a production-only extra field cause failure not represented by the mock?
- Does the test assert the intended error reason?
- Can a stage fail while the test still passes?
- Are runtime artifacts inspected, not only return values?

## 6. Audit output format

Use:

### Accepted fixes
Only items proven by code/test/runtime evidence.

### Blocking issues
Issues that invalidate the experiment or main path.

### High priority issues
Issues that weaken reliability but do not fully invalidate the path.

### Verification limitations
State clearly whether review was:
- static only;
- tests executed locally;
- real API smoke-tested.

### Next executor instruction
Keep it concise:
- target;
- exact blockers;
- required tests;
- commit message;
- stop-after-push rule.

## 7. Anti-lying evidence rule

Every claim should be linked to:

`Claim → Requirement ID → Code → Test → Runtime Evidence → Artifact`

Missing evidence means `UNVERIFIED`, not PASS.
