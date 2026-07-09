from __future__ import annotations

import json
import os
from enum import Enum
from hashlib import sha256
from pathlib import Path
from typing import Any

from copy import deepcopy

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field

from .schemas import (
    CleanForecastPackage,
    ForecastLock,
    MarketManifest,
    PriceSnapshot,
    Resolution,
    ResolutionOutcome,
    TzAwareDt,
)


# ── multiprocessing stress-test helper ──────


def _concurrent_append_worker(seed: int, path_str: str, exp_id: str, n: int) -> str:
    """Top-level worker for concurrent_event_append multiprocessing test."""
    try:
        store = EventStore(path_str)
        for i in range(n):
            store.append(
                event_type="sim_event",
                experiment_id=exp_id,
                data={"seed": seed, "i": i},
            )
        return "ok"
    except Exception as e:
        return str(e)


# ── cross-platform file locking ──────────────

_HAS_FLOCK = True
try:
    import fcntl
except ImportError:
    _HAS_FLOCK = False

_HAS_MSVCRT = False
try:
    import msvcrt  # Windows
    _HAS_MSVCRT = True
except ImportError:
    pass


def _flock_exclusive(fh):
    """Acquire exclusive file lock (blocking)."""
    if _HAS_FLOCK:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
    elif _HAS_MSVCRT:
        # Lock the entire file (0 to max) - Windows releases on close
        msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 2**31 - 1)


def _flock_unlock(fh):
    """Release file lock."""
    if _HAS_FLOCK:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    # On Windows/macOS, close releases the lock automatically


def _read_last_line(path: Path) -> tuple[str, int]:
    """Read the last complete JSON line.  Returns (event_hash, sequence)."""
    last_hash = "0" * 64
    seq = 0
    if path.is_file() and path.stat().st_size > 0:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                prev = json.loads(line)
                last_hash = prev.get("event_hash", "0" * 64)
                seq = prev.get("event_sequence", 0)
    return last_hash, seq


# ──────────────────────────────────────────────
# Event schema (internal to state layer)
# ──────────────────────────────────────────────


class EventSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: str
    event_sequence: int
    experiment_id: str
    market_id: str = ""
    previous_event_hash: str
    event_hash: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    timestamp: TzAwareDt


# ──────────────────────────────────────────────
# Experiment lifecycle
# ──────────────────────────────────────────────


class ExperimentStatus(str, Enum):
    CREATED = "CREATED"
    ACTIVE = "ACTIVE"
    COMPLETE = "COMPLETE"


_TRANSITIONS_EXPERIMENT: dict[ExperimentStatus, set[ExperimentStatus]] = {
    ExperimentStatus.CREATED: {ExperimentStatus.ACTIVE},
    ExperimentStatus.ACTIVE: {ExperimentStatus.COMPLETE},
    ExperimentStatus.COMPLETE: set(),
}


def _valid_transition_experiment(
    current: ExperimentStatus, next_status: ExperimentStatus
) -> bool:
    allowed = _TRANSITIONS_EXPERIMENT.get(current, set())
    return next_status in allowed


# ──────────────────────────────────────────────
# Market lifecycle
# ──────────────────────────────────────────────


class MarketStatus(str, Enum):
    PACKAGE_READY = "PACKAGE_READY"
    FORECAST_LOCKED = "FORECAST_LOCKED"
    PRICE_REVEALED = "PRICE_REVEALED"
    # note: PRICE_UNAVAILABLE is not a market state;
    # it is handled as an event for the experiment-level record.
    BASELINE_CAPTURED = "BASELINE_CAPTURED"
    RESOLVED = "RESOLVED"
    EVALUATED = "EVALUATED"
    AUDITED = "AUDITED"


_TRANSITIONS_MARKET: dict[MarketStatus, set[MarketStatus]] = {
    MarketStatus.PACKAGE_READY: {MarketStatus.FORECAST_LOCKED},
    MarketStatus.FORECAST_LOCKED: {MarketStatus.PRICE_REVEALED, MarketStatus.BASELINE_CAPTURED},
    MarketStatus.PRICE_REVEALED: {MarketStatus.BASELINE_CAPTURED, MarketStatus.RESOLVED},
    MarketStatus.BASELINE_CAPTURED: {MarketStatus.RESOLVED},
    MarketStatus.RESOLVED: {MarketStatus.EVALUATED},
    MarketStatus.EVALUATED: {MarketStatus.AUDITED},
    MarketStatus.AUDITED: set(),
}


