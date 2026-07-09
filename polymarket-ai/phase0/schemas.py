from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any

from pydantic import BaseModel, Field, model_validator, ConfigDict
from pydantic.functional_validators import AfterValidator


def _ensure_tz(v: datetime) -> datetime:
    if v.tzinfo is None:
        raise ValueError(
            f"Datetime must be timezone-aware, got naive: {v.isoformat()}"
        )
    return v


TzAwareDt = Annotated[datetime, AfterValidator(_ensure_tz)]


class ForecastMode(str, Enum):
    CHEAP_BASELINE = "CHEAP_BASELINE"
    BETTER_BASELINE = "BETTER_BASELINE"
    FULL_RESEARCH = "FULL_RESEARCH"
    PRIMARY_MODEL = "PRIMARY_MODEL"


class ConfidenceLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    VERY_HIGH = "VERY_HIGH"


class ResolutionStatus(str, Enum):
    RESOLVED_VALID = "RESOLVED_VALID"
    RESOLUTION_DISPUTED = "RESOLUTION_DISPUTED"
    TEMPORALLY_INVALID = "TEMPORALLY_INVALID"
    MISSING_PROVENANCE = "MISSING_PROVENANCE"
    UNRESOLVED = "UNRESOLVED"


class ResolutionOutcome(str, Enum):
    YES = "YES"
    NO = "NO"

    def to_p_yes(self) -> float:
        return 1.0 if self == ResolutionOutcome.YES else 0.0


class ManifestMarketEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    market_id: str
    question: str = ""
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    horizon_days: int = 0
    rule_complexity: str = ""
    liquidity_bucket: str = ""

    @model_validator(mode="after")
    def _validate_market_id(self) -> ManifestMarketEntry:
        raw = self.market_id.strip()
        if not raw:
            raise ValueError("market_id must be non-empty after stripping whitespace")
        self.market_id = raw
        return self


class MarketManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    experiment_id: str
    created_at: TzAwareDt
    selection_cutoff: TzAwareDt
    selection_rule_version: str = "v1"
    sampling_strategy: str = "stratified"
    markets: list[ManifestMarketEntry] = Field(default_factory=list)
    exclusion_rules: list[str] = Field(default_factory=list)
    manifest_hash: str = ""
    manifest_artifact_hash: str = ""

    @model_validator(mode="after")
    def _validate_unique_market_ids(self) -> MarketManifest:
        ids = [m.market_id for m in self.markets]
        if len(ids) != len(set(ids)):
            seen: set[str] = set()
            dupes: list[str] = []
            for mid in ids:
                if mid in seen:
                    dupes.append(mid)
                seen.add(mid)
            raise ValueError(f"Duplicate market_id(s) in manifest: {dupes}")
        return self


class CleanForecastPackage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    market_id: str
    question: str
    description: str
    resolution_source: str
    resolution_sources: list[dict[str, Any]] = Field(default_factory=list)
    outcomes: list[str]
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    references: list[dict[str, Any]] = Field(default_factory=list)
    package_created_at: TzAwareDt


class PackageArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    package: CleanForecastPackage
    package_hash: str = ""
    artifact_version: int = 1
    forecast_mode: str = "CHEAP_BASELINE"
    original_market_id: str = ""


class MarketUniverseRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    market_id: str
    question: str
    description: str = ""
    resolution_rules: str = ""
    close_time: TzAwareDt | None = None
    category: str = ""
    subcategory: str = ""
    source: str = ""
    retrieved_at: TzAwareDt = Field(default_factory=lambda: datetime.now(timezone.utc))
    raw_artifact_hash: str = ""
    parser_version: str = ""
    normalized_artifact_hash: str = ""
    tags: list[str] = Field(default_factory=list)
    enable_order_book: bool = False
    clob_token_ids: list[str] = Field(default_factory=list)
    outcomes: list[str] = Field(default_factory=list)
    accepting_orders: bool = False
    yes_token_id: str = ""


class ForecastLock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    forecast_id: str
    market_id: str
    forecast_version: int = 1
    forecast_cutoff: TzAwareDt
    package_hash: str
    forecast_mode: ForecastMode
    raw_probability: float = Field(ge=0.0, le=1.0)
    locked_at: TzAwareDt
    forecast_hash: str
    forecast_artifact_hash: str = ""


class Forecast(BaseModel):
    model_config = ConfigDict(extra="forbid")

    market_id: str
    forecast_cutoff: TzAwareDt
    forecast_mode: ForecastMode
    p_yes: float = Field(ge=0.0, le=1.0)
    interval_50: list[float] = Field(min_length=2, max_length=2)
    interval_80: list[float] = Field(min_length=2, max_length=2)
    top_drivers: list[str] = Field(default_factory=list)
    counterarguments: list[str] = Field(default_factory=list)
    critical_unknowns: list[str] = Field(default_factory=list)
    rules_confidence: ConfidenceLevel = ConfidenceLevel.MEDIUM
    research_cost_usd: float | None = None
    latency_seconds: float = 0.0

    @model_validator(mode="after")
    def validate_intervals(self) -> Forecast:
        lo80, hi80 = self.interval_80
        lo50, hi50 = self.interval_50
        if not (0.0 <= lo80 <= lo50 <= self.p_yes <= hi50 <= hi80 <= 1.0):
            raise ValueError(
                f"Interval ordering violated: 0 <= lo80({lo80}) <= lo50({lo50}) "
                f"<= p_yes({self.p_yes}) <= hi50({hi50}) <= hi80({hi80}) <= 1"
            )
        return self


class PriceSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    market_id: str
    snapshot_timestamp: TzAwareDt = Field(default_factory=lambda: datetime.now(timezone.utc))
    snapshot_id: str = ""
    bid: float | None = Field(None, ge=0.0, le=1.0)
    ask: float | None = Field(None, ge=0.0, le=1.0)
    mid: float | None = Field(None, ge=0.0, le=1.0)
    spread: float | None = Field(None, ge=0.0)
    volume: float | None = Field(None, ge=0.0)
    price_history_url: str | None = None


class Resolution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    market_id: str
    resolved_at: TzAwareDt
    outcome: ResolutionOutcome
    resolution_status: ResolutionStatus = ResolutionStatus.RESOLVED_VALID
    resolution_source: str = ""
    source_retrieved_at: TzAwareDt | None = None
    source_published_at: TzAwareDt | None = None
    resolution_recorded_at: TzAwareDt = Field(default_factory=lambda: datetime.now(timezone.utc))
    resolver_version: str = "v1"
    evidence_artifact_hash: str = ""
    resolution_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    manual_intervention: bool = False

    @property
    def p_yes_actual(self) -> float:
        return self.outcome.to_p_yes()


class EvalResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    market_id: str
    ai_brier: float
    market_brier: float | None = None
    delta_brier: float | None = None
    ai_log_loss: float
    market_log_loss: float | None = None
    delta_log_loss: float | None = None


class EvaluationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    experiment_id: str
    evaluated_at: TzAwareDt
    results: list[EvalResult] = Field(default_factory=list)
    pending_markets: list[str] = Field(default_factory=list)
    forecast_count: int = 0
    resolved_count: int = 0
    evaluated_count: int = 0
    unresolved_count: int = 0
    mean_ai_brier: float = 0.0
    mean_market_brier: float | None = None
    mean_delta_brier: float | None = None
    mean_ai_log_loss: float = 0.0
    mean_market_log_loss: float | None = None
    mean_delta_log_loss: float | None = None
    extreme_error_count: int = 0

    def has_evaluable_cases(self) -> bool:
        return self.evaluated_count > 0
