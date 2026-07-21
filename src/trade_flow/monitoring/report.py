from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from trade_flow.data import DailyBar, MarketDataSnapshot
from trade_flow.domain.config import AppConfig
from trade_flow.execution import PositionSnapshot
from trade_flow.monitoring.models import (
    CandidateReview,
    DailyMonitoringReport,
    EventDirection,
    EventSeverity,
    MarketEvent,
    PositionReview,
    RecommendationAction,
    ReplacementComparison,
    WeeklyDiscoveryReport,
)
from trade_flow.risk import RegimeState
from trade_flow.strategy import FactorScore, StrategyResult, signal

_SEVERITY_ORDER = {
    EventSeverity.LOW: 0,
    EventSeverity.MEDIUM: 1,
    EventSeverity.HIGH: 2,
    EventSeverity.CRITICAL: 3,
}
_NEW_YORK = ZoneInfo("America/New_York")


def _bars_by_symbol(snapshot: MarketDataSnapshot) -> Mapping[str, tuple[DailyBar, ...]]:
    grouped: dict[str, list[DailyBar]] = defaultdict(list)
    for bar in snapshot.prices:
        grouped[bar.symbol].append(bar)
    return {
        symbol: tuple(sorted(bars, key=lambda item: item.session_date))
        for symbol, bars in grouped.items()
    }


def _period_return(bars: Sequence[DailyBar], sessions: int) -> Decimal | None:
    if len(bars) <= sessions:
        return None
    return bars[-1].split_adjusted_close / bars[-(sessions + 1)].split_adjusted_close - Decimal(1)


def _volume_ratio(bars: Sequence[DailyBar], sessions: int = 20) -> Decimal | None:
    if len(bars) <= sessions:
        return None
    history = bars[-(sessions + 1) : -1]
    average = Decimal(sum(bar.volume for bar in history)) / Decimal(len(history))
    return Decimal(bars[-1].volume) / average if average > 0 else None


def _ranked_scores(result: StrategyResult) -> tuple[tuple[str, FactorScore], ...]:
    return tuple(
        sorted(
            result.scores.items(),
            key=lambda item: (
                -item[1].total,
                -item[1].momentum_return,
                -item[1].average_dollar_volume,
                item[0],
            ),
        )
    )


def _material_events(events: Iterable[MarketEvent], config: AppConfig) -> tuple[MarketEvent, ...]:
    return tuple(
        sorted(
            (
                event
                for event in events
                if _SEVERITY_ORDER[event.severity] >= _SEVERITY_ORDER[EventSeverity.HIGH]
                and event.confidence >= config.monitoring.material_event_confidence
            ),
            key=lambda event: (
                -_SEVERITY_ORDER[event.severity],
                event.published_at,
                event.event_id,
            ),
        )
    )


def _recent_events(
    events: Sequence[MarketEvent], *, snapshot: MarketDataSnapshot, lookback_days: int
) -> tuple[MarketEvent, ...]:
    first_date = snapshot.as_of - timedelta(days=lookback_days)
    return tuple(
        event
        for event in events
        if first_date <= event.published_at.astimezone(_NEW_YORK).date() <= snapshot.as_of
    )


def _position_action(
    position: PositionSnapshot,
    bars: Sequence[DailyBar],
    *,
    result: StrategyResult,
    rank: int | None,
    relevant_events: Sequence[MarketEvent],
    eligible: bool,
    regime_state: RegimeState | None,
    config: AppConfig,
) -> tuple[RecommendationAction, tuple[str, ...]]:
    if not bars or bars[-1].session_date != result.as_of:
        return RecommendationAction.BLOCKED, ("missing_latest_price",)

    close = bars[-1].split_adjusted_close
    reasons: list[str] = []
    stop_price = position.average_price * (Decimal(1) - config.risk.stop_loss_fraction)
    if position.quantity > 0 and position.average_price > 0 and close <= stop_price:
        reasons.append("hard_stop_reached")
        return RecommendationAction.EXIT, tuple(reasons)

    critical_negative = any(
        event.direction is EventDirection.NEGATIVE
        and event.severity is EventSeverity.CRITICAL
        and event.confidence >= config.monitoring.material_event_confidence
        for event in relevant_events
    )
    if critical_negative:
        reasons.append("critical_negative_event_requires_exit_review")
        return RecommendationAction.EXIT, tuple(reasons)

    high_negative = any(
        event.direction is EventDirection.NEGATIVE
        and event.severity is EventSeverity.HIGH
        and event.confidence >= config.monitoring.material_event_confidence
        for event in relevant_events
    )
    if high_negative:
        reasons.append("high_impact_negative_event")
        return RecommendationAction.REDUCE, tuple(reasons)

    if not eligible:
        return RecommendationAction.REDUCE, ("outside_active_universe",)

    exclusion = result.exclusions.get(position.symbol)
    if exclusion == "insufficient_history":
        return RecommendationAction.BLOCKED, ("insufficient_price_history",)
    if exclusion == "below_sma_long":
        return RecommendationAction.REDUCE, ("below_long_term_trend",)

    one_day = _period_return(bars, 1)
    volume_ratio = _volume_ratio(bars)
    if (
        one_day is not None
        and one_day <= -config.monitoring.large_move_fraction
        and volume_ratio is not None
        and volume_ratio >= config.monitoring.volume_spike_multiple
    ):
        reasons.append("large_down_move_with_volume_spike")

    if regime_state is not None and regime_state.active:
        reasons.append("risk_regime_active")
    if rank is not None and rank > config.monitoring.hold_rank_limit:
        reasons.append("outside_hold_rank")
    if reasons:
        return RecommendationAction.WATCH, tuple(reasons)
    return RecommendationAction.HOLD, ("holding_conditions_intact",)


