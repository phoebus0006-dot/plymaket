from __future__ import annotations

import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .schemas import MarketUniverseRecord


def _hash_content(data: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _normalize_record(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize a raw market record into a canonical form.

    Strips unknown fields, normalizes keys, ensures required fields exist.
    """
    normalized: dict[str, Any] = {}
    field_map = {
        "market_id": ("market_id", str),
        "question": ("question", str),
        "description": ("description", str),
        "resolution_rules": ("resolution_rules", str),
        "close_time": ("close_time", str),
        "category": ("category", str),
        "subcategory": ("subcategory", str),
        "source": ("source", str),
        "tags": ("tags", list),
    }
    for raw_key, (norm_key, expected_type) in field_map.items():
        val = raw.get(raw_key, raw.get(norm_key, ""))
        if expected_type == list and not isinstance(val, list):
            val = []
        normalized[norm_key] = val
    return normalized


def ingest_market_record(
    raw: dict[str, Any],
    source: str = "fixture",
    parser_version: str = "v1",
) -> MarketUniverseRecord:
    """Ingest a single raw market record into a validated MarketUniverseRecord.

    Raises ValueError if the record cannot be validated.
    """
    mid = raw.get("market_id", raw.get("market_id", "")).strip()
    if not mid:
        raise ValueError("Market record missing market_id")

    resolution_rules = raw.get("resolution_rules", raw.get("resolution_rules", "")).strip()
    if not resolution_rules:
        raise ValueError(f"Market {mid}: missing resolution_rules")

    raw_artifact_hash = _hash_content(raw)
    normalized = _normalize_record(raw)
    normalized_artifact_hash = _hash_content(normalized)

    close_time_str = normalized.get("close_time", "")
    close_time: datetime | None = None
    if close_time_str:
        try:
            close_time = datetime.fromisoformat(close_time_str)
            if close_time.tzinfo is None:
                close_time = close_time.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            raise ValueError(f"Market {mid}: invalid close_time: {close_time_str}")

    # Parse outcomes and clobTokenIds for YES token mapping
    outcomes_raw = raw.get("outcomes", raw.get("outcomes", []))
    tokens_raw = raw.get("clobTokenIds", raw.get("clobTokenIds", ""))

    from .polymarket_client import PolymarketClient
    if isinstance(outcomes_raw, list) and outcomes_raw and tokens_raw:
        try:
            yes_token = PolymarketClient.resolve_yes_token(outcomes_raw, tokens_raw)
        except ValueError:
            yes_token = ""
    else:
        yes_token = ""

    return MarketUniverseRecord(
        market_id=mid,
        question=normalized.get("question", ""),
        description=normalized.get("description", ""),
        resolution_rules=resolution_rules,
        close_time=close_time,
        category=normalized.get("category", ""),
        subcategory=normalized.get("subcategory", ""),
        source=source,
        retrieved_at=datetime.now(timezone.utc),
        raw_artifact_hash=raw_artifact_hash,
        parser_version=parser_version,
        normalized_artifact_hash=normalized_artifact_hash,
        tags=normalized.get("tags", []),
        enable_order_book=bool(raw.get("enableOrderBook", raw.get("enable_order_book", False))),
        accepting_orders=bool(raw.get("acceptingOrders", raw.get("accepting_orders", False))),
        outcomes=outcomes_raw if isinstance(outcomes_raw, list) else [],
        clob_token_ids=[str(t) for t in (tokens_raw if isinstance(tokens_raw, list) else [])],
        yes_token_id=yes_token,
    )


def ingest_market_universe(
    records: list[dict[str, Any]],
    source: str = "fixture",
    parser_version: str = "v1",
) -> tuple[list[MarketUniverseRecord], list[str]]:
    """Ingest a list of raw market records.

    Returns (valid_records, error_messages).
    Invalid records are not silently skipped — each has an error message.
    """
    valid: list[MarketUniverseRecord] = []
    errors: list[str] = []

    for i, raw in enumerate(records):
        try:
            rec = ingest_market_record(raw, source=source, parser_version=parser_version)
            valid.append(rec)
        except ValueError as e:
            errors.append(f"[{i}] {e}")

    return valid, errors


def load_market_universe_json(path: str | Path, source: str = "fixture") -> tuple[list[MarketUniverseRecord], list[str]]:
    """Load and ingest market universe from a JSON file.

    File format: list of objects with market_id, question, resolution_rules, etc.
    """
    raw_data: list[dict[str, Any]] = json.loads(Path(path).read_text(encoding="utf-8"))
    return ingest_market_universe(raw_data, source=source)
