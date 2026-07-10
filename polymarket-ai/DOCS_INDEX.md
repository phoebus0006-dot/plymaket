# Plymaket Project Documentation Index

This documentation set is the canonical handover and audit baseline for the **Polymarket AI Forecasting System V3.1** implementation in:

- Repository: `https://github.com/phoebus0006-dot/plymaket`
- Main branch: `master`
- Current implementation baseline under review: `3ba56f4`
- Audit disposition at handover: **NOT ACCEPTED / BLOCKERS OPEN**

## Document authority

The authority order is:

1. `01_PRODUCT_REQUIREMENTS.md`
2. `02_SYSTEM_ARCHITECTURE.md`
3. `03_DATA_CONTRACTS_AND_PROVENANCE.md`
4. `04_EXPERIMENT_PROTOCOL.md`
5. `05_STATE_MACHINE_AND_CONCURRENCY.md`
6. `06_TEST_AND_ACCEPTANCE.md`
7. `07_ROADMAP_AND_PROGRESS.md`
8. `08_AUDIT_PLAYBOOK.md`
9. `09_HANDOVER_GUIDE.md`
10. ADRs in `docs/adr/`

If implementation, tests, reports, and documentation disagree, reviewers must use the following evidence order:

`Requirement → Source Code → Diff → Tests → Runtime Evidence → Artifacts → Report`

A report is never sufficient evidence by itself.

## Requirement ID convention

- `PRD-*`: product/research requirements
- `ARCH-*`: architecture requirements
- `DATA-*`: data and provenance requirements
- `EXP-*`: experiment protocol requirements
- `STATE-*`: lifecycle/concurrency requirements
- `TEST-*`: testing and acceptance requirements
- `SEC-*`: security and isolation requirements

Every material code change should map to one or more requirement IDs.

## Current project stage

The project remains in **Phase 0 / Feasibility Probe and Research Integrity Foundation**.

Do not advance to Calibration, MoA, Risk Engine, Execution, Position Sizing, Live Trading, Complex UI, Full Agent Swarm, or Learned Pool until the Phase 0 exit criteria in `07_ROADMAP_AND_PROGRESS.md` are satisfied.
