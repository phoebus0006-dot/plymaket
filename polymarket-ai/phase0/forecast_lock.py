from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

from .schemas import Forecast, ForecastMode, ForecastLock


_VERSION_RE = re.compile(r"^v(\d+)\.json$")

_FORECAST_FILENAME = "forecast.json"


def parse_version(filename: str) -> int | None:
    m = _VERSION_RE.match(filename)
    if m:
        return int(m.group(1))
    return None


def find_latest_version(forecasts_dir: str | Path) -> int:
    """Return the highest version number found in forecasts_dir, or 0."""
    p = Path(forecasts_dir)
    if not p.is_dir():
        return 0
    best = 0
    for child in p.iterdir():
        v = parse_version(child.name)
        if v is not None and v > best:
            best = v
    return best


def find_latest_file(forecasts_dir: str | Path) -> Path | None:
    """Return the path to the highest-version forecast file, or None."""
    p = Path(forecasts_dir)
    if not p.is_dir():
        return None
    best_v = 0
    best_path: Path | None = None
    for child in p.iterdir():
        v = parse_version(child.name)
        if v is not None and v > best_v:
            best_v = v
            best_path = child
    return best_path


def compute_forecast_hash(forecast: Forecast) -> str:
    return sha256(
        json.dumps(forecast.model_dump(mode="json"), sort_keys=True).encode("utf-8")
    ).hexdigest()


def compute_package_hash(package: dict[str, Any]) -> str:
    return sha256(
        json.dumps(package, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def lock_forecast(
    experiments_root: str,
    experiment_id: str,
    market_id: str,
    package: dict[str, Any],
    forecast: Forecast,
    forecast_mode: ForecastMode,
) -> ForecastLock:
    """Create a ForecastLock without writing or transitioning state.

    Reads the latest forecast artifact from
    ``<forecasts>/<market_id>/v{version}.json`` to verify it exists,
    then builds and returns the lock.  Does NOT write anything.
    """
    # Verify argument consistency BEFORE reading disk
    arg_violations = []
    if market_id != forecast.market_id:
        arg_violations.append(f"arg market_id {market_id} != forecast.market_id {forecast.market_id}")
    if forecast_mode != forecast.forecast_mode:
        arg_violations.append(f"arg forecast_mode {forecast_mode} != forecast.forecast_mode {forecast.forecast_mode}")
    if arg_violations:
        raise RuntimeError(f"Lock forecast argument consistency check failed: {'; '.join(arg_violations)}")

    forecasts_dir = Path(experiments_root) / experiment_id / "forecasts" / market_id
    latest_ver = find_latest_version(forecasts_dir)
    if latest_ver == 0:
        raise FileNotFoundError(
            f"no forecast artifacts found in {forecasts_dir}"
        )
    latest_path = forecasts_dir / f"v{latest_ver}.json"
    if not latest_path.is_file():
        raise FileNotFoundError(
            f"latest forecast artifact not found: {latest_path}"
        )

    raw_forecast: dict[str, Any] = json.loads(latest_path.read_text(encoding="utf-8"))
    disk_forecast = Forecast(**raw_forecast)  # validate schema

    # Verify disk artifact matches input forecast
    violations = []
    if disk_forecast.market_id != forecast.market_id:
        violations.append(f"disk market_id {disk_forecast.market_id} != input {forecast.market_id}")
    if abs(disk_forecast.p_yes - forecast.p_yes) > 0.0001:
        violations.append(f"disk p_yes {disk_forecast.p_yes} != input {forecast.p_yes}")
    if disk_forecast.forecast_cutoff != forecast.forecast_cutoff:
        violations.append("forecast_cutoff mismatch")
    if disk_forecast.forecast_mode != forecast.forecast_mode:
        violations.append("forecast_mode mismatch")
    disk_hash = sha256(json.dumps(raw_forecast, sort_keys=True).encode()).hexdigest()
    input_hash = sha256(json.dumps(forecast.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()
    if disk_hash != input_hash:
        violations.append("canonical hash mismatch")
    if violations:
        raise RuntimeError(f"Lock forecast consistency check failed: {'; '.join(violations)}")

    # Compute package_hash from the raw package dict.
    # PriceRevealService._verify_package_hash uses the raw dict from the file.
    package_hash = compute_package_hash(package)
    forecast_hash = compute_forecast_hash(forecast)

    forecast_artifact_raw = json.dumps(raw_forecast, sort_keys=True).encode("utf-8")
    forecast_artifact_hash = sha256(forecast_artifact_raw).hexdigest()

    lock = ForecastLock(
        forecast_id=f"{market_id}_{latest_ver}",
        market_id=market_id,
        forecast_version=latest_ver,
        forecast_cutoff=forecast.forecast_cutoff,
        package_hash=package_hash,
        forecast_mode=forecast_mode,
        raw_probability=forecast.p_yes,
        locked_at=datetime.now(timezone.utc),
        forecast_hash=forecast_hash,
        forecast_artifact_hash=forecast_artifact_hash,
    )
    return lock
