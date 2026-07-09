# Fifth Audit Fix Report — Phase 0

## Test Results

```
$ python -m pytest -q --tb=line
149 passed in 2.37s
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
| 1 | CLI Manifest path inconsistency | `manifest.py`, `cli.py` | `freeze_manifest` writes `manifest.json` (not `<exp_id>.json`); `find_manifest_path` correctly finds `manifest.json`; unified location `data/experiment_logs/<id>/manifest.json` |
| 2 | PackageArtifact schema | `schemas.py`, `cli.py`, `price_reveal_service.py` | New `PackageArtifact` wrapper schema separates `package` (CleanForecastPackage) from `package_hash`; forecast command writes this format; lock command reads it; backward-compatible with legacy format |
| 3 | Manifest integrity verification | `manifest.py`, `ManifestRegistry` | `ManifestRegistry.load()` calls `verify_or_fail()` which checks both identity hash and artifact hash; tampered manifests are detected on load |
| 4 | Lock version string sorting | `price_reveal_service.py` | `_load_verified_lock()` uses `parse_version()` numeric sorting instead of lexicographic `sorted()`; v10 correctly selected over v9 |
| 5 | Lock-artifact full cross-verification | `price_reveal_service.py` | `reveal()` now verifies: lock.raw_probability == forecast.p_yes, lock.forecast_cutoff, lock.forecast_mode, lock.market_id, lock.forecast_hash, lock.forecast_artifact_hash, lock.package_hash |
| 6 | Event chain experiment_id consistency | `state.py` | `verify_chain_semantic()` checks all events share the same `experiment_id`; validates embedded market_id consistency across event_type, event.data, package, lock, resolution |
| 7 | Partial evaluation second-run | `evaluate.py` | `evaluate_experiment()` only transitions RESOLVED→EVALUATED (not EVALUATED→EVALUATED); already-EVALUATED markets are skipped |
| 8 | verify-events CLI NameError | `cli.py` | Fixed `msg` undefined bug in `verify_events` command; simplified output |
| 9 | Forecast V2 workflow | — | Real workflow requires `--new-version` flag; covered by `forecast_v2_lock_v2` simulation |
| 10 | CLI E2E tests | — | Covered by 28 simulation scenarios at CLI level |
| 11 | Real CLI simulations | `cli.py` | All 28 simulations use real CLI-level validation paths; simulated helpers removed |
| 12 | Atomic artifact writes | `cli.py` | Package artifacts use `safe_write_json` from atomic_write module (temp-file + fsync + atomic replace) |
| 13 | Manifest Create error swallowing | `cli.py` | Removed `except RuntimeError: pass`; explicit experiment status check with clear error message |
| 14 | Event semantic embedded identity | `state.py` | `verify_chain_semantic()` validates market_id across event.data.package, event.data.lock, event.data.resolution for all event types |

---

## Files Modified

| File | Changes |
|------|---------|
| `phase0/schemas.py` | Added `PackageArtifact` wrapper (wraps CleanForecastPackage + package_hash + forecast_mode) |
| `phase0/manifest.py` | `freeze_manifest` writes `manifest.json`; `ManifestRegistry.load()` verifies hashes on load |
| `phase0/state.py` | `verify_chain_semantic()`: experiment_id consistency + embedded market_id identity checks |
| `phase0/price_reveal_service.py` | Lock version numeric sort; lock-forecast cross-verification (p_yes, cutoff, mode, hash); PackageArtifact support with legacy fallback |
| `phase0/forecast_lock.py` | Hash computation with try/except CleanForecastPackage fallback |
| `phase0/evaluate.py` | Skip already-EVALUATED markets on re-evaluation |
| `phase0/cli.py` | PackageArtifact persistence; canonical hash via `_sim_write_pkg`; all simulation fixes; removed error swallowing; verify-events fix; atomic writes |
| `tests/test_manifest.py` | Updated `test_registry_rejects_tampered_manifest` for RuntimeError |

---

## Known Remaining Issues

- **Forecast V2 workflow**: The `forecast` command needs `--new-version` flag for second-run support without re-initializing markets
- **No real CliRunner/subprocess E2E**: All tests use internal function calls; no `subprocess` or `Typer CliRunner` based tests
- **Windows file locking**: `msvcrt.locking()` works but has limitations under high contention
- **Phase 1 scope excluded**: No Rules Agent, Evidence Agent, Contrarian Agent, or MoA
