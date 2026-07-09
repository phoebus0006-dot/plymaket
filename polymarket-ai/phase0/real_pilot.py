from __future__ import annotations

import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .polymarket_client import PolymarketClient
from .market_universe import ingest_market_universe
from .sampling import generate_manifest_markets
from .manifest import create_manifest, freeze_manifest
from .state import EventStore, ExperimentStateManager
from .package_validator import validate_package
from .schemas import (
    ForecastMode,
    PackageArtifact,
    PriceSnapshot,
)
from .forecast_lock import lock_forecast
from .blind_forecast_runner import BlindForecastRunner
from .price_reveal_service import PriceRevealService
from .clob_provider import CLOBSnapshotProvider


def run_real_pilot(
    output_dir: str | Path,
    seed: str = "phase0-real-v1",
    target_count: int = 30,
    model_provider=None,
) -> dict[str, Any]:
    """Run the Phase 0 Pilot using live Polymarket data.

    Args:
        output_dir: Where to write artifacts.
        seed: RNG seed for stratified sampling.
        target_count: Target number of markets.
        model_provider: A provider with .forecast(market_id, clean_package) method.
                        If None, the pipeline will not produce forecasts.

    Returns:
        Dict with status, ledger, forecast_ledger, baseline_ledger.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    experiment_id = "P0-REAL-PILOT"
    started_at = datetime.now(timezone.utc)
    ledger: list[dict[str, Any]] = []
    forecast_ledger: list[dict[str, Any]] = []
    baseline_ledger: list[dict[str, Any]] = []

    def _record(mid: str, status: str, detail: str = "", **kw: Any) -> None:
        entry = {
            "market_id": mid,
            "status": status,
            "detail": detail,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
        entry.update(kw)
        ledger.append(entry)

    # ── 1. Fetch live universe from Polymarket Gamma API ──
    print("Fetching live markets from Polymarket Gamma API...")
    client = PolymarketClient()
    raw_markets = client.fetch_markets(limit=100, closed=False)

    # Filter out sports markets
    sports_keywords = ["NBA", "NFL", "NHL", "MLB", "FIFA", "UFC", "NCAA", "EPL", "NCAAB"]
    raw_markets = [
        m for m in raw_markets
        if not any(s in (m.get("question", "") or "") for s in sports_keywords)
    ]
    print(f"  {len(raw_markets)} non-sports markets fetched")

    # Convert to universe records
    universe_records = []
    for m in raw_markets:
        rec = client.market_to_universe_record(m, source="polymarket_gamma")
        if rec:
            universe_records.append(rec)
            _record(rec.market_id, "IMPORTED",
                    f"source=polymarket_gamma",
                    raw_artifact_hash=rec.raw_artifact_hash)

    print(f"  {len(universe_records)} valid universe records")

    # Filter for CLOB-eligible markets
    eligible_records = []
    for rec in universe_records:
        reasons = []
        mid = rec.market_id
        raw_mkt = next((m for m in raw_markets if m.get("conditionId","") == mid or m.get("id","") == mid), None)
        if raw_mkt:
            if not raw_mkt.get("active", False):
                reasons.append("active=false")
            if raw_mkt.get("closed", True):
                reasons.append("closed=true")
            if not raw_mkt.get("enableOrderBook", False):
                reasons.append("enableOrderBook=false")
            if not raw_mkt.get("acceptingOrders", False):
                reasons.append("acceptingOrders=false")
        if not rec.yes_token_id:
            reasons.append("no YES token mapping")
        if reasons:
            _record(mid, "EXCLUDED_PRE_FORECAST", "; ".join(reasons))
        else:
            eligible_records.append(rec)

    # Build market_id → clob_token_id mapping for CLOB baseline capture
    token_ids = {r.market_id: r.yes_token_id for r in eligible_records if r.yes_token_id}

    if len(eligible_records) < 20:
        return {"status": "INSUFFICIENT_MARKETS", "count": len(eligible_records),
                "ledger": ledger}

    # ── 2. Stratified sampling ──
    cutoff = datetime.now(timezone.utc)
    entries, exclusions = generate_manifest_markets(
        [r.model_dump(mode="json") for r in eligible_records],
        selection_cutoff=cutoff,
        seed=seed,
        target_count=target_count,
    )
    for exc in exclusions:
        mid = exc.split(":")[0]
        _record(mid, "EXCLUDED_PRE_FORECAST", exc)

    if len(entries) < 20:
        return {"status": "INSUFFICIENT_SAMPLED", "selected": len(entries),
                "ledger": ledger}

    print(f"  {len(entries)} markets sampled")

    # ── 3. Manifest freeze ──
    manifest = create_manifest(
        experiment_id,
        [{"market_id": e.market_id, "question": e.question} for e in entries],
        selection_cutoff=cutoff,
    )
    manifest_dir = out / "manifest"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    freeze_manifest(manifest, manifest_dir)
    print(f"  Manifest frozen at {manifest_dir / 'manifest.json'}")

    # ── 4. Experiment state ──
    experiments_root = out / "experiment_logs"
    store = EventStore(experiments_root / experiment_id / "events.jsonl")
    sm = ExperimentStateManager(store)
    sm.record_experiment_created(experiment_id, manifest)
    sm.record_experiment_activated(experiment_id)

    # ── 5. Helper: package from universe record ──
    universe_by_id = {r.market_id: r for r in eligible_records}

    def _build_pkg(mid: str, uni) -> dict[str, Any] | None:
        try:
            return {
                "market_id": mid,
                "question": uni.question,
                "description": uni.description,
                "resolution_source": uni.resolution_rules,
                "outcomes": ["Yes", "No"],
                "evidence": [],
                "package_created_at": datetime.now(timezone.utc).isoformat(),
            }
        except Exception:
            return None

    # ── 6. Pipeline for each market ──
    for entry in entries:
        mid = entry.market_id
        uni = universe_by_id.get(mid)
        if not uni:
            _record(mid, "PIPELINE_FAILED", "universe record not found")
            continue

        # Package
        pkg = _build_pkg(mid, uni)
        if not pkg:
            _record(mid, "PIPELINE_FAILED", "package build failed")
            continue

        try:
            clean_pkg = validate_package(pkg)
        except Exception as e:
            _record(mid, "PIPELINE_FAILED", f"package validation: {e}")
            continue

        try:
            sm.record_market_initialized(experiment_id, mid, clean_pkg)
        except RuntimeError as e:
            _record(mid, "PIPELINE_FAILED", f"market init: {e}")
            continue

        # Persist package artifact
        pkg_path = experiments_root / experiment_id / "packages" / f"{mid}.json"
        pkg_path.parent.mkdir(parents=True, exist_ok=True)
        canon = clean_pkg.model_dump(mode="json")
        pkg_hash = hashlib.sha256(
            json.dumps(canon, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        pkg_art = PackageArtifact(package=clean_pkg, package_hash=pkg_hash, artifact_version=1,
                                  forecast_mode=ForecastMode.PRIMARY_MODEL.value,
                                  original_market_id=mid)
        pkg_path.write_text(pkg_art.model_dump_json(indent=2), encoding="utf-8")

        # ── Forecast (real model call) ──
        if model_provider is not None:
            runner = BlindForecastRunner(
                provider=model_provider,
                model_id=getattr(model_provider, "MODEL_ID", "unknown"),
                model_version=getattr(model_provider, "MODEL_VERSION", "0"),
                prompt_version=getattr(model_provider, "PROMPT_VERSION", "v1"),
                runner_version="1.0.0",
            )
            try:
                fc, provenance = runner.run(mid, pkg_art, ForecastMode.PRIMARY_MODEL)
            except Exception as e:
                _record(mid, "PIPELINE_FAILED", f"model call: {e}")
                continue

            # Write forecast artifact
            fc_dir = experiments_root / experiment_id / "forecasts" / mid
            fc_dir.mkdir(parents=True, exist_ok=True)
            fc_path = fc_dir / "v1.json"
            fc_path.write_text(fc.model_dump_json(indent=2), encoding="utf-8")
            # Provenance
            prov_dir = experiments_root / experiment_id / "forecast_provenance" / mid
            prov_dir.mkdir(parents=True, exist_ok=True)
            (prov_dir / "v1.json").write_text(json.dumps(provenance, indent=2), encoding="utf-8")

            _record(mid, "FORECASTED",
                    f"p_yes={fc.p_yes:.4f} model={provenance['model_id']}",
                    forecast_hash=provenance["parsed_forecast_hash"])
            forecast_ledger.append({
                "market_id": mid,
                "p_yes": fc.p_yes,
                "model_id": provenance["model_id"],
                "package_hash": provenance["package_hash"],
                "parsed_forecast_hash": provenance["parsed_forecast_hash"],
            })

            # ── Lock ──
            try:
                lock_obj = lock_forecast(
                    experiments_root=str(experiments_root),
                    experiment_id=experiment_id,
                    market_id=mid,
                    package=pkg_art.package.model_dump(mode="json"),
                    forecast=fc,
                    forecast_mode=fc.forecast_mode,
                )
            except Exception as e:
                _record(mid, "PIPELINE_FAILED", f"lock: {e}")
                continue

            lock_dir = experiments_root / experiment_id / "locks" / mid
            lock_dir.mkdir(parents=True, exist_ok=True)
            lock_path = lock_dir / "v1.json"
            lock_path.write_text(lock_obj.model_dump_json(indent=2), encoding="utf-8")
            sm.record_forecast_locked(experiment_id, mid, lock_obj)

            # ── Real baseline capture ──
            snap_provider = CLOBSnapshotProvider(token_ids=token_ids, output_dir=str(experiments_root))
            svc = PriceRevealService(
                state_mgr=sm,
                experiments_root=str(experiments_root),
                provider=snap_provider,
            )
            try:
                capture_start = datetime.now(timezone.utc)
                snapshot = svc.reveal(mid, experiment_id)
                capture_delay = (datetime.now(timezone.utc) - capture_start).total_seconds()
            except Exception as e:
                _record(mid, "PIPELINE_FAILED", f"baseline capture: {e}")
                continue

            mid_val = snapshot.mid if snapshot else None
            _record(mid, "BASELINE_CAPTURED",
                    f"mid={mid_val}, delay={capture_delay:.3f}s",
                    baseline_mid=mid_val)
            baseline_ledger.append({
                "market_id": mid,
                "mid": mid_val,
                "bid": snapshot.bid if snapshot else None,
                "ask": snapshot.ask if snapshot else None,
                "capture_delay_seconds": round(capture_delay, 3),
                "captured_at": capture_start.isoformat(),
            })

            # Unresolved status (no real resolution yet)
            _record(mid, "UNRESOLVED", "awaiting real resolution outcome")
        else:
            # No model configured — mark as PIPELINE_FAILED
            _record(mid, "PIPELINE_FAILED", "no model provider configured")

    # ── 7. Write pilot report ──
    summary = {}
    for e in ledger:
        s = e["status"]
        summary[s] = summary.get(s, 0) + 1

    result = {
        "status": "COMPLETED",
        "experiment_id": experiment_id,
        "started_at": started_at.isoformat(),
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "source": "polymarket_gamma",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "markets_fetched": len(raw_markets),
        "markets_imported": len(universe_records),
        "markets_selected": len(entries),
        "markets_forecasted": len(forecast_ledger),
        "markets_baseline": len(baseline_ledger),
        "ledger_summary": summary,
        "ledger": ledger,
        "forecast_ledger": forecast_ledger,
        "baseline_ledger": baseline_ledger,
    }

    report_path = out / "pilot_report.json"
    report_path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    return result