def _valid_transition_market(
    current: MarketStatus | None, next_status: MarketStatus
) -> bool:
    if current is None:
        allowed = {MarketStatus.PACKAGE_READY}
    else:
        allowed = _TRANSITIONS_MARKET.get(current, set())
    return next_status in allowed


# ──────────────────────────────────────────────
# Event Store (append-only JSONL with hash chain, concurrent-safe)
# ──────────────────────────────────────────────


class EventStore:
    """Append-only event log backed by JSONL + SHA256 hash chain.

    Multi-process safe via fcntl.flock (or msvcrt on Windows).
    Each append opens the file, acquires an exclusive lock,
    reads the last complete line for chaining, computes the next
    sequence number, writes the new event, fsyncs, and releases.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    # ── public helpers ────────────────────────

    def read_all(self) -> list[EventSchema]:
        """Return every event (decoded) in order, or empty list."""
        if not self.path.is_file():
            return []
        events: list[EventSchema] = []
        with open(self.path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                events.append(EventSchema(**json.loads(line)))
        return events

    def verify_experiment_id(self, experiment_id: str) -> None:
        """Verify that all existing events belong to this experiment_id."""
        for ev in self.read_all():
            if ev.experiment_id != experiment_id:
                raise RuntimeError(
                    f"Event store bound to experiment {experiment_id} "
                    f"but found event for experiment {ev.experiment_id}"
                )

    def append(self, event_type: str, experiment_id: str, data: dict[str, Any], market_id: str = "") -> EventSchema:
        """Multi-process safe append: exclusive lock → read-last → chain → append → fsync → unlock.

        Returns the newly created EventSchema (with computed event_hash).
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)

        # Atomic file creation to avoid multi-process race
        if not self.path.is_file():
            fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_RDWR)
            os.close(fd)
        fh = open(self.path, "r+b")

        try:
            _flock_exclusive(fh)
            # Read last event under lock
            last_hash = "0" * 64
            seq = 0
            seen_experiments: set[str] = set()
            fh.seek(0)
            for raw_line_bytes in fh:
                raw_line = raw_line_bytes.decode("utf-8").strip()
                if not raw_line:
                    continue
                prev = json.loads(raw_line)
                last_hash = prev.get("event_hash", "0" * 64)
                seq = prev.get("event_sequence", 0)
                seen_experiments.add(prev.get("experiment_id", ""))

            # Verify experiment_id consistency
            if seen_experiments and experiment_id not in seen_experiments:
                raise RuntimeError(
                    f"cannot append event for experiment {experiment_id} "
                    f"to store bound to {seen_experiments}"
                )

            seq += 1
            ev = EventSchema(
                event_type=event_type,
                event_sequence=seq,
                experiment_id=experiment_id,
                market_id=market_id,
                previous_event_hash=last_hash,
                data=data,
                timestamp=datetime.now(timezone.utc),
            )
            payload = ev.model_dump_json(exclude={"event_hash"})
            ev.event_hash = sha256(payload.encode("utf-8")).hexdigest()

            line_bytes = (ev.model_dump_json() + "\n").encode("utf-8")
            fh.seek(0, os.SEEK_END)  # seek to end for append
            fh.write(line_bytes)
            fh.flush()
            os.fsync(fh.fileno())
        finally:
            _flock_unlock(fh)
            fh.close()

        return ev

    def verify_sequences(self) -> list[str]:
        """Verify event sequences are contiguous (1..N, no gaps, no dupes).

        Returns a list of error messages (empty = all good).
        """
        events = self.read_all()
        if not events:
            return []
        errors: list[str] = []
        for i, ev in enumerate(events):
            expected = i + 1
            if ev.event_sequence != expected:
                errors.append(
                    f"event idx={i}: expected sequence {expected}, "
                    f"got {ev.event_sequence}"
                )
        return errors

    def verify_chain(self) -> tuple[bool, str]:
        """Verify the SHA256 hash chain from first to last event.

        Returns (ok, message).
        """
        events = self.read_all()
        if not events:
            return True, "empty chain (trivially valid)"

        seq_errors = self.verify_sequences()
        if seq_errors:
            return False, f"sequence error: {seq_errors[0]}"

        for i, ev in enumerate(events):
            expected_prev = "0" * 64 if i == 0 else events[i - 1].event_hash
            if ev.previous_event_hash != expected_prev:
                return (
                    False,
                    f"event {ev.event_sequence} (idx={i}): "
                    f"previous_event_hash mismatch (expected={expected_prev})",
                )
            payload = ev.model_dump_json(exclude={"event_hash"})
            expected_hash = sha256(payload.encode("utf-8")).hexdigest()
            if ev.event_hash != expected_hash:
                return (
                    False,
                    f"event {ev.event_sequence} (idx={i}): "
                    f"event_hash mismatch (expected={expected_hash})",
                )
        return True, f"chain valid ({len(events)} events)"

    def verify_or_fail(self) -> None:
        """Run all verifications and raise RuntimeError on any failure."""
        ok, msg = self.verify_chain()
        if not ok:
            raise RuntimeError(f"Event chain integrity violation: {msg}")
        semantic_errors = self.verify_chain_semantic()
        if semantic_errors:
            raise RuntimeError(
                f"Event chain semantic violation: {semantic_errors[0]}"
            )

    def verify_chain_semantic(self) -> list[str]:
        """Semantic validation of event ordering and state lifecycle.

        Returns a list of error messages (empty = all good).
        """
        events = self.read_all()
        if not events:
            return []

        errors: list[str] = []
        experiment_current: ExperimentStatus | None = None
        first_experiment_id: str | None = None
        market_states: dict[str, MarketStatus] = {}

        for ev in events:
            # ── experiment-level transitions ──
            if ev.event_type == "experiment_created":
                if experiment_current is not None:
                    errors.append(
                        f"event {ev.event_sequence}: experiment_created "
                        f"when experiment already exists (status={experiment_current})"
                    )
                experiment_current = ExperimentStatus.CREATED

            elif ev.event_type == "experiment_activated":
                if experiment_current is None:
                    errors.append(
                        f"event {ev.event_sequence}: experiment_activated "
                        f"before experiment_created"
                    )
                elif not _valid_transition_experiment(experiment_current, ExperimentStatus.ACTIVE):
                    errors.append(
                        f"event {ev.event_sequence}: invalid experiment transition "
                        f"{experiment_current} -> ACTIVE"
                    )
                else:
                    experiment_current = ExperimentStatus.ACTIVE

            elif ev.event_type == "experiment_completed":
                if experiment_current is None:
                    errors.append(
                        f"event {ev.event_sequence}: experiment_completed "
                        f"before experiment_created"
                    )
                elif not _valid_transition_experiment(experiment_current, ExperimentStatus.COMPLETE):
                    errors.append(
                        f"event {ev.event_sequence}: invalid experiment transition "
                        f"{experiment_current} -> COMPLETE"
                    )
                else:
                    experiment_current = ExperimentStatus.COMPLETE

            # ── experiment_id consistency ──
            if first_experiment_id is None:
                first_experiment_id = ev.experiment_id
            elif ev.experiment_id != first_experiment_id:
                errors.append(
                    f"event {ev.event_sequence}: experiment_id mismatch "
                    f"(expected {first_experiment_id}, got {ev.experiment_id})"
                )

            # ── market-level transitions ──
            if ev.market_id:
                mid = ev.market_id
                current_ms = market_states.get(mid)

                if ev.event_type == "market_initialized":
                    if ev.market_id != ev.data.get("market_id"):
                        errors.append(
                            f"event {ev.event_sequence}: market_initialized "
                            f"market_id mismatch "
                            f"(event.market_id={ev.market_id}, data.market_id={ev.data.get('market_id')})"
                        )
                    if ev.data.get("package", {}).get("market_id") != ev.market_id:
                        errors.append(
                            f"event {ev.event_sequence}: market_initialized "
                            f"package.market_id mismatch "
                            f"(expected {ev.market_id}, got {ev.data.get('package', {}).get('market_id')})"
                        )
                    if current_ms is not None:
                        errors.append(
                            f"event {ev.event_sequence}: market_initialized "
                            f"for market {mid} when already in state {current_ms}"
                        )
                    else:
                        market_states[mid] = MarketStatus.PACKAGE_READY

                elif ev.event_type == "forecast_locked":
                    if ev.market_id != ev.data.get("market_id"):
                        errors.append(
                            f"event {ev.event_sequence}: forecast_locked "
                            f"market_id mismatch "
                            f"(event.market_id={ev.market_id}, data.market_id={ev.data.get('market_id')})"
                        )
                    if ev.data.get("lock", {}).get("market_id") != ev.market_id:
                        errors.append(
                            f"event {ev.event_sequence}: forecast_locked "
                            f"lock.market_id mismatch "
                            f"(expected {ev.market_id}, got {ev.data.get('lock', {}).get('market_id')})"
                        )
                    if experiment_current == ExperimentStatus.CREATED:
                        errors.append(
                            f"event {ev.event_sequence}: forecast_locked for market {mid} "
                            f"while experiment is still CREATED"
                        )
                    if not _valid_transition_market(current_ms, MarketStatus.FORECAST_LOCKED):
                        errors.append(
                            f"event {ev.event_sequence}: invalid market transition "
                            f"{current_ms} -> FORECAST_LOCKED for market {mid}"
                        )
                    else:
                        market_states[mid] = MarketStatus.FORECAST_LOCKED

                elif ev.event_type == "price_revealed":
                    if ev.market_id != ev.data.get("market_id"):
                        errors.append(
                            f"event {ev.event_sequence}: price_revealed "
                            f"market_id mismatch "
                            f"(event.market_id={ev.market_id}, data.market_id={ev.data.get('market_id')})"
                        )
                    if not _valid_transition_market(current_ms, MarketStatus.PRICE_REVEALED):
                        errors.append(
                            f"event {ev.event_sequence}: invalid market transition "
                            f"{current_ms} -> PRICE_REVEALED for market {mid}"
                        )
                    else:
                        market_states[mid] = MarketStatus.PRICE_REVEALED

                elif ev.event_type == "market_resolved":
                    if ev.market_id != ev.data.get("market_id"):
                        errors.append(
                            f"event {ev.event_sequence}: market_resolved "
                            f"market_id mismatch "
                            f"(event.market_id={ev.market_id}, data.market_id={ev.data.get('market_id')})"
                        )
                    if ev.data.get("resolution", {}).get("market_id") != ev.market_id:
                        errors.append(
                            f"event {ev.event_sequence}: market_resolved "
                            f"resolution.market_id mismatch "
                            f"(expected {ev.market_id}, got {ev.data.get('resolution', {}).get('market_id')})"
                        )
                    if not _valid_transition_market(current_ms, MarketStatus.RESOLVED):
                        errors.append(
                            f"event {ev.event_sequence}: invalid market transition "
                            f"{current_ms} -> RESOLVED for market {mid}"
                        )
                    else:
                        market_states[mid] = MarketStatus.RESOLVED

                elif ev.event_type == "baseline_captured":
                    if not _valid_transition_market(current_ms, MarketStatus.BASELINE_CAPTURED):
                        errors.append(
                            f"event {ev.event_sequence}: invalid market transition "
                            f"{current_ms} -> BASELINE_CAPTURED for market {mid}"
                        )
                    else:
                        market_states[mid] = MarketStatus.BASELINE_CAPTURED

                elif ev.event_type == "market_evaluated":
                    if not _valid_transition_market(current_ms, MarketStatus.EVALUATED):
                        errors.append(
                            f"event {ev.event_sequence}: invalid market transition "
                            f"{current_ms} -> EVALUATED for market {mid}"
                        )
                    else:
                        market_states[mid] = MarketStatus.EVALUATED

                elif ev.event_type == "audited":
                    if not _valid_transition_market(current_ms, MarketStatus.AUDITED):
                        errors.append(
                            f"event {ev.event_sequence}: invalid market transition "
                            f"{current_ms} -> AUDITED for market {mid}"
                        )
                    else:
                        market_states[mid] = MarketStatus.AUDITED

        return errors


