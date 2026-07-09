from __future__ import annotations

import ast
import hashlib
import json
from datetime import datetime, timezone
from typing import Any

import requests

from .schemas import MarketUniverseRecord

GAMMA_URL = "https://gamma-api.polymarket.com"


class PolymarketClient:
    """Live Polymarket API client.

    Uses Gamma API (public read-only) for market data and prices.
    No API key required.
    """

    def __init__(self, base_url: str = GAMMA_URL, timeout: int = 30) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def fetch_markets(
        self,
        limit: int = 50,
        offset: int = 0,
        closed: bool = False,
        tag: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch markets from Gamma API."""
        params: dict[str, Any] = {
            "limit": min(limit, 100),
            "offset": offset,
            "closed": str(closed).lower(),
        }
        if tag:
            params["tag"] = tag

        resp = requests.get(
            f"{self.base_url}/markets",
            params=params,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else data.get("data", data.get("results", [data]))

    @staticmethod
    def market_to_universe_record(raw: dict[str, Any], source: str = "polymarket_gamma") -> MarketUniverseRecord | None:
        """Convert a Gamma API market dict to a MarketUniverseRecord.

        Returns None if the record cannot be validated.
        """
        mid = raw.get("conditionId", raw.get("condition_id", "")).strip()
        question = raw.get("question", "").strip()
        if not mid or not question:
            return None

        description = raw.get("description", raw.get("outcomesDescription", ""))
        desc_str = description if isinstance(description, str) else (description[0] if isinstance(description, list) and description else "")
        raw_res = raw.get("resolutionSource", raw.get("rules", ""))
        resolution_rules = raw_res if raw_res else desc_str

        close_time_str = raw.get("endDate", raw.get("endDateIso", ""))
        close_time: datetime | None = None
        if close_time_str:
            try:
                close_time = datetime.fromisoformat(close_time_str.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                pass

        category = raw.get("category", raw.get("tag", ""))
        tags = []
        if raw.get("featured"):
            tags.append("featured")
        if raw.get("negRisk"):
            tags.append("neg_risk")

        raw_bytes = json.dumps(raw, sort_keys=True, default=str).encode("utf-8")
        raw_artifact_hash = hashlib.sha256(raw_bytes).hexdigest()

        normalized = {
            "market_id": mid,
            "question": question,
            "description": description if isinstance(description, str) else json.dumps(description),
            "resolution_rules": resolution_rules if isinstance(resolution_rules, str) else json.dumps(resolution_rules),
            "close_time": close_time.isoformat() if close_time else "",
            "category": category,
            "subcategory": "",
            "source": source,
            "tags": tags,
        }
        norm_bytes = json.dumps(normalized, sort_keys=True).encode("utf-8")
        normalized_artifact_hash = hashlib.sha256(norm_bytes).hexdigest()

        outcomes = PolymarketClient._parse_json_list(raw.get("outcomes", []))
        clob_tokens = PolymarketClient._parse_json_list(raw.get("clobTokenIds", ""))
        yes_token = ""
        if outcomes and clob_tokens:
            try:
                yes_token = PolymarketClient.resolve_yes_token(outcomes, clob_tokens)
            except ValueError:
                pass

        return MarketUniverseRecord(
            market_id=mid,
            question=question,
            description=str(description) if description else "",
            resolution_rules=str(resolution_rules) if resolution_rules else "",
            close_time=close_time,
            category=category,
            subcategory="",
            source=source,
            retrieved_at=datetime.now(timezone.utc),
            raw_artifact_hash=raw_artifact_hash,
            parser_version="gamma-v1",
            normalized_artifact_hash=normalized_artifact_hash,
            tags=tags,
            enable_order_book=bool(raw.get("enableOrderBook", False)),
            clob_token_ids=clob_tokens,
            yes_token_id=yes_token,
            outcomes=outcomes,
            accepting_orders=bool(raw.get("acceptingOrders", False)),
        )

    @staticmethod
    def _parse_json_list(value: Any) -> list[str]:
        """Parse a value that may be a JSON string list, Python repr string list, or already a list."""
        if isinstance(value, list):
            return [str(v) for v in value]
        if isinstance(value, str):
            value_stripped = value.strip()
            if value_stripped.startswith("["):
                try:
                    import json as _json
                    parsed = _json.loads(value_stripped)
                    if isinstance(parsed, list):
                        return [str(v) for v in parsed]
                except Exception:
                    pass
                try:
                    import ast
                    parsed = ast.literal_eval(value_stripped)
                    if isinstance(parsed, list):
                        return [str(v) for v in parsed]
                except Exception:
                    pass
        return []

    @staticmethod
    def resolve_yes_token(outcomes_raw: Any, tokens_raw: Any) -> str:
        """Resolve the YES token from outcomes and clobTokenIds.

        Supports outcomes as JSON string, Python repr string, or list.
        Supports clobTokenIds as JSON string, Python repr string, or list.

        Returns the YES token ID.
        Raises ValueError if unambiguous mapping is impossible.
        """
        outcomes = PolymarketClient._parse_json_list(outcomes_raw)
        clob_tokens = PolymarketClient._parse_json_list(tokens_raw)

        if not outcomes:
            raise ValueError("no outcomes parsed")
        if not clob_tokens:
            raise ValueError("no clobTokenIds parsed")
        if len(outcomes) != len(clob_tokens):
            raise ValueError(
                f"outcomes count ({len(outcomes)}) != clobTokenIds count ({len(clob_tokens)})"
            )

        yes_idx = -1
        for i, o in enumerate(outcomes):
            if o.strip().upper() in ("YES", "Y", "1"):
                if yes_idx >= 0:
                    raise ValueError(f"multiple YES outcomes found in {outcomes}")
                yes_idx = i

        if yes_idx < 0:
            raise ValueError(f"no YES outcome found in {outcomes}")

        return str(clob_tokens[yes_idx])

    @staticmethod
    def gamma_price_snapshot(market: dict[str, Any]) -> dict[str, Any] | None:
        """Extract a price snapshot directly from a Gamma API market response.

        Gamma includes bestBid, bestAsk, lastTradePrice, outcomePrices directly.
        """
        bid = market.get("bestBid")
        ask = market.get("bestAsk")
        last_price = market.get("lastTradePrice")
        outcome_prices = market.get("outcomePrices")

        bid_f = float(bid) if bid is not None else None
        ask_f = float(ask) if ask is not None else None
        mid = round((bid_f + ask_f) / 2, 6) if bid_f is not None and ask_f is not None else None
        spread = round(ask_f - bid_f, 6) if bid_f is not None and ask_f is not None else None

        return {
            "market_id": market.get("conditionId", market.get("condition_id", "")),
            "bid": bid_f,
            "ask": ask_f,
            "mid": mid,
            "spread": spread,
            "volume": market.get("volumeNum"),
        }

    def fetch_market_snapshot(self, market_id: str) -> dict[str, Any] | None:
        """Fetch current snapshot for a single market by condition_id."""
        resp = requests.get(
            f"{self.base_url}/markets/{market_id}",
            timeout=self.timeout,
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        market = resp.json()
        if isinstance(market, list):
            market = market[0] if market else None
        if not market:
            return None
        return self.gamma_price_snapshot(market)


def resolve_yes_token(outcomes_raw: Any, tokens_raw: Any) -> str:
    """Module-level convenience wrapper for PolymarketClient.resolve_yes_token."""
    return PolymarketClient.resolve_yes_token(outcomes_raw, tokens_raw)
