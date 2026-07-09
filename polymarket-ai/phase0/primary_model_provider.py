from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from typing import Any

import torch
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM


class PrimaryForecastModel:
    """Primary instruction-tuned forecast model.

    Uses google/flan-t5-small. NO hash-based probability fallback.
    If the model output is not a valid probability, the call raises RuntimeError.
    """

    MODEL_ID = "flan-t5-small-forecast-v1"
    MODEL_VERSION = "1.0.0"
    PROMPT_VERSION = "phase0-blind-v2"
    RUNNER_VERSION = "1.0.0"

    PROMPT_TEMPLATE = """Question: {question}
Description: {description}
Resolution rules: {resolution_rules}

Based only on the above information, what is the probability (0 to 1) that this market resolves to YES?
Respond with a single number between 0 and 1:"""

    def __init__(self) -> None:
        self._tokenizer = AutoTokenizer.from_pretrained("google/flan-t5-small")
        self._model = AutoModelForSeq2SeqLM.from_pretrained("google/flan-t5-small")
        self._model.eval()

    def forecast(self, market_id: str, clean_package: dict[str, Any]) -> dict[str, Any]:
        question = clean_package.get("question", "")[:300]
        description = clean_package.get("description", "")[:300]
        resolution_rules = clean_package.get("resolution_source", "")[:200]

        prompt = self.PROMPT_TEMPLATE.format(
            question=question,
            description=description or "Not available.",
            resolution_rules=resolution_rules or "Standard market resolution.",
        )

        start = time.time()
        try:
            inputs = self._tokenizer(prompt, return_tensors="pt", truncation=True, max_length=512)
            with torch.no_grad():
                outputs = self._model.generate(
                    **inputs,
                    max_new_tokens=10,
                    temperature=0.3,
                    do_sample=True,
                )
            latency = time.time() - start
            generated = self._tokenizer.decode(outputs[0], skip_special_tokens=True).strip()
        except Exception as e:
            raise RuntimeError(f"Primary model inference failed for {market_id}: {e}")

        # Parse probability from model output — NO hash fallback
        p_yes = self._extract_probability(generated, market_id)

        return {
            "market_id": market_id,
            "forecast_cutoff": datetime.now(timezone.utc).isoformat(),
            "forecast_mode": "PRIMARY_MODEL",
            "p_yes": round(p_yes, 4),
            "interval_50": [round(max(0.0, p_yes - 0.04), 4), round(min(1.0, p_yes + 0.04), 4)],
            "interval_80": [round(max(0.0, p_yes - 0.10), 4), round(min(1.0, p_yes + 0.10), 4)],
            "top_drivers": ["Primary instruction-tuned model (flan-t5-small)"],
            "counterarguments": ["Small model — may lack nuanced reasoning"],
            "critical_unknowns": ["Larger instruction-tuned model needed for production"],
            "rules_confidence": "LOW",
            "research_cost_usd": None,
            "latency_seconds": round(latency, 3),
        }

    @staticmethod
    def _extract_probability(text: str, market_id: str) -> float:
        """Extract a valid probability from model output. Raises RuntimeError on failure."""
        nums = re.findall(r"0\.\d+|1\.0|^0$|^1$", text.strip())
        if nums:
            val = float(nums[0])
            if 0.0 <= val <= 1.0:
                return val
        try:
            val = float(text.strip())
            if 0.0 <= val <= 1.0:
                return val
        except ValueError:
            pass
        raise RuntimeError(
            f"Primary model output for {market_id} is not a valid probability: '{text[:80]}'"
        )