# ──────────────────────────────────────────────
# Experiment State Manager
# ──────────────────────────────────────────────


class ExperimentStateManager:
    """High-level gateway for experiment lifecycle and event recording."""

    def __init__(self, store: EventStore) -> None:
        self._store = store
        self._decoded_events: list[EventSchema] = store.read_all()

    def _ensure_integrity(self) -> None:
        """Verify event chain integrity before mutating state."""
        self._store.verify_or_fail()

    def _replay(self) -> None:
        self._decoded_events = self._store.read_all()

    @property
    def store(self) -> EventStore:
        return self._store

    # ── status ────────────────────────────────

    def experiment_status(self) -> ExperimentStatus | None:
        for ev in reversed(self._decoded_events):
            if ev.event_type == "experiment_completed":
                return ExperimentStatus.COMPLETE
            if ev.event_type == "experiment_activated":
                return ExperimentStatus.ACTIVE
            if ev.event_type == "experiment_created":
                return ExperimentStatus.CREATED
        return None

    def market_status(self, market_id: str) -> MarketStatus | None:
        for ev in reversed(self._decoded_events):
            if ev.market_id != market_id:
                continue
            if ev.event_type == "audited":
                return MarketStatus.AUDITED
            if ev.event_type == "market_evaluated":
                return MarketStatus.EVALUATED
            if ev.event_type == "market_resolved":
                return MarketStatus.RESOLVED
            if ev.event_type == "baseline_captured":
                return MarketStatus.BASELINE_CAPTURED
            if ev.event_type == "price_revealed":
                return MarketStatus.PRICE_REVEALED
            if ev.event_type == "forecast_locked":
                return MarketStatus.FORECAST_LOCKED
            if ev.event_type == "market_initialized":
                return MarketStatus.PACKAGE_READY
        return None

    def experiment_is(self, status: ExperimentStatus) -> bool:
        return self.experiment_status() == status

    # ── event recording ───────────────────────

    def _require_active(self) -> None:
        """Block mutations when experiment is not ACTIVE."""
        status = self.experiment_status()
        if status is None:
            raise RuntimeError("experiment not created")
        if status != ExperimentStatus.ACTIVE:
            raise RuntimeError(
                f"experiment must be ACTIVE for mutations, got {status}"
            )

    def record_experiment_created(self, experiment_id: str, manifest: MarketManifest) -> EventSchema:
        self._ensure_integrity()
        self._replay()
        if self.experiment_status() is not None:
            raise RuntimeError(f"experiment {experiment_id} already exists")
        ev = self._store.append(
            event_type="experiment_created",
            experiment_id=experiment_id,
            data={
                "experiment_id": experiment_id,
                "manifest": manifest.model_dump(mode="json"),
            },
        )
        self._replay()
        return ev

    def record_experiment_activated(self, experiment_id: str) -> EventSchema:
        self._ensure_integrity()
        self._replay()
        current = self.experiment_status()
        if current is None:
            raise RuntimeError("experiment not created yet")
        if not _valid_transition_experiment(current, ExperimentStatus.ACTIVE):
            raise RuntimeError(f"cannot activate experiment in state {current}")
        ev = self._store.append(
            event_type="experiment_activated",
            experiment_id=experiment_id,
            data={},
        )
        self._replay()
        return ev

    def record_experiment_completed(self, experiment_id: str) -> EventSchema:
        self._ensure_integrity()
        self._replay()
        current = self.experiment_status()
        if current is None:
            raise RuntimeError("experiment not created yet")
        if not _valid_transition_experiment(current, ExperimentStatus.COMPLETE):
            raise RuntimeError(f"cannot complete experiment in state {current}")
        ev = self._store.append(
            event_type="experiment_completed",
            experiment_id=experiment_id,
            data={},
        )
        self._replay()
        return ev

    def record_market_initialized(self, experiment_id: str, market_id: str, package: CleanForecastPackage) -> EventSchema:
        self._ensure_integrity()
        self._replay()
        current = self.experiment_status()
        if current is None:
            raise RuntimeError("experiment not created yet")
        status = self.experiment_status()
        if status != ExperimentStatus.ACTIVE:
            raise RuntimeError(f"cannot initialize market in experiment state {status}")
        ms = self.market_status(market_id)
        if ms is not None:
            raise RuntimeError(f"market {market_id} already initialized (state={ms})")
        ev = self._store.append(
            event_type="market_initialized",
            experiment_id=experiment_id,
            market_id=market_id,
            data={
                "market_id": market_id,
                "package": package.model_dump(mode="json"),
            },
        )
        self._replay()
        return ev

    def record_forecast_locked(self, experiment_id: str, market_id: str, lock: ForecastLock) -> EventSchema:
        self._ensure_integrity()
        self._replay()
        if self.experiment_status() == ExperimentStatus.CREATED:
            raise RuntimeError("cannot lock forecast while experiment is CREATED")
        self._require_active()
        ms = self.market_status(market_id)
        if not _valid_transition_market(ms, MarketStatus.FORECAST_LOCKED):
            raise RuntimeError(
                f"cannot lock forecast for market {market_id} "
                f"in state {ms}"
            )
        ev = self._store.append(
            event_type="forecast_locked",
            experiment_id=experiment_id,
            market_id=market_id,
            data={
                "market_id": market_id,
                "lock": lock.model_dump(mode="json"),
            },
        )
        self._replay()
        return ev

    def record_price_revealed(
        self,
        experiment_id: str,
        market_id: str,
        snapshot: PriceSnapshot | None = None,
    ) -> EventSchema:
        self._ensure_integrity()
        self._replay()
        self._require_active()
        ms = self.market_status(market_id)
        if not _valid_transition_market(ms, MarketStatus.PRICE_REVEALED):
            raise RuntimeError(
                f"cannot reveal price for market {market_id} "
                f"in state {ms}"
            )
        data: dict[str, Any] = {"market_id": market_id}
        if snapshot is not None:
            data["snapshot"] = snapshot.model_dump(mode="json")
        ev = self._store.append(
            event_type="price_revealed",
            experiment_id=experiment_id,
            market_id=market_id,
            data=data,
        )
        self._replay()
        return ev

    def record_price_unavailable(self, experiment_id: str, market_id: str, reason: str = "") -> EventSchema:
        self._ensure_integrity()
        self._replay()
        self._require_active()
        ms = self.market_status(market_id)
        if ms is None:
            raise RuntimeError(f"market {market_id} not initialized")
        if ms != MarketStatus.FORECAST_LOCKED:
            raise RuntimeError(
                f"cannot mark price unavailable for market {market_id} "
                f"in state {ms} (expected FORECAST_LOCKED)"
            )
        data: dict[str, Any] = {"market_id": market_id, "reason": reason}
        ev = self._store.append(
            event_type="price_unavailable",
            experiment_id=experiment_id,
            market_id=market_id,
            data=data,
        )
        self._replay()
        return ev

    def record_market_resolved(
        self,
        experiment_id: str,
        market_id: str,
        resolution: Resolution,
    ) -> EventSchema:
        self._ensure_integrity()
        self._replay()
        self._require_active()
        ms = self.market_status(market_id)
        if ms is None:
            raise RuntimeError(f"market {market_id} not initialized")
        if not _valid_transition_market(ms, MarketStatus.RESOLVED):
            raise RuntimeError(
                f"cannot resolve market {market_id} "
                f"in state {ms}"
            )
        ev = self._store.append(
            event_type="market_resolved",
            experiment_id=experiment_id,
            market_id=market_id,
            data={
                "market_id": market_id,
                "resolution": resolution.model_dump(mode="json"),
            },
        )
        self._replay()
        return ev

    def record_market_evaluated(
        self,
        experiment_id: str,
        market_id: str,
    ) -> EventSchema:
        self._ensure_integrity()
        self._replay()
        self._require_active()
        ms = self.market_status(market_id)
        if ms is None:
            raise RuntimeError(f"market {market_id} not initialized")
        if not _valid_transition_market(ms, MarketStatus.EVALUATED):
            raise RuntimeError(
                f"cannot evaluate market {market_id} "
                f"in state {ms}"
            )
        ev = self._store.append(
            event_type="market_evaluated",
            experiment_id=experiment_id,
            market_id=market_id,
            data={"market_id": market_id},
        )
        self._replay()
        return ev

    def record_baseline_captured(
        self,
        experiment_id: str,
        market_id: str,
    ) -> EventSchema:
        self._ensure_integrity()
        self._replay()
        self._require_active()
        ms = self.market_status(market_id)
        if ms is None:
            raise RuntimeError(f"market {market_id} not initialized")
        if not _valid_transition_market(ms, MarketStatus.BASELINE_CAPTURED):
            raise RuntimeError(
                f"cannot capture baseline for market {market_id} "
                f"in state {ms}"
            )
        ev = self._store.append(
            event_type="baseline_captured",
            experiment_id=experiment_id,
            market_id=market_id,
            data={"market_id": market_id},
        )
        self._replay()
        return ev

    def record_market_audited(
        self,
        experiment_id: str,
        market_id: str,
    ) -> EventSchema:
        self._ensure_integrity()
        self._replay()
        self._require_active()
        ms = self.market_status(market_id)
        if ms is None:
            raise RuntimeError(f"market {market_id} not initialized")
        if not _valid_transition_market(ms, MarketStatus.AUDITED):
            raise RuntimeError(
                f"cannot audit market {market_id} "
                f"in state {ms}"
            )
        ev = self._store.append(
            event_type="audited",
            experiment_id=experiment_id,
            market_id=market_id,
            data={"market_id": market_id},
        )
        self._replay()
        return ev
