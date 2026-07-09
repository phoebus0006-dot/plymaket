from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(data: dict[str, Any], exclude: set[str] | None = None) -> bytes:
    filtered = _filter_exclude(data, exclude)
    return json.dumps(filtered, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")


def _filter_exclude(data: dict[str, Any], exclude: set[str] | None) -> dict[str, Any]:
    if exclude is None:
        return {k: v for k, v in data.items() if k != "manifest_hash"}
    return {k: v for k, v in data.items() if k not in exclude}


def compute_hash(data: dict[str, Any], exclude: set[str] | None = None) -> str:
    return hashlib.sha256(canonical_json(data, exclude=exclude)).hexdigest()


def verify_hash(data: dict[str, Any], expected_hash: str, exclude: set[str] | None = None) -> bool:
    actual = compute_hash(data, exclude=exclude)
    return actual == expected_hash
