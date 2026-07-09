from __future__ import annotations

import json
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

from .forecast_lock import compute_package_hash, parse_version
from .package_validator import CleanForecastPackage
from .schemas import BaselineArtifact, Forecast, ForecastLock, PackageArtifact, PriceSnapshot
from .state import EventStore, ExperimentStateManager, MarketStatus


class PriceRevealService:
    """Manages price revelation for a single experiment.

    Lifecycle: FORECAST_LOCKED → PRICE_REVEALED → BASELINE_CAPTURED → RESOLVED → EVALUATED → AUDITED

    1. Loads active market state
    2. Loads exact lock artifact and validates ForecastLock schema
    3. Loads exact forecast artifact and recomputes forecast_artifact_hash
    4. Loads package artifact and recomputes package_hash
    5. Verifies market_id chain: manifest → package → forecast → lock → request
    6. Calls provider, persists snapshot (append-only), transitions state
    """

    def __init__(
        self,
        state_mgr: ExperimentStateManager,
        experiments_root: str,
        provider=None,
    ) -> None:
        self._state_mgr = state_mgr
        self._experiments_root = Path(experiments_root)
        self._provider = provider
        self._raw_package_dict: dict[str, Any] = {}

    @property
    def store(self) -> EventStore:
        return self._state_mgr.store

    # ── public API ────────────────────────────

    def reveal(
        self,
        market_id: str,
        experiment_id: str,
        manifest_markets: set[str] | None = None,
    ) -> PriceSnapshot | None:
        state = self._state_mgr.market_status(market_id)
        if state is None:
            raise RuntimeError(f"market {market_id} not initialized")
        if state != MarketStatus.FORECAST_LOCKED:
            raise RuntimeError(
                f"market {market_id} in state {state}, "
                f"expected FORECAST_LOCKED"
            )

        if manifest_markets is not None and market_id not in manifest_markets:
            raise RuntimeError(f"market {market_id} not in manifest")

        # 1. Load and verify lock artifact
        lock = self._load_verified_lock(market_id, experiment_id)
        if lock.market_id != market_id:
            raise RuntimeError(
                f"lock.market_id ({lock.market_id}) != requested ({market_id})"
            )

        # 2. Load and verify forecast artifact
        forecast_artifact = self._load_verified_forecast(
            market_id, experiment_id, lock.forecast_version
        )
        self._verify_forecast_artifact_hash(forecast_artifact, lock)

        # Parse forecast object
        fc_obj = Forecast(**forecast_artifact)
        violations = []
        if lock.raw_probability != fc_obj.p_yes:
            violations.append(f"lock.raw_probability ({lock.raw_probability}) != forecast.p_yes ({fc_obj.p_yes})")
        if lock.forecast_cutoff != fc_obj.forecast_cutoff:
            violations.append(f"lock.forecast_cutoff mismatch")
        if lock.forecast_mode != fc_obj.forecast_mode:
            violations.append(f"lock.forecast_mode mismatch")
        if lock.market_id != fc_obj.market_id:
            violations.append(f"lock.market_id != forecast.market_id")
        forecast_hash = sha256(json.dumps(forecast_artifact, sort_keys=True).encode("utf-8")).hexdigest()
        if lock.forecast_hash != forecast_hash:
            violations.append(f"lock.forecast_hash mismatch")
        if violations:
            raise RuntimeError("Lock-forecast verification failed: " + "; ".join(violations))

        # 3. Load and verify package artifact
        package = self._load_verified_package(market_id, experiment_id)
        self._verify_package_hash(package, lock)

        # 4. market_id consistency chain
        if package.market_id != market_id:
            raise RuntimeError(
                f"package.market_id ({package.market_id}) != {market_id}"
            )

        if manifest_markets is not None and market_id not in manifest_markets:
            raise RuntimeError(f"market {market_id} not in manifest")

        # 5. Provider call
        if self._provider is None:
            return self._handle_no_provider(market_id, experiment_id)

        try:
            raw = self._provider.get_snapshot(market_id=market_id)
        except Exception as exc:
            raise RuntimeError(
                f"Snapshot provider failed for market {market_id}: {exc}"
            )
        if raw is None:
            return self._handle_no_provider(market_id, experiment_id)

        # 6. Build immutable BaselineArtifact
        from uuid import uuid4
        snapshot_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}_{uuid4().hex[:8]}"
        # Extract only PriceSnapshot-compatible fields from provider response
        if isinstance(raw, dict):
            ps_fields = {"market_id", "snapshot_timestamp", "snapshot_id", "bid", "ask", "mid", "spread", "volume", "price_history_url"}
            clean_raw = {k: v for k, v in raw.items() if k in ps_fields}
            snapshot = PriceSnapshot(**clean_raw, snapshot_id=snapshot_id)
        else:
            snapshot = raw
        if isinstance(snapshot, PriceSnapshot) and not snapshot.snapshot_id:
            snapshot.snapshot_id = snapshot_id

        captured_at = datetime.now(timezone.utc)
        prov_token_id = raw.get("token_id", "") if isinstance(raw, dict) else ""

        baseline = BaselineArtifact(
            market_id=market_id,
            token_id=prov_token_id,
            outcome_side="YES",
            best_bid=snapshot.bid,
            best_ask=snapshot.ask,
            midpoint=snapshot.mid,
            spread=snapshot.spread,
            captured_at=captured_at,
            endpoint=raw.get("endpoint", "") if isinstance(raw, dict) else "",
            raw_orderbook_hash=raw.get("raw_orderbook_hash", "") if isinstance(raw, dict) else "",
            forecast_id=lock.forecast_id if hasattr(lock, 'forecast_id') else "",
            forecast_version=lock.forecast_version if hasattr(lock, 'forecast_version') else 0,
        )
        baseline_artifact_hash = sha256(
            json.dumps(baseline.model_dump(mode="json"), sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        baseline.artifact_hash = baseline_artifact_hash

        # 7. Persist snapshot (append-only)
        written_path = self._persist_snapshot(market_id, experiment_id, snapshot, snapshot_id=snapshot_id)

        # 8. Persist immutable BaselineArtifact
        baseline_path = written_path.parent / f"{written_path.stem}_baseline.json"
        baseline_path.write_text(baseline.model_dump_json(indent=2), encoding="utf-8")

        # 9. Transition state: FORECAST_LOCKED → PRICE_REVEALED → BASELINE_CAPTURED
        self._state_mgr.record_price_revealed(
            experiment_id=experiment_id,
            market_id=market_id,
            snapshot=snapshot,
            baseline_artifact_hash=baseline_artifact_hash,
        )
        self._state_mgr.record_baseline_captured(
            experiment_id=experiment_id,
            market_id=market_id,
        )
        return snapshot

    def reveal_all_available(
        self,
        experiment_id: str,
        manifest_markets: set[str] | None = None,
    ) -> dict[str, PriceSnapshot | None]:
        results: dict[str, PriceSnapshot | None] = {}
        for market_id in self._markets_in_state(MarketStatus.FORECAST_LOCKED):
            try:
                snap = self.reveal(market_id, experiment_id, manifest_markets)
                results[market_id] = snap
            except Exception as exc:
                results[market_id] = None
        return results

    # ── lock artifact verification ────────────

    def _load_verified_lock(self, market_id: str, experiment_id: str) -> ForecastLock:
        lock_dir = self._experiments_root / experiment_id / "locks" / market_id
        if not lock_dir.is_dir():
            raise RuntimeError(f"lock artifact directory not found: {lock_dir}")
        # Find latest lock version
        lock_versions = []
        for p in lock_dir.iterdir():
            v = parse_version(p.name)
            if v is not None:
                lock_versions.append((v, p))
        if not lock_versions:
            raise RuntimeError(f"no lock artifacts found in {lock_dir}")
        lock_versions.sort(key=lambda x: x[0])
        lock_path = lock_versions[-1][1]
        raw: dict[str, Any] = json.loads(lock_path.read_text(encoding="utf-8"))
        try:
            return ForecastLock(**raw)
        except Exception as exc:
            raise RuntimeError(f"invalid lock artifact {lock_path}: {exc}")

    # ── forecast artifact verification ────────

    def _forecast_version_path(
        self, market_id: str, experiment_id: str, version: int
    ) -> Path:
        return (
            self._experiments_root
            / experiment_id
            / "forecasts"
            / market_id
            / f"v{version}.json"
        )

    def _load_verified_forecast(
        self, market_id: str, experiment_id: str, version: int
    ) -> dict[str, Any]:
        path = self._forecast_version_path(market_id, experiment_id, version)
        if not path.is_file():
            raise RuntimeError(
                f"forecast artifact v{version} not found: {path}"
            )
        raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        try:
            Forecast(**raw)  # validate schema
        except Exception as exc:
            raise RuntimeError(
                f"invalid forecast artifact {path}: {exc}"
            )
        return raw

    @staticmethod
    def _verify_forecast_artifact_hash(
        artifact: dict[str, Any], lock: ForecastLock
    ) -> None:
        """Recompute forecast_artifact_hash from disk and compare with lock."""
        computed = sha256(
            json.dumps(artifact, sort_keys=True).encode("utf-8")
        ).hexdigest()
        if computed != lock.forecast_artifact_hash:
            raise RuntimeError(
                f"forecast artifact hash mismatch: "
                f"computed={computed}, lock.forecast_artifact_hash={lock.forecast_artifact_hash}"
            )

    # ── package artifact verification ─────────

    def _load_verified_package(self, market_id: str, experiment_id: str) -> CleanForecastPackage:
        package_path = self._experiments_root / experiment_id / "packages" / f"{market_id}.json"
        if not package_path.is_file():
            raise FileNotFoundError(
                f"package artifact not found: {package_path}"
            )
        raw_full: dict[str, Any] = json.loads(package_path.read_text(encoding="utf-8"))
        raw_inner: dict[str, Any]
        declared_hash: str = ""
        if "package" in raw_full:
            # PackageArtifact format
            art = PackageArtifact(**raw_full)
            raw_inner = dict(art.package.model_dump(mode="json"))
            declared_hash = art.package_hash
            package_obj = art.package
        else:
            # Legacy format: raw dict with optional package_hash
            declared_hash = raw_full.pop("package_hash", "")
            raw_inner = dict(raw_full)
            package_obj = CleanForecastPackage(**raw_full)

        self._raw_package_dict = raw_inner
        if declared_hash:
            computed = compute_package_hash(raw_inner)
            if computed != declared_hash:
                raise RuntimeError(
                    f"package artifact hash mismatch for {market_id}: "
                    f"computed={computed}, declared={declared_hash}"
                )
        package = package_obj
        if package.market_id != market_id:
            raise RuntimeError(
                f"package market_id mismatch: "
                f"{package.market_id} != {market_id}"
            )
        return package

    def _verify_package_hash(
        self, package: CleanForecastPackage, lock: ForecastLock
    ) -> None:
        """Recompute package_hash from the raw package dict and compare with lock.

        Uses the same dict (without package_hash) as was used when the lock was created.
        """
        computed = compute_package_hash(self._raw_package_dict)
        if computed != lock.package_hash:
            raise RuntimeError(
                f"package hash mismatch: computed={computed}, lock.package_hash={lock.package_hash}"
            )

    # ── helpers ───────────────────────────────

    def _handle_no_provider(
        self, market_id: str, experiment_id: str
    ):
        self._state_mgr.record_price_unavailable(
            experiment_id=experiment_id,
            market_id=market_id,
            reason="no price provider configured",
        )
        return None

    def _persist_snapshot(
        self,
        market_id: str,
        experiment_id: str,
        snapshot: PriceSnapshot,
        snapshot_id: str = "",
    ) -> Path:
        """Persist snapshot to append-only artifact path.

        Layout: price_snapshots/<market_id>/<timestamp>_<uuid>.json
        """
        from uuid import uuid4

        snap_dir = self._experiments_root / experiment_id / "price_snapshots" / market_id
        snap_dir.mkdir(parents=True, exist_ok=True)
        snap_id = snapshot_id or snapshot.snapshot_id or f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}_{uuid4().hex[:8]}"
        snap_path = snap_dir / f"{snap_id}.json"
        snap_path.write_text(
            json.dumps(snapshot.model_dump(mode="json"), indent=2),
            encoding="utf-8",
        )
        return snap_path

    def _markets_in_state(self, status: MarketStatus) -> list[str]:
        events = self._state_mgr.store.read_all()
        result: set[str] = set()
        for ev in events:
            if ev.event_type == "forecast_locked":
                result.add(ev.market_id)
            elif ev.event_type in (
                "price_revealed",
                "price_unavailable",
                "market_resolved",
                "market_evaluated",
            ):
                result.discard(ev.market_id)
        return list(result)
