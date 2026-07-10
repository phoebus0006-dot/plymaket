# Handover Guide for Codex, OpenCode, or Human Maintainer

## 1. Read order

A new maintainer should read:

1. `DOCS_INDEX.md`
2. `01_PRODUCT_REQUIREMENTS.md`
3. `02_SYSTEM_ARCHITECTURE.md`
4. `03_DATA_CONTRACTS_AND_PROVENANCE.md`
5. `04_EXPERIMENT_PROTOCOL.md`
6. `05_STATE_MACHINE_AND_CONCURRENCY.md`
7. `06_TEST_AND_ACCEPTANCE.md`
8. `07_ROADMAP_AND_PROGRESS.md`
9. `08_AUDIT_PLAYBOOK.md`

Then inspect the repository code.

## 2. First commands

```bash
git status
git branch --show-current
git log --oneline --decorate -10
git rev-parse HEAD
```

Then identify the diff range since the last accepted audit baseline.

## 3. Do not trust status reports

Developer output such as:

- “all requirements complete”;
- “202 tests passed”;
- “E2E passed”;
- “real CLOB integrated”;

must be independently verified.

## 4. Required reviewer record

For every audit round, record:

```text
Audit round:
Repository:
Branch:
Reviewed SHA:
Parent/baseline SHA:
Review type: STATIC / TESTED / LIVE-SMOKE
Accepted requirement IDs:
Rejected requirement IDs:
Blocking issues:
High priority issues:
Test commands executed:
Runtime artifacts inspected:
Next action:
```

Store this in `docs/audits/` if the project chooses to preserve audit notes.

## 5. Documentation update policy

The executor may update documentation only when:

- requirement meaning changes;
- architecture contract changes;
- acceptance criteria changes;
- verified progress changes.

Do not rewrite requirements merely to make current code pass.

Any scope change should be documented in an ADR.

## 6. Commit discipline

Recommended workflow:

1. implement one audit scope;
2. run tests;
3. secret scan;
4. commit;
5. push;
6. stop;
7. reviewer audits exact SHA.

No force-push of reviewed history.

## 7. Definition of done

A feature is done only when:

- requirement exists;
- production path implements it;
- tests exercise production-equivalent contract;
- runtime evidence exists where required;
- artifacts are auditable;
- reviewer accepts it.

## 8. Current handover status

At the time this documentation set was created:

- current known implementation baseline: `3ba56f4`;
- audit17 was not accepted;
- the next executor should continue from `07_ROADMAP_AND_PROGRESS.md` blockers and verify current master before coding.

Do not assume the repository has not changed after this document was created. Always refresh branch and SHA first.