def _position_reviews(
    snapshot: MarketDataSnapshot,
    positions: Mapping[str, PositionSnapshot],
    *,
    result: StrategyResult,
    ranks: Mapping[str, int],
    events: Sequence[MarketEvent],
    eligible_symbols: set[str],
    regime_state: RegimeState | None,
    config: AppConfig,
) -> tuple[PositionReview, ...]:
    grouped = _bars_by_symbol(snapshot)
    reviews: list[PositionReview] = []
    for symbol, position in sorted(positions.items()):
        bars = grouped.get(symbol, ())
        relevant = tuple(event for event in events if event.applies_to(symbol))
        action, reasons = _position_action(
            position,
            bars,
            result=result,
            rank=ranks.get(symbol),
            relevant_events=relevant,
            eligible=symbol in eligible_symbols,
            regime_state=regime_state,
            config=config,
        )
        close = bars[-1].split_adjusted_close if bars else None
        unrealized_return = (
            close / position.average_price - Decimal(1)
            if close is not None and position.average_price > 0
            else None
        )
        reviews.append(
            PositionReview(
                symbol=symbol,
                action=action,
                latest_close=close,
                unrealized_return=unrealized_return,
                one_day_return=_period_return(bars, 1),
                five_day_return=_period_return(bars, 5),
                twenty_day_return=_period_return(bars, 20),
                volume_ratio=_volume_ratio(bars),
                strategy_score=(result.scores[symbol].total if symbol in result.scores else None),
                strategy_rank=ranks.get(symbol),
                reasons=reasons,
                event_ids=tuple(event.event_id for event in relevant),
            )
        )
    return tuple(reviews)


def _candidate_reviews(
    result: StrategyResult,
    *,
    ranks: Mapping[str, int],
    held_symbols: set[str],
    events: Sequence[MarketEvent],
    config: AppConfig,
    limit: int,
    require_target_weight: bool,
    action: RecommendationAction = RecommendationAction.ADD,
) -> tuple[CandidateReview, ...]:
    output: list[CandidateReview] = []
    for symbol, score in _ranked_scores(result):
        if symbol in held_symbols or score.total < config.monitoring.minimum_entry_score:
            continue
        if require_target_weight and symbol not in result.target_weights:
            continue
        relevant = tuple(event for event in events if event.applies_to(symbol))
        has_material_negative = any(
            event.direction is EventDirection.NEGATIVE
            and _SEVERITY_ORDER[event.severity] >= _SEVERITY_ORDER[EventSeverity.HIGH]
            and event.confidence >= config.monitoring.material_event_confidence
            for event in relevant
        )
        if has_material_negative:
            continue
        output.append(
            CandidateReview(
                symbol=symbol,
                action=action,
                strategy_score=score.total,
                strategy_rank=ranks[symbol],
                momentum_return=score.momentum_return,
                average_dollar_volume=score.average_dollar_volume,
                reasons=("entry_score_passed", "no_material_negative_event"),
                event_ids=tuple(event.event_id for event in relevant),
            )
        )
        if len(output) >= limit:
            break
    return tuple(output)


def _strategy_and_ranks(
    snapshot: MarketDataSnapshot,
    config: AppConfig,
    *,
    main_symbols: Iterable[str],
    high_volatility_symbols: Iterable[str],
) -> tuple[StrategyResult, Mapping[str, int]]:
    result = signal(
        snapshot,
        config.strategy,
        main_symbols=main_symbols,
        high_volatility_symbols=high_volatility_symbols,
    )
    return result, {
        symbol: index for index, (symbol, _) in enumerate(_ranked_scores(result), start=1)
    }


