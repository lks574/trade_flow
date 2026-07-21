from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum


class RecommendationAction(StrEnum):
    HOLD = "hold"
    ADD = "add"
    WATCH = "watch"
    REDUCE = "reduce"
    EXIT = "exit"
    BLOCKED = "blocked"


class EventDirection(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    MIXED = "mixed"
    NEUTRAL = "neutral"


class EventSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True)
class MarketEvent:
    event_id: str
    published_at: datetime
    headline: str
    source: str
    scope: str
    direction: EventDirection
    severity: EventSeverity
    confidence: Decimal
    summary: str
    affected_symbols: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.event_id or not self.headline or not self.source or not self.scope:
            raise ValueError("event id, headline, source, and scope are required")
        if self.scope not in {"company", "sector", "macro", "geopolitical", "global"}:
            raise ValueError("event scope is invalid")
        if self.published_at.tzinfo is None or self.published_at.utcoffset() is None:
            raise ValueError("event published_at must be timezone-aware")
        if not Decimal(0) <= self.confidence <= Decimal(1):
            raise ValueError("event confidence must be in [0, 1]")

    def applies_to(self, symbol: str) -> bool:
        return self.scope in {"macro", "geopolitical", "global"} or symbol in self.affected_symbols


@dataclass(frozen=True)
class PositionReview:
    symbol: str
    action: RecommendationAction
    latest_close: Decimal | None
    unrealized_return: Decimal | None
    one_day_return: Decimal | None
    five_day_return: Decimal | None
    twenty_day_return: Decimal | None
    volume_ratio: Decimal | None
    strategy_score: Decimal | None
    strategy_rank: int | None
    reasons: tuple[str, ...]
    event_ids: tuple[str, ...]


@dataclass(frozen=True)
class CandidateReview:
    symbol: str
    action: RecommendationAction
    strategy_score: Decimal
    strategy_rank: int
    momentum_return: Decimal
    average_dollar_volume: Decimal
    reasons: tuple[str, ...]
    event_ids: tuple[str, ...]


@dataclass(frozen=True)
class ReplacementComparison:
    candidate_symbol: str
    holding_symbol: str
    candidate_score: Decimal
    holding_score: Decimal | None
    score_advantage: Decimal | None
    recommended: bool
    reasons: tuple[str, ...]


def _json_default(value: object) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, StrEnum):
        return value.value
    raise TypeError(f"cannot serialize {type(value).__name__}")


@dataclass(frozen=True)
class DailyMonitoringReport:
    as_of: date
    data_hash: str
    config_hash: str
    positions: tuple[PositionReview, ...]
    entry_candidates: tuple[CandidateReview, ...]
    material_events: tuple[MarketEvent, ...]
    alerts: tuple[str, ...]
    execution_authorized: bool = False

    def to_json(self) -> str:
        return json.dumps(
            asdict(self),
            default=_json_default,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )


@dataclass(frozen=True)
class WeeklyDiscoveryReport:
    as_of: date
    data_hash: str
    config_hash: str
    holdings: tuple[PositionReview, ...]
    candidates: tuple[CandidateReview, ...]
    comparisons: tuple[ReplacementComparison, ...]
    material_events: tuple[MarketEvent, ...]
    alerts: tuple[str, ...]
    execution_authorized: bool = False

    def to_json(self) -> str:
        return json.dumps(
            asdict(self),
            default=_json_default,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
