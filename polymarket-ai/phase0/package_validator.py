from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urlparse
from typing import Any

from phase0.schemas import CleanForecastPackage


FORBIDDEN_FIELD_NAMES: set[str] = {
    "price",
    "current_price",
    "market_price",
    "market_probability",
    "implied_probability",
    "bid",
    "best_bid",
    "ask",
    "best_ask",
    "mid",
    "midpoint",
    "spread",
    "volume",
    "price_history",
    "market_trend",
    "betting_odds",
    "trader_sentiment",
    "orderbook",
}

FORBIDDEN_SOURCE_DOMAINS: set[str] = {
    "polymarket.com",
    "predictionmarket.com",
    "kalshi.com",
}


class MarketTaintError(ValueError):
    pass


def normalize_key(key: str) -> str:
    key = re.sub(r"([a-z])([A-Z])", r"\1_\2", key)
    key = key.replace("-", "_").replace(" ", "_")
    key = key.lower()
    key = re.sub(r"_+", "_", key)
    return key.strip("_")


def _scan_dict(data: dict[str, Any], path: str = "") -> list[str]:
    violations: list[str] = []
    for key, value in data.items():
        current_path = f"{path}.{key}" if path else key
        norm_key = normalize_key(key)
        if norm_key in FORBIDDEN_FIELD_NAMES:
            violations.append(
                f"Field '{current_path}' (normalized: '{norm_key}') is forbidden"
            )
        if isinstance(value, dict):
            violations.extend(_scan_dict(value, current_path))
        elif isinstance(value, list):
            violations.extend(_scan_list(value, current_path))
    return violations


def _scan_list(data: list[Any], path: str = "") -> list[str]:
    violations: list[str] = []
    for i, item in enumerate(data):
        current_path = f"{path}[{i}]"
        if isinstance(item, dict):
            violations.extend(_scan_dict(item, current_path))
        elif isinstance(item, list):
            violations.extend(_scan_list(item, current_path))
    return violations


URL_FIELD_NAMES: set[str] = {
    "source_url",
    "source",
    "resolution_source",
    "url",
    "urls",
    "link",
    "links",
    "href",
    "website",
    "reference",
    "citation",
}

_URL_RE = re.compile(r"https?://[^\s\"'>]+")


def _recursive_urls(data: Any, seen: set[int] | None = None) -> list[str]:
    """Recursively scan any data structure for URL-like strings.

    Checks both:
    1. Values under known URL field names.
    2. Any string value that matches http(s):// URL pattern.
    """
    if seen is None:
        seen = set()
    urls: list[str] = []

    stack: list[tuple[Any, str]] = [(data, "")]
    while stack:
        node, parent_key = stack.pop()
        nid = id(node)
        if nid in seen:
            continue
        seen.add(nid)

        norm_parent = normalize_key(parent_key)
        if isinstance(node, dict):
            for key, val in node.items():
                norm_key = normalize_key(key)
                if isinstance(val, str) and val:
                    if norm_key in URL_FIELD_NAMES or _URL_RE.match(val):
                        urls.append(val)
                    else:
                        m = _URL_RE.search(val)
                        if m:
                            urls.append(m.group(0))
                else:
                    stack.append((val, key))
        elif isinstance(node, list):
            for i, item in enumerate(node):
                stack.append((item, f"{parent_key}[{i}]"))
        elif isinstance(node, str) and node:
            if _URL_RE.match(node):
                urls.append(node)
            else:
                m = _URL_RE.search(node)
                if m:
                    urls.append(m.group(0))
    return urls


def _extract_source_urls(package: dict[str, Any]) -> list[str]:
    return _recursive_urls(package)


def _check_hostname(url: str) -> str | None:
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
        if hostname is None:
            return None
        hostname = hostname.lower()
        for blocked in FORBIDDEN_SOURCE_DOMAINS:
            if hostname == blocked or hostname.endswith("." + blocked):
                return f"URL '{url}' has forbidden hostname '{hostname}' " \
                       f"(matched block '{blocked}')"
    except Exception:
        pass
    return None


def _check_source_domains(package: dict[str, Any]) -> list[str]:
    violations: list[str] = []
    urls = _extract_source_urls(package)
    seen = set()
    for url in urls:
        if url in seen:
            continue
        seen.add(url)
        result = _check_hostname(url)
        if result is not None:
            violations.append(result)
    return violations


def validate_package(package: dict[str, Any]) -> CleanForecastPackage:
    violations: list[str] = []

    field_violations = _scan_dict(package)
    violations.extend(field_violations)

    domain_violations = _check_source_domains(package)
    violations.extend(domain_violations)

    if violations:
        raise MarketTaintError("; ".join(violations))

    payload = dict(package)
    if "package_created_at" in payload:
        val = payload["package_created_at"]
        if isinstance(val, str):
            ts = datetime.fromisoformat(val)
            if ts.tzinfo is None:
                raise ValueError("package_created_at must be timezone-aware")
            payload["package_created_at"] = ts.astimezone(timezone.utc)

    return CleanForecastPackage(**payload)
