from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from phase0.schemas import (
    Forecast, CleanForecastPackage, MarketManifest, ForecastLock,
    EvaluationSummary, PriceSnapshot, Resolution, ResolutionOutcome,
)


class TestForecastValidation:
    def test_valid_forecast(self):
        fc = Forecast(
            market_id="M001",
            forecast_cutoff=datetime(2025, 6, 1, tzinfo=timezone.utc),
            forecast_mode="CHEAP_BASELINE",
            p_yes=0.63,
            interval_50=[0.56, 0.70],
            interval_80=[0.44, 0.77],
        )
        assert fc.p_yes == 0.63

    def test_p_yes_below_0_rejected(self):
        with pytest.raises(ValidationError):
            Forecast(
                market_id="M001",
                forecast_cutoff=datetime(2025, 6, 1, tzinfo=timezone.utc),
                forecast_mode="CHEAP_BASELINE",
                p_yes=-0.1,
                interval_50=[0.0, 0.0],
                interval_80=[0.0, 0.0],
            )

    def test_p_yes_above_1_rejected(self):
        with pytest.raises(ValidationError):
            Forecast(
                market_id="M001",
                forecast_cutoff=datetime(2025, 6, 1, tzinfo=timezone.utc),
                forecast_mode="CHEAP_BASELINE",
                p_yes=1.7,
                interval_50=[0.5, 0.6],
                interval_80=[0.4, 0.7],
            )

    def test_interval_order_violation(self):
        with pytest.raises(ValidationError):
            Forecast(
                market_id="M001",
                forecast_cutoff=datetime(2025, 6, 1, tzinfo=timezone.utc),
                forecast_mode="CHEAP_BASELINE",
                p_yes=0.5,
                interval_50=[0.6, 0.3],
                interval_80=[0.2, 0.8],
            )

    def test_naive_timestamp_rejected(self):
        with pytest.raises(ValidationError):
            Forecast(
                market_id="M001",
                forecast_cutoff=datetime(2025, 6, 1),
                forecast_mode="CHEAP_BASELINE",
                p_yes=0.5,
                interval_50=[0.4, 0.6],
                interval_80=[0.3, 0.7],
            )

    def test_naive_timestamp_string_rejected(self):
        with pytest.raises(ValidationError):
            Forecast.model_validate({
                "market_id": "M001",
                "forecast_cutoff": "2025-06-01T00:00:00",
                "forecast_mode": "CHEAP_BASELINE",
                "p_yes": 0.5,
                "interval_50": [0.4, 0.6],
                "interval_80": [0.3, 0.7],
            })

    def test_interval_80_contains_50_and_p(self):
        fc = Forecast(
            market_id="M001",
            forecast_cutoff=datetime(2025, 6, 1, tzinfo=timezone.utc),
            forecast_mode="CHEAP_BASELINE",
            p_yes=0.5,
            interval_50=[0.45, 0.55],
            interval_80=[0.30, 0.70],
        )
        assert fc.interval_80[0] <= fc.interval_50[0] <= fc.p_yes <= fc.interval_50[1] <= fc.interval_80[1]

    def test_extra_field_rejected(self):
        with pytest.raises(ValidationError):
            Forecast.model_validate({
                "market_id": "M001",
                "forecast_cutoff": "2025-06-01T00:00:00+00:00",
                "forecast_mode": "CHEAP_BASELINE",
                "p_yes": 0.5,
                "interval_50": [0.4, 0.6],
                "interval_80": [0.3, 0.7],
                "hidden_field": "should not be allowed",
            })


class TestCleanForecastPackage:
    def test_valid_package(self):
        pkg = CleanForecastPackage(
            market_id="M001",
            question="Test?",
            description="Desc",
            resolution_source="https://example.com",
            outcomes=["Yes", "No"],
            package_created_at=datetime(2025, 5, 15, tzinfo=timezone.utc),
        )
        assert pkg.market_id == "M001"

    def test_naive_timestamp_rejected(self):
        with pytest.raises(ValidationError):
            CleanForecastPackage(
                market_id="M001",
                question="Test?",
                description="Desc",
                resolution_source="https://example.com",
                outcomes=["Yes", "No"],
                package_created_at=datetime(2025, 5, 15),
            )

    def test_naive_timestamp_string_rejected(self):
        with pytest.raises(ValidationError):
            CleanForecastPackage.model_validate({
                "market_id": "M001",
                "question": "Test?",
                "description": "Desc",
                "resolution_source": "https://example.com",
                "outcomes": ["Yes", "No"],
                "package_created_at": "2025-05-15T00:00:00",
            })

    def test_extra_field_rejected(self):
        with pytest.raises(ValidationError):
            CleanForecastPackage.model_validate({
                "market_id": "M001",
                "question": "Test?",
                "description": "Desc",
                "resolution_source": "https://example.com",
                "outcomes": ["Yes", "No"],
                "package_created_at": "2025-05-15T00:00:00+00:00",
                "extra_data": "not allowed",
            })


