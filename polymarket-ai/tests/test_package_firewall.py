from __future__ import annotations

from pathlib import Path

import pytest

from phase0.package_validator import (
    validate_package, normalize_key, MarketTaintError,
)


class TestNormalizeKey:
    def test_snake_case_unchanged(self):
        assert normalize_key("best_ask") == "best_ask"

    def test_camel_case_to_snake(self):
        assert normalize_key("bestAsk") == "best_ask"

    def test_pascal_case_to_snake(self):
        assert normalize_key("BestAsk") == "best_ask"

    def test_hyphen_to_underscore(self):
        assert normalize_key("best-ask") == "best_ask"

    def test_spaces_to_underscore(self):
        assert normalize_key("best ask") == "best_ask"

    def test_trailing_underscores_stripped(self):
        assert normalize_key("best_ask_") == "best_ask"

    def test_duplicate_underscores_collapsed(self):
        assert normalize_key("best___ask") == "best_ask"

    def test_mixed_case_hyphen_space(self):
        assert normalize_key("Best-Ask Value") == "best_ask_value"


class TestValidatePackage:
    def test_clean_package_passes(self):
        pkg = {
            "market_id": "M001",
            "question": "Test?",
            "description": "Desc",
            "resolution_source": "https://example.com",
            "outcomes": ["Yes", "No"],
            "evidence": [{"published_at": "2025-05-01T00:00:00+00:00", "source_url": "https://news.example.com"}],
            "package_created_at": "2025-05-15T00:00:00+00:00",
        }
        result = validate_package(pkg)
        assert result.market_id == "M001"

    def test_rejects_best_ask(self):
        pkg = {
            "market_id": "M001",
            "question": "Test?",
            "description": "Desc",
            "resolution_source": "https://example.com",
            "outcomes": ["Yes", "No"],
            "package_created_at": "2025-05-15T00:00:00+00:00",
            "best_ask": 0.5,
        }
        with pytest.raises(MarketTaintError, match="best_ask"):
            validate_package(pkg)

    def test_rejects_bestAsk_camelCase(self):
        pkg = {
            "market_id": "M001",
            "question": "Test?",
            "description": "Desc",
            "resolution_source": "https://example.com",
            "outcomes": ["Yes", "No"],
            "package_created_at": "2025-05-15T00:00:00+00:00",
            "bestAsk": 0.65,
        }
        with pytest.raises(MarketTaintError):
            validate_package(pkg)

    def test_rejects_nested_taint(self):
        pkg = {
            "market_id": "M001",
            "question": "Test?",
            "description": "Desc",
            "resolution_source": "https://example.com",
            "outcomes": ["Yes", "No"],
            "evidence": [{"price": 0.5}],
            "package_created_at": "2025-05-15T00:00:00+00:00",
        }
        with pytest.raises(MarketTaintError, match="price"):
            validate_package(pkg)

    def test_rejects_forbidden_domain(self):
        pkg = {
            "market_id": "M001",
            "question": "Test?",
            "description": "Desc",
            "resolution_source": "https://polymarket.com/event",
            "outcomes": ["Yes", "No"],
            "package_created_at": "2025-05-15T00:00:00+00:00",
        }
        with pytest.raises(MarketTaintError, match="polymarket"):
            validate_package(pkg)

    def test_rejects_subdomain_forbidden_domain(self):
        pkg = {
            "market_id": "M001",
            "question": "Test?",
            "description": "Desc",
            "resolution_source": "https://sub.polymarket.com/xyz",
            "outcomes": ["Yes", "No"],
            "package_created_at": "2025-05-15T00:00:00+00:00",
        }
        with pytest.raises(MarketTaintError, match="polymarket"):
            validate_package(pkg)

    def test_allows_safe_markets_url(self):
        pkg = {
            "market_id": "M001",
            "question": "Test?",
            "description": "Desc",
            "resolution_source": "https://markets.example.com/data",
            "outcomes": ["Yes", "No"],
            "package_created_at": "2025-05-15T00:00:00+00:00",
        }
        result = validate_package(pkg)
        assert result is not None

    def test_rejects_mid(self):
        pkg = {
            "market_id": "M001",
            "question": "Test?",
            "description": "Desc",
            "resolution_source": "https://example.com",
            "outcomes": ["Yes", "No"],
            "package_created_at": "2025-05-15T00:00:00+00:00",
            "mid": 0.5,
        }
        with pytest.raises(MarketTaintError):
            validate_package(pkg)

    def test_rejects_volume(self):
        pkg = {
            "market_id": "M001",
            "question": "Test?",
            "description": "Desc",
            "resolution_source": "https://example.com",
            "outcomes": ["Yes", "No"],
            "package_created_at": "2025-05-15T00:00:00+00:00",
            "volume": 1000,
        }
        with pytest.raises(MarketTaintError):
            validate_package(pkg)

    def test_rejects_domain_in_evidence_urls(self):
        pkg = {
            "market_id": "M001",
            "question": "Test?",
            "description": "Desc",
            "resolution_source": "https://example.com",
            "outcomes": ["Yes", "No"],
            "evidence": [{"source_url": "https://kalshi.com/trade"}],
            "package_created_at": "2025-05-15T00:00:00+00:00",
        }
        with pytest.raises(MarketTaintError, match="kalshi"):
            validate_package(pkg)

    def test_naive_timestamp_in_package_rejected(self):
        pkg = {
            "market_id": "M001",
            "question": "Test?",
            "description": "Desc",
            "resolution_source": "https://example.com",
            "outcomes": ["Yes", "No"],
            "package_created_at": "2025-05-15T00:00:00",
        }
        with pytest.raises(ValueError, match="timezone-aware"):
            validate_package(pkg)

    def test_extra_field_causes_pydantic_failure(self):
        pkg = {
            "market_id": "M001",
            "question": "Test?",
            "description": "Desc",
            "resolution_source": "https://example.com",
            "outcomes": ["Yes", "No"],
            "package_created_at": "2025-05-15T00:00:00+00:00",
            "extra_field": "should be rejected",
        }
        import json
        from phase0.schemas import CleanForecastPackage
        with pytest.raises(Exception):
            CleanForecastPackage(**json.loads(json.dumps(pkg)))
