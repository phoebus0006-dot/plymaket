from __future__ import annotations

from datetime import datetime, timezone

import pytest

from phase0.temporal import (
    _parse_ts, check_evidence_temporal_integrity, TemporalLeakageError,
)


class TestParseTs:
    def test_parse_aware_datetime(self):
        dt = _parse_ts("2025-06-01T12:00:00+00:00")
        assert dt is not None
        assert dt.tzinfo is not None

    def test_naive_string_raises(self):
        with pytest.raises(ValueError, match="Naive datetime"):
            _parse_ts("2025-06-01T00:00:00")

    def test_parse_none(self):
        assert _parse_ts(None) is None

    def test_parse_datetime_object(self):
        dt = datetime(2025, 6, 1, tzinfo=timezone.utc)
        assert _parse_ts(dt) is dt

    def test_parse_naive_datetime_object_raises(self):
        with pytest.raises(ValueError, match="Naive datetime"):
            _parse_ts(datetime(2025, 6, 1))

    def test_parse_converts_to_utc(self):
        dt_plus8 = datetime(2025, 5, 15, 8, 0, 0, tzinfo=timezone.utc)
        dt_utc = _parse_ts(dt_plus8.isoformat())
        assert dt_utc is not None
        assert dt_utc.tzinfo == timezone.utc

    def test_parse_int_returns_none(self):
        assert _parse_ts(12345) is None


class TestTemporalIntegrity:
    def test_evidence_before_cutoff_passes(self):
        evidence = [{
            "published_at": "2025-05-01T00:00:00+00:00",
            "source_url": "https://example.com",
        }]
        cutoff = datetime(2025, 6, 1, tzinfo=timezone.utc)
        result = check_evidence_temporal_integrity(evidence, cutoff)
        assert len(result) == 1

    def test_evidence_after_cutoff_rejected(self):
        evidence = [{
            "published_at": "2025-07-01T00:00:00+00:00",
            "source_url": "https://example.com",
        }]
        cutoff = datetime(2025, 6, 1, tzinfo=timezone.utc)
        with pytest.raises(TemporalLeakageError):
            check_evidence_temporal_integrity(evidence, cutoff)

    def test_empty_evidence_passes(self):
        cutoff = datetime(2025, 6, 1, tzinfo=timezone.utc)
        result = check_evidence_temporal_integrity([], cutoff)
        assert result == []

    def test_evidence_at_exact_cutoff_passes(self):
        evidence = [{
            "published_at": "2025-06-01T00:00:00+00:00",
            "source_url": "https://example.com",
        }]
        cutoff = datetime(2025, 6, 1, tzinfo=timezone.utc)
        result = check_evidence_temporal_integrity(evidence, cutoff)
        assert len(result) == 1

    def test_naive_cutoff_raises(self):
        with pytest.raises(ValueError, match="timezone-aware"):
            check_evidence_temporal_integrity([], datetime(2025, 6, 1))

    def test_updated_at_without_snapshot_rejected(self):
        evidence = [{
            "published_at": "2025-05-01T00:00:00+00:00",
            "updated_at": "2025-07-01T00:00:00+00:00",
            "source_url": "https://example.com",
        }]
        cutoff = datetime(2025, 6, 1, tzinfo=timezone.utc)
        with pytest.raises(TemporalLeakageError):
            check_evidence_temporal_integrity(evidence, cutoff)

    def test_updated_at_with_snapshot_passes(self):
        evidence = [{
            "published_at": "2025-05-01T00:00:00+00:00",
            "updated_at": "2025-07-01T00:00:00+00:00",
            "snapshot_timestamp": "2025-05-15T00:00:00+00:00",
            "source_url": "https://example.com",
        }]
        cutoff = datetime(2025, 6, 1, tzinfo=timezone.utc)
        result = check_evidence_temporal_integrity(evidence, cutoff)
        assert len(result) == 1

    def test_multiple_evidence_mixed(self):
        evidence = [
            {"published_at": "2025-05-01T00:00:00+00:00", "source_url": "https://a.com"},
            {"published_at": "2025-07-01T00:00:00+00:00", "source_url": "https://b.com"},
        ]
        cutoff = datetime(2025, 6, 1, tzinfo=timezone.utc)
        with pytest.raises(TemporalLeakageError):
            check_evidence_temporal_integrity(evidence, cutoff)