class TestMarketManifest:
    def test_valid_manifest(self):
        m = MarketManifest(
            experiment_id="P0-001",
            created_at=datetime(2025, 6, 1, tzinfo=timezone.utc),
            selection_cutoff=datetime(2025, 6, 1, tzinfo=timezone.utc),
        )
        assert m.experiment_id == "P0-001"

    def test_naive_timestamp_rejected(self):
        with pytest.raises(ValidationError):
            MarketManifest(
                experiment_id="P0-001",
                created_at=datetime(2025, 6, 1),
                selection_cutoff=datetime(2025, 6, 1, tzinfo=timezone.utc),
            )

    def test_naive_timestamp_string_rejected(self):
        with pytest.raises(ValidationError):
            MarketManifest.model_validate({
                "experiment_id": "P0-001",
                "created_at": "2025-06-01T00:00:00",
                "selection_cutoff": "2025-06-01T00:00:00+00:00",
            })

    def test_extra_field_rejected(self):
        with pytest.raises(ValidationError):
            MarketManifest.model_validate({
                "experiment_id": "P0-001",
                "created_at": "2025-06-01T00:00:00+00:00",
                "selection_cutoff": "2025-06-01T00:00:00+00:00",
                "extra_option": "nope",
            })


class TestForecastLock:
    def test_valid_lock(self):
        lock = ForecastLock(
            forecast_id="FC-TEST",
            market_id="M001",
            forecast_cutoff=datetime(2025, 6, 1, tzinfo=timezone.utc),
            package_hash="abc123",
            forecast_mode="CHEAP_BASELINE",
            raw_probability=0.63,
            locked_at=datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc),
            forecast_hash="def456",
            forecast_artifact_hash="art123",
        )
        assert lock.forecast_id == "FC-TEST"
        assert lock.market_id == "M001"

    def test_market_id_required(self):
        with pytest.raises(ValidationError):
            ForecastLock(
                forecast_id="FC-TEST",
                forecast_cutoff=datetime(2025, 6, 1, tzinfo=timezone.utc),
                package_hash="abc123",
                forecast_mode="CHEAP_BASELINE",
                raw_probability=0.63,
                locked_at=datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc),
                forecast_hash="def456",
            )

    def test_naive_timestamp_rejected(self):
        with pytest.raises(ValidationError):
            ForecastLock(
                forecast_id="FC-TEST",
                market_id="M001",
                forecast_cutoff=datetime(2025, 6, 1),
                package_hash="abc123",
                forecast_mode="CHEAP_BASELINE",
                raw_probability=0.63,
                locked_at=datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc),
                forecast_hash="def456",
            )

    def test_naive_timestamp_string_rejected(self):
        with pytest.raises(ValidationError):
            ForecastLock.model_validate({
                "forecast_id": "FC-TEST",
                "market_id": "M001",
                "forecast_cutoff": "2025-06-01T00:00:00",
                "package_hash": "abc",
                "forecast_mode": "CHEAP_BASELINE",
                "raw_probability": 0.5,
                "locked_at": "2025-06-01T12:00:00+00:00",
                "forecast_hash": "def",
            })

    def test_extra_field_rejected(self):
        with pytest.raises(ValidationError):
            ForecastLock.model_validate({
                "forecast_id": "FC-TEST",
                "market_id": "M001",
                "forecast_cutoff": "2025-06-01T00:00:00+00:00",
                "package_hash": "abc",
                "forecast_mode": "CHEAP_BASELINE",
                "raw_probability": 0.5,
                "locked_at": "2025-06-01T12:00:00+00:00",
                "forecast_hash": "def",
                "hidden": "extra",
            })


