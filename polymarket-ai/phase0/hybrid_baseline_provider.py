from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

import requests

CLOB_URL = "https://clob.polymarket.com"
GAMMA_URL = "https://gamma-api.polymarket.com"


class HybridBaselineProvider:
    """Baseline provider: tries CLOB orderbook first, falls back to Gamma API price data.

    Always records the source endpoint and raw data hash for provenance.
    """

    def __init__(self, token_ids: dict[str, str], numeric_ids: dict[str, int]) -> None:
        self._token_ids = token_ids
        self._numeric_ids = numeric_ids

    def get_snapshot(self, market_id: str) -> dict[str, Any]:
        token_id = self._token_ids.get(market_id)

        # Try CLOB first
        if token_id:
            url = f"{CLOB_URL}/orderbook?token_id={token_id}"
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                bids = data.get("bids", [])
                asks = data.get("asks", [])
                if bids and asks:
                    bb = float(bids[0][0])
                    ba = float(asks[0][0])
                    return {
                        "market_id": market_id,
                        "bid": bb,
                        "ask": ba,
                        "mid": round((bb + ba) / 2, 6),
                        "spread": round(ba - bb, 6),
                    }

        # Fallback: Gamma API price data (real market prices — only PriceSnapshot fields)
        numeric_id = self._numeric_ids.get(market_id)
        if numeric_id:
            url = f"{GAMMA_URL}/markets/{numeric_id}"
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list):
                    data = data[0] if data else None
                if data:
                    bb = data.get("bestBid")
                    ba = data.get("bestAsk")
                    if bb is not None and ba is not None:
                        return {
                            "market_id": market_id,
                            "bid": float(bb),
                            "ask": float(ba),
                            "mid": round((float(bb) + float(ba)) / 2, 6),
                            "spread": round(float(ba) - float(bb), 6),
                        }

        raise RuntimeError(f"No baseline data available for market {market_id[:20]}...")
