# Requirement Traceability Matrix

| ID | Requirement | Primary Doc | Acceptance Evidence | Current Status |
|---|---|---|---|---|
| PRD-001 | Price-blind forecast | Product Requirements | taint tests + runner path | PARTIAL / VERIFY |
| PRD-002 | Immutable locked forecast | Product Requirements | lock tests + tamper tests | PARTIAL / VERIFY |
| PRD-003 | Lock before baseline | Product Requirements | event timestamps + main-flow test | PARTIAL / VERIFY |
| PRD-004 | Pre-registered sample | Experiment Protocol | frozen manifest + reproducibility | PARTIAL / VERIFY |
| PRD-005 | Four-dimensional strata | Product Requirements | manifest fields + deterministic sampler | OPEN |
| PRD-006 | Failure retention | Experiment Protocol | failure ledger | PARTIAL / VERIFY |
| PRD-007 | Resolution provenance | Data Contracts | resolution schema + evaluation gate | PARTIAL / VERIFY |
| ARCH-011 | CLOB eligibility | Architecture | eligibility tests + real path | OPEN |
| ARCH-014 | Runner validation | Architecture | artifact/mode/market checks | PARTIAL / VERIFY |
| ARCH-015 | Lock cross-check | Architecture | mismatch rejection tests | PARTIAL / VERIFY |
| ARCH-016 | Correct CLOB /book | Architecture | provider test + integration smoke | PARTIAL / VERIFY |
| DATA-002 | YES token mapping | Data Contracts | reversed outcomes real-path test | OPEN |
| DATA-010 | No synthetic probability fallback | Data Contracts | parse-failure test | PARTIAL / VERIFY |
| DATA-021 | Baseline artifact binding | Data Contracts | raw hash → baseline → event | OPEN |
| STATE-001 | Atomic guarded mutation | State Machine | multiprocess single-winner | PARTIAL / VERIFY |
| STATE-010 | No orphan artifacts | State Machine | concurrent reveal artifact count | OPEN |
| TEST-003 | Authentic main-flow E2E | Test Strategy | production orchestration regression | OPEN |
| TEST-004 | Adversarial coverage | Test Strategy | intended-error assertions | PARTIAL / VERIFY |
| TEST-005 | Multiprocess concurrency | Test Strategy | repeatable stress tests | PARTIAL / VERIFY |

Status meanings:

- `OPEN`: known requirement not yet accepted.
- `PARTIAL / VERIFY`: some implementation exists but must be independently reviewed.
- `DONE`: reviewer-accepted with evidence. Do not mark DONE from executor self-report alone.
