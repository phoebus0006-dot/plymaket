from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


class TemporalLeakageError(ValueError):
    pass


class TemporarilyUnsafeWarning(UserWarning):
    pass


def _parse_ts(val: Any) -> datetime | None:
    if isinstance(val, str):
        val = datetime.fromisoformat(val)
    if isinstance(val, datetime):
        if val.tzinfo is None:
            raise ValueError(
                f"Naive datetime not allowed: {val.isoformat()}. "
                "All timestamps must be timezone-aware."
            )
        val = val.astimezone(timezone.utc)
        return val
    return None


def check_evidence_temporal_integrity(
    evidence: list[dict[str, Any]],
    forecast_cutoff: datetime,
) -> list[dict[str, Any]]:
    if forecast_cutoff.tzinfo is None:
        raise ValueError("forecast_cutoff must be timezone-aware")

    valid: list[dict[str, Any]] = []
    for ev in evidence:
        published = _parse_ts(ev.get("published_at"))
        updated = _parse_ts(ev.get("updated_at"))
        first_seen = _parse_ts(ev.get("first_seen_at"))
        snapshot_ts = _parse_ts(ev.get("snapshot_timestamp"))

        usable_at: datetime | None = None
        for ts in (published, first_seen):
            if ts is not None:
                if usable_at is None or ts > usable_at:
                    usable_at = ts

        if usable_at is not None and usable_at > forecast_cutoff:
            raise TemporalLeakageError(
                f"Evidence usable_at ({usable_at.isoformat()}) is after "
                f"forecast_cutoff ({forecast_cutoff.isoformat()})"
            )

        if updated is not None and updated > forecast_cutoff and snapshot_ts is None:
            raise TemporalLeakageError(
                f"Evidence updated_at ({updated.isoformat()}) is after "
                f"forecast_cutoff ({forecast_cutoff.isoformat()}) with no snapshot"
            )

        if snapshot_ts is not None and snapshot_ts > forecast_cutoff:
            raise TemporalLeakageError(
                f"Evidence snapshot_timestamp ({snapshot_ts.isoformat()}) is after "
                f"forecast_cutoff ({forecast_cutoff.isoformat()})"
            )

        valid.append(ev)
    return valid