def build_daily_monitoring_report(
    snapshot: MarketDataSnapshot,
    config: AppConfig,
    *,
    positions: Mapping[str, PositionSnapshot],
    main_symbols: Iterable[str],
    high_volatility_symbols: Iterable[str] = (),
    events: Sequence[MarketEvent] = (),
    regime_state: RegimeState | None = None,
) -> DailyMonitoringReport:
    snapshot.quality_report.require_valid()
    main_symbols = tuple(main_symbols)
    high_volatility_symbols = tuple(high_volatility_symbols)
    events = _recent_events(
        events,
        snapshot=snapshot,
        lookback_days=config.monitoring.daily_event_lookback_days,
    )
    result, ranks = _strategy_and_ranks(
        snapshot,
        config,
        main_symbols=main_symbols,
        high_volatility_symbols=high_volatility_symbols,
    )
    material = _material_events(events, config)
    reviews = _position_reviews(
        snapshot,
        positions,
        result=result,
        ranks=ranks,
        events=events,
        eligible_symbols=set(main_symbols) | set(high_volatility_symbols),
        regime_state=regime_state,
        config=config,
    )
    alerts: list[str] = []
    if regime_state is not None and regime_state.active:
        alerts.append("risk_regime_active_new_entries_blocked")
    if any(review.action is RecommendationAction.BLOCKED for review in reviews):
        alerts.append("position_review_blocked_by_data")
    candidates = ()
    if regime_state is None or not regime_state.active:
        candidates = _candidate_reviews(
            result,
            ranks=ranks,
            held_symbols=set(positions),
            events=events,
            config=config,
            limit=config.monitoring.daily_candidate_limit,
            require_target_weight=True,
        )
    if not candidates:
        alerts.append("no_daily_entry_candidate")
    return DailyMonitoringReport(
        as_of=snapshot.as_of,
        data_hash=snapshot.data_hash,
        config_hash=config.config_hash,
        positions=reviews,
        entry_candidates=candidates,
        material_events=material,
        alerts=tuple(alerts),
    )


def build_weekly_discovery_report(
    snapshot: MarketDataSnapshot,
    config: AppConfig,
    *,
    positions: Mapping[str, PositionSnapshot],
    main_symbols: Iterable[str],
    high_volatility_symbols: Iterable[str] = (),
    events: Sequence[MarketEvent] = (),
    regime_state: RegimeState | None = None,
) -> WeeklyDiscoveryReport:
    snapshot.quality_report.require_valid()
    main_symbols = tuple(main_symbols)
    high_volatility_symbols = tuple(high_volatility_symbols)
    events = _recent_events(
        events,
        snapshot=snapshot,
        lookback_days=config.monitoring.weekly_event_lookback_days,
    )
    result, ranks = _strategy_and_ranks(
        snapshot,
        config,
        main_symbols=main_symbols,
        high_volatility_symbols=high_volatility_symbols,
    )
    reviews = _position_reviews(
        snapshot,
        positions,
        result=result,
        ranks=ranks,
        events=events,
        eligible_symbols=set(main_symbols) | set(high_volatility_symbols),
        regime_state=regime_state,
        config=config,
    )
    candidates = _candidate_reviews(
        result,
        ranks=ranks,
        held_symbols=set(positions),
        events=events,
        config=config,
        limit=config.monitoring.weekly_candidate_limit,
        require_target_weight=False,
        action=(
            RecommendationAction.WATCH
            if regime_state is not None and regime_state.active
            else RecommendationAction.ADD
        ),
    )
    weakest = sorted(
        reviews,
        key=lambda review: (
            review.action not in {RecommendationAction.EXIT, RecommendationAction.REDUCE},
            -(review.strategy_rank or 10**9),
            review.strategy_score if review.strategy_score is not None else Decimal(-1),
            review.symbol,
        ),
    )
    comparisons: list[ReplacementComparison] = []
    for candidate, holding in zip(candidates, weakest, strict=False):
        advantage = (
            candidate.strategy_score - holding.strategy_score
            if holding.strategy_score is not None
            else None
        )
        holding_is_weak = holding.action in {
            RecommendationAction.EXIT,
            RecommendationAction.REDUCE,
        } or (
            holding.strategy_rank is not None
            and holding.strategy_rank > config.monitoring.hold_rank_limit
        )
        margin_passed = advantage is None or advantage >= config.monitoring.replacement_score_margin
        regime_allows_entry = regime_state is None or not regime_state.active
        recommended = holding_is_weak and margin_passed and regime_allows_entry
        reasons = ["candidate_entry_score_passed"]
        reasons.append(
            "holding_requires_replacement_review" if holding_is_weak else "holding_qualified"
        )
        reasons.append("score_margin_passed" if margin_passed else "score_margin_not_met")
        if not regime_allows_entry:
            reasons.append("risk_regime_blocks_entry")
        comparisons.append(
            ReplacementComparison(
                candidate_symbol=candidate.symbol,
                holding_symbol=holding.symbol,
                candidate_score=candidate.strategy_score,
                holding_score=holding.strategy_score,
                score_advantage=advantage,
                recommended=recommended,
                reasons=tuple(reasons),
            )
        )
    alerts: list[str] = []
    if regime_state is not None and regime_state.active:
        alerts.append("risk_regime_active_new_entries_blocked")
    if not candidates:
        alerts.append("no_weekly_candidate_passed")
    if positions and candidates and not any(item.recommended for item in comparisons):
        alerts.append("no_replacement_justified")
    return WeeklyDiscoveryReport(
        as_of=snapshot.as_of,
        data_hash=snapshot.data_hash,
        config_hash=config.config_hash,
        holdings=reviews,
        candidates=candidates,
        comparisons=tuple(comparisons),
        material_events=_material_events(events, config),
        alerts=tuple(alerts),
    )
