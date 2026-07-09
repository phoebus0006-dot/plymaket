from __future__ import annotations

from typing import Any

import requests

CLOB_URL = "https://clob.polymarket.com"


class CLOBSnapshotProvider:
    """Baseline provider using Polymarket CLOB /book endpoint.

    Uses condition_id -> YES token_id mapping to fetch order book data.
    Only accepts markets with active=true, closed=false, enableOrderBook=true.
    """

    def __init__(self, token_ids: dict[str, str]) -> None:
        """token_ids maps condition_id -> YES token_id"""
        self._token_ids = token_ids

    def get_snapshot(self, market_id: str) -> dict[str, Any]:
        token_id = self._token_ids.get(market_id)
        if not token_id:
            raise RuntimeError(f"No CLOB token_id for market {market_id[:20]}...")

        url = f"{CLOB_URL}/book?token_id={token_id}"
        resp = requests.get(url, timeout=15)
        if resp.status_code != 200:
            raise RuntimeError(
                f"CLOB /book failed for token {token_id[:16]}...: HTTP {resp.status_code}"
            )

        data = resp.json()
        bids = data.get("bids", [])
        asks = data.get("asks", [])

        # Parse {price, size} levels
        best_bid = max(float(b["price"]) for b in bids) if bids else None
        best_ask = min(float(a["price"]) for a in asks) if asks else None

        if best_bid is None or best_ask is None:
            raise RuntimeError(f"CLOB /book returned empty orderbook for market {market_id[:20]}...")

        mid = round((best_bid + best_ask) / 2, 6)
        spread = round(best_ask - best_bid, 6)

        return {
            "market_id": market_id,
            "bid": best_bid,
            "ask": best_ask,
            "mid": mid,
            "spread": spread,
        }
