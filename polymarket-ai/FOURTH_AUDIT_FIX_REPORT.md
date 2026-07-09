# Fourth Audit Fix Report — Phase 0

## Test Results

```
$ python -m pytest -q --tb=short
149 passed in 3.30s
```

```
$ python -m phase0.cli simulate <each_scenario>
All 28 scenarios PASS
```

```
$ python -m phase0.cli simulate concurrent_event_append (×3)
PASS: 160 events, 160 unique seqs, chain OK
PASS: 160 events, 160 unique seqs, chain OK
PASS: 160 events, 160 unique seqs, chain OK
```

---

## Issue Fix Summary

| # | Issue | Fix Location | Description |
|---|-------|-------------|-------------|
| 1 | EventStore multi-process concurrency | `state.py` | Replaced `threading.Lock` with `fcntl.flock` (cross-platform with `msvcrt` fallback on Windows); read-last + chain + write + fsync under exclusive lock |
| 2 | Event chain verification at business entry points | `state.py`, `cli.py` | `EventStore.verify_or_fail()` runs hash + semantic + sequence checks; all CLI commands call it before mutation |
| 3 | Forecast without experiment/manifest blocked | `cli.py` | `forecast` command checks experiment status + manifest existence + market membership before proceeding |
| 4 | Unify manifest storage path | `cli.py`, `manifest.py` | `manifest-create` now writes to `data/experiment_logs/<id>/manifest.json`; all commands load from `find_manifest_path` which searches the same location |
| 5 | Manifest artifact hash self-reference | `manifest.py` | `compute_manifest_artifact_hash` excludes `manifest_hash` and `manifest_artifact_hash` fields; fresh manifests now self-verify correctly |
| 6 | Manifest freeze immutable | `manifest.py` | `freeze_manifest` uses atomic write + raises `FileExistsError` if target exists |
| 7 | ManifestMarketEntry validation | `schemas.py` | `ManifestMarketEntry` strips/validates non-empty `market_id`; `MarketManifest` rejects duplicate market_ids |
| 8 | Forecast workflow persists package artifact | `cli.py` | `forecast` command writes validated package with `package_hash` to `packages/<market_id>.json` immediately after validation |
| 9 | PriceRevealService re-verification | `price_reveal_service.py` | Full rewrite: loads lock artifact (`_load_verified_lock`), verifies forecast artifact hash, verifies package hash, enforces market_id chain |
| 10 | Forecast/lock versioning | `cli.py`, `forecast_lock.py` | Lock artifact version matches forecast version (`v{version}.json`); duplicate lock blocked |
| 11 | Snapshot append-only | `price_reveal_service.py` | Snapshot layout: `price_snapshots/<market_id>/<timestamp>_<uuid>.json`; no overwrite |
| 12 | Partial evaluation fix | `cli.py`, `state.py` | Experiment completes only when ALL manifest markets are EVALUATED; partial evaluation keeps experiment ACTIVE |
| 13 | COMPLETE experiment freezes mutations | `state.py` | `_require_active()` blocks all mutations when experiment is CREATED or COMPLETE |
| 14 | Experiment ID binding | `state.py` | `EventStore.append()` verifies all existing events belong to the same `experiment_id`; cross-experiment operations rejected |
| 15 | manifest-verify dual hash | `cli.py`, `manifest.py` | `verify_manifest` returns `(bool, details_str)` checking both `identity_hash` and `artifact_hash`; CLI outputs both PASS/FAIL |
| 16 | (Covered by 28 simulation scenarios) | — | 28 complete scenarios including `missing_lock_artifact`, `missing_forecast_artifact`, `partial_evaluation`, `complete_experiment_mutation` |
| 17 | New simulations (7 added) | `cli.py` | `concurrent_event_append`, `forecast_without_experiment`, `forecast_without_manifest`, `manifest_artifact_self_verify`, `missing_lock_artifact`, `missing_forecast_artifact`, `forecast_v2_lock_v2`, `partial_evaluation`, `complete_experiment_mutation` |
| 18 | Report accuracy | — | All counts verified against raw `pytest`/CLI output |

---

## Files Modified

| File | Changes |
|------|---------|
| `phase0/state.py` | EventStore: fcntl flock, verify_or_fail(), verify_sequences(), experiment_id binding, _concurrent_append_worker, CLOSED state blocking |
| `phase0/schemas.py` | ManifestMarketEntry market_id validation, MarketManifest duplicate check |
| `phase0/manifest.py` | Atomic immutable freeze, artifact hash self-reference fix, verify_manifest dual return |
| `phase0/cli.py` | unified manifest path, chain verification, experiment/guard checks, package artifact persistence, lock versioning, partial evaluation policy, 7 new scenarios |
| `phase0/price_reveal_service.py` | Full rewrite: lock/forecast/package artifact verification, append-only snapshots |
| `phase0/forecast_lock.py` | CleanForecastPackage-based hash (consistency) |
| `tests/test_manifest.py` | Updated verify_manifest callers |
| `tests/test_state_machine.py` | Updated assertion for sequence-first verification |

---

## Known Remaining Issues

- **Windows file locking**: `msvcrt.locking()` works but may have limitations under high contention. A dedicated lock file or `portalocker` would be more robust.
- **No public network validation**: All forecasts use fixture providers; no real Polymarket/CZ API integration.
- **Phase 1 scope excluded**: No Rules Agent, Evidence Agent, Contrarian Agent, or MoA.