class TestPriceSnapshot:
    def test_valid_snapshot(self):
        snap = PriceSnapshot(
            market_id="M001",
            snapshot_timestamp=datetime(2025, 6, 1, tzinfo=timezone.utc),
            mid=0.5,
            bid=0.4,
            ask=0.6,
            spread=0.2,
            volume=1000.0,
        )
        assert snap.mid == 0.5

    def test_mid_zero_is_valid(self):
        snap = PriceSnapshot(
            market_id="M001",
            snapshot_timestamp=datetime(2025, 6, 1, tzinfo=timezone.utc),
            mid=0.0,
        )
        assert snap.mid == 0.0

    def test_mid_one_is_valid(self):
        snap = PriceSnapshot(
            market_id="M001",
            snapshot_timestamp=datetime(2025, 6, 1, tzinfo=timezone.utc),
            mid=1.0,
        )
        assert snap.mid == 1.0

    def test_bid_out_of_range_rejected(self):
        with pytest.raises(ValidationError):
            PriceSnapshot(
                market_id="M001",
                snapshot_timestamp=datetime(2025, 6, 1, tzinfo=timezone.utc),
                bid=1.5,
            )

    def test_negative_spread_rejected(self):
        with pytest.raises(ValidationError):
            PriceSnapshot(
                market_id="M001",
                snapshot_timestamp=datetime(2025, 6, 1, tzinfo=timezone.utc),
                spread=-0.1,
            )

    def test_volume_negative_rejected(self):
        with pytest.raises(ValidationError):
            PriceSnapshot(
                market_id="M001",
                snapshot_timestamp=datetime(2025, 6, 1, tzinfo=timezone.utc),
                volume=-5.0,
            )

    def test_naive_timestamp_string_rejected(self):
        with pytest.raises(ValidationError):
            PriceSnapshot.model_validate({
                "market_id": "M001",
                "snapshot_timestamp": "2025-06-01T00:00:00",
            })

    def test_extra_field_rejected(self):
        with pytest.raises(ValidationError):
            PriceSnapshot.model_validate({
                "market_id": "M001",
                "snapshot_timestamp": "2025-06-01T00:00:00+00:00",
                "extra": "no",
            })


class TestResolution:
    def test_valid_yes(self):
        r = Resolution(
            market_id="M001",
            resolved_at=datetime(2025, 6, 1, tzinfo=timezone.utc),
            outcome=ResolutionOutcome.YES,
        )
        assert r.outcome == ResolutionOutcome.YES
        assert r.p_yes_actual == 1.0

    def test_valid_no(self):
        r = Resolution(
            market_id="M001",
            resolved_at=datetime(2025, 6, 1, tzinfo=timezone.utc),
            outcome=ResolutionOutcome.NO,
        )
        assert r.outcome == ResolutionOutcome.NO
        assert r.p_yes_actual == 0.0

    def test_invalid_outcome_rejected(self):
        with pytest.raises(ValidationError):
            Resolution(
                market_id="M001",
                resolved_at=datetime(2025, 6, 1, tzinfo=timezone.utc),
                outcome="MAYBE",
                p_yes_actual=0.5,
            )

    def test_naive_timestamp_string_rejected(self):
        with pytest.raises(ValidationError):
            Resolution.model_validate({
                "market_id": "M001",
                "resolved_at": "2025-06-01T00:00:00",
                "outcome": "YES",
                "p_yes_actual": 1.0,
            })

    def test_extra_field_rejected(self):
        with pytest.raises(ValidationError):
            Resolution.model_validate({
                "market_id": "M001",
                "resolved_at": "2025-06-01T00:00:00+00:00",
                "outcome": "YES",
                "p_yes_actual": 1.0,
                "extra_field": "x",
            })


class TestEvaluationSummary:
    def test_has_evaluable_cases_false_when_zero(self):
        summary = EvaluationSummary(
            experiment_id="P0-TEST",
            evaluated_at=datetime(2025, 6, 1, tzinfo=timezone.utc),
            evaluated_count=0,
        )
        assert summary.has_evaluable_cases() is False

    def test_has_evaluable_cases_true(self):
        summary = EvaluationSummary(
            experiment_id="P0-TEST",
            evaluated_at=datetime(2025, 6, 1, tzinfo=timezone.utc),
            evaluated_count=3,
        )
        assert summary.has_evaluable_cases() is True

    def test_naive_timestamp_string_rejected(self):
        with pytest.raises(ValidationError):
            EvaluationSummary.model_validate({
                "experiment_id": "P0-TEST",
                "evaluated_at": "2025-06-01T00:00:00",
            })

    def test_extra_field_rejected(self):
        with pytest.raises(ValidationError):
            EvaluationSummary.model_validate({
                "experiment_id": "P0-TEST",
                "evaluated_at": "2025-06-01T00:00:00+00:00",
                "extra": "no",
            })
