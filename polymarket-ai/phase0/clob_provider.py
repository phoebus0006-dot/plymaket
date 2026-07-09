from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

import requests

CLOB_URL = "https://clob.polymarket.com"


class CLOBSnapshotProvider:
    """Baseline provider using real CLOB orderbook data.

    Requires token_id (from Gamma API) to query the orderbook.
    Strictly enforces: must be called AFTER forecast lock is verified.
    """

    def __init__(self, token_ids: dict[str, str]) -> None:
        """
        Args:
            token_ids: mapping of condition_id -> clob_token_id (first token from clobTokenIds)
        """
        self._token_ids = token_ids
        self._base_url = CLOB_URL

    def get_snapshot(self, market_id: str) -> dict[str, Any]:
        """Fetch live CLOB orderbook for a market.

        Args:
            market_id: The condition_id of the market.

        Returns:
            Dict with bid, ask, mid, spread, token_id, source endpoint.
        """
        token_id = self._token_ids.get(market_id)
        if not token_id:
            raise RuntimeError(f"No CLOB token_id known for market {market_id[:20]}...")

        url = f"{self._base_url}/orderbook?token_id={token_id}"
        resp = requests.get(url, timeout=15)
        if resp.status_code != 200:
            raise RuntimeError(
                f"CLOB orderbook fetch failed for token {token_id[:16]}...: HTTP {resp.status_code}"
            )

        data = resp.json()
        bids = data.get("bids", [])
        asks = data.get("asks", [])

        best_bid = float(bids[0][0]) if bids else None
        best_ask = float(asks[0][0]) if asks else None
        mid = round((best_bid + best_ask) / 2, 6) if best_bid is not None and best_ask is not None else None
        spread = round(best_ask - best_bid, 6) if best_bid is not None and best_ask is not None else None

        # Compute raw orderbook hash for provenance
        raw_hash = hashlib.sha256(
            json.dumps(data, sort_keys=True).encode("utf-8")
        ).hexdigest()

        return {
            "market_id": market_id,
            "token_id": token_id,
            "bid": best_bid,
            "ask": best_ask,
            "mid": mid,
            "spread": spread,
            "volume": None,
            "raw_orderbook_hash": raw_hash,
            "source_endpoint": url.replace(token_id, token_id[:8] + "..."),
            "captured_at": datetime.now(timezone.utc).isoformat(),
        }
