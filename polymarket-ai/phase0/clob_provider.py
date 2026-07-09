from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

CLOB_URL = "https://clob.polymarket.com"


class CLOBSnapshotProvider:
    """Baseline provider using Polymarket CLOB /book endpoint.

    token_ids maps condition_id -> YES token_id.
    """

    def __init__(self, token_ids: dict[str, str], output_dir: str | None = None) -> None:
        self._token_ids = token_ids
        self._output_dir = output_dir

    def get_snapshot(self, market_id: str) -> dict[str, Any]:
        token_id = self._token_ids.get(market_id)
        if not token_id:
            raise RuntimeError(f"No CLOB token_id for market {market_id[:20]}...")

        account_id = "0x0000000000000000000000000000000000000000"
        url = f"{CLOB_URL}/book?token_id={token_id}"
        resp = requests.get(url, timeout=15)
        if resp.status_code != 200:
            raise RuntimeError(f"CLOB /book failed for token {token_id[:16]}...: HTTP {resp.status_code}")

        data = resp.json()
        bids = data.get("bids", [])
        asks = data.get("asks", [])

        best_bid = max(float(b["price"]) for b in bids) if bids else None
        best_ask = min(float(a["price"]) for a in asks) if asks else None

        if best_bid is None or best_ask is None:
            raise RuntimeError(f"CLOB /book returned empty orderbook for {market_id[:20]}...")

        mid = round((best_bid + best_ask) / 2, 6)
        spread = round(best_ask - best_bid, 6)
        captured_at = datetime.now(timezone.utc)

        # Persist raw /book response
        raw_orderbook_hash = hashlib.sha256(
            json.dumps(data, sort_keys=True).encode()
        ).hexdigest()

        if self._output_dir:
            raw_dir = Path(self._output_dir) / "clob_raw"
            raw_dir.mkdir(parents=True, exist_ok=True)
            raw_path = raw_dir / f"{market_id}_{captured_at.strftime('%Y%m%dT%H%M%S')}.json"
            raw_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        return {
            "market_id": market_id,
            "token_id": token_id,
            "bid": best_bid,
            "ask": best_ask,
            "mid": mid,
            "spread": spread,
            "raw_orderbook_hash": raw_orderbook_hash,
            "captured_at": captured_at.isoformat(),
            "endpoint": CLOB_URL,
        }
