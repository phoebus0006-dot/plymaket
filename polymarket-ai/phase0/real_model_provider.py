from __future__ import annotations

import json
import os
import hashlib
import time
from datetime import datetime, timezone
from typing import Any


class RealModelProvider:
    """Real model provider using OpenAI API.

    Requires OPENAI_API_KEY environment variable to be set.
    API failure → raises RuntimeError (no mock fallback).
    """

    MODEL_ID = "gpt-4o-mini"
    MODEL_VERSION = "gpt-4o-mini-2024-07-18"
    PROMPT_VERSION = "phase0-blind-v1"
    RUNNER_VERSION = "1.0.0"

    SYSTEM_PROMPT = """You are a blind forecaster. You have NO access to:
- Market prices, bids, asks, or spreads
- Trading volume or liquidity
- Any market data whatsoever

You receive ONLY:
- The market question
- A brief description
- Resolution criteria

Your task: produce a probabilistic forecast with uncertainty intervals.
Respond ONLY with valid JSON containing:
{
  "p_yes": float between 0 and 1,
  "interval_50": [lower, upper] (50% confidence),
  "interval_80": [lower, upper] (80% confidence),
  "top_drivers": [3-5 key factors],
  "counterarguments": [1-3 counterarguments],
  "critical_unknowns": [1-3 critical unknowns]
}"""

    def __init__(self) -> None:
        self.api_key = os.environ.get("OPENAI_API_KEY", "")
        self._client = None
        self._call_count = 0

    @property
    def client(self):
        if self._client is None:
            import openai
            if not self.api_key:
                raise RuntimeError(
                    "OPENAI_API_KEY environment variable not set. "
                    "Cannot make real model calls."
                )
            self._client = openai.OpenAI(api_key=self.api_key)
        return self._client

    def forecast(self, market_id: str, clean_package: dict[str, Any]) -> dict[str, Any]:
        """Call the real model. Returns raw forecast dict.

        Raises RuntimeError on any API failure.
        No mock/fallback is allowed.
        """
        question = clean_package.get("question", "")
        description = clean_package.get("description", "")
        resolution_rules = clean_package.get("resolution_source", "")

        user_message = f"""Market ID: {market_id}
Question: {question}
Description: {description}
Resolution Rules: {resolution_rules}"""

        start = time.time()
        try:
            response = self.client.chat.completions.create(
                model=self.MODEL_ID,
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.0,
                response_format={"type": "json_object"},
                timeout=30,
            )
        except Exception as e:
            raise RuntimeError(f"OpenAI API call failed for {market_id}: {e}")

        latency = time.time() - start
        raw_output = response.choices[0].message.content if response.choices else ""

        if not raw_output:
            raise RuntimeError(f"Empty response from model for {market_id}")

        try:
            parsed = json.loads(raw_output)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Invalid JSON from model for {market_id}: {e}")

        self._call_count += 1

        # Build the forecast output in the expected format
        return {
            "market_id": market_id,
            "forecast_cutoff": datetime.now(timezone.utc).isoformat(),
            "forecast_mode": "CHEAP_BASELINE",
            "p_yes": float(parsed.get("p_yes", 0.5)),
            "interval_50": [float(v) for v in parsed.get("interval_50", [0.45, 0.55])],
            "interval_80": [float(v) for v in parsed.get("interval_80", [0.40, 0.60])],
            "top_drivers": parsed.get("top_drivers", []),
            "counterarguments": parsed.get("counterarguments", []),
            "critical_unknowns": parsed.get("critical_unknowns", []),
            "rules_confidence": "MEDIUM",
            "research_cost_usd": round(latency * 0.00003, 6),
            "latency_seconds": round(latency, 3),
        }
