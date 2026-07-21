from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from trade_flow.data import DailyBar, build_market_data_snapshot
from trade_flow.domain.config import load_config
from trade_flow.execution import PositionSnapshot
from trade_flow.monitoring import (
    EventDirection,
    EventSeverity,
    MarketEvent,
    RecommendationAction,
    build_daily_monitoring_report,
    build_weekly_discovery_report,
)
from trade_flow.risk import RegimeState


def _history(symbol: str, slope: str, volume: int) -> list[DailyBar]:
    start = date(2025, 1, 1)
    increment = Decimal(slope)
    bars: list[DailyBar] = []
    for index in range(201):
        close = Decimal(120) + increment * Decimal(index)
        bars.append(
            DailyBar(
                symbol=symbol,
                session_date=start + timedelta(days=index),
                open=close,
                high=close + Decimal(1),
                low=close - Decimal(1),
                close=close,
                split_adjusted_open=close,
                split_adjusted_high=close + Decimal(1),
                split_adjusted_low=close - Decimal(1),
                split_adjusted_close=close,
                volume=volume,
                cash_dividend=Decimal(0),
                source="fixture",
                fetched_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
    return bars


def _snapshot():
    bars = [
        *_history("A", "0.50", 6000),
        *_history("B", "0.40", 5000),
        *_history("C", "0.30", 4000),
        *_history("D", "0.20", 3000),
        *_history("E", "0.10", 2000),
        *_history("F", "0.05", 1000),
        *_history("WEAK", "-0.10", 1000),
    ]
    sessions = sorted({bar.session_date for bar in bars})
    return build_market_data_snapshot(
        bars,
        as_of=sessions[-1],
        expected_sessions=sessions,
        expected_symbols={bar.symbol for bar in bars},
    )


def _positions():
    return {
        "F": PositionSnapshot("F", 10, Decimal("120"), Decimal("130")),
        "WEAK": PositionSnapshot("WEAK", 10, Decimal("100"), Decimal("100")),
    }


def test_daily_report_reviews_holdings_and_only_recommends_qualified_candidates() -> None:
    snapshot = _snapshot()
    config = load_config("configs/strategy.toml")

    report = build_daily_monitoring_report(
        snapshot,
        config,
        positions=_positions(),
        main_symbols={"A", "B", "C", "D", "E", "F", "WEAK"},
    )

    reviews = {review.symbol: review for review in report.positions}
    assert reviews["WEAK"].action is RecommendationAction.REDUCE
    assert reviews["WEAK"].reasons == ("below_long_term_trend",)
    assert report.entry_candidates
    assert len(report.entry_candidates) <= config.monitoring.daily_candidate_limit
    assert all(
        candidate.strategy_score >= config.monitoring.minimum_entry_score
        for candidate in report.entry_candidates
    )
    assert report.execution_authorized is False


def test_critical_negative_event_marks_position_for_exit_review() -> None:
    snapshot = _snapshot()
    config = load_config("configs/strategy.toml")
    event = MarketEvent(
        event_id="company-critical",
        published_at=datetime(2025, 7, 20, tzinfo=UTC),
        headline="Critical company event",
        source="fixture",
        scope="company",
        direction=EventDirection.NEGATIVE,
        severity=EventSeverity.CRITICAL,
        confidence=Decimal("0.95"),
        summary="fixture",
        affected_symbols=("F",),
    )

    report = build_daily_monitoring_report(
        snapshot,
        config,
        positions=_positions(),
        main_symbols={"A", "B", "C", "D", "E", "F", "WEAK"},
        events=(event,),
    )

    review = next(item for item in report.positions if item.symbol == "F")
    assert review.action is RecommendationAction.EXIT
    assert review.event_ids == ("company-critical",)
    assert report.material_events == (event,)


def test_weekly_report_limits_candidates_and_requires_replacement_margin() -> None:
    snapshot = _snapshot()
    config = load_config("configs/strategy.toml")

    report = build_weekly_discovery_report(
        snapshot,
        config,
        positions=_positions(),
        main_symbols={"A", "B", "C", "D", "E", "F", "WEAK"},
    )

    assert 0 < len(report.candidates) <= config.monitoring.weekly_candidate_limit
    weak_comparison = next(
        comparison for comparison in report.comparisons if comparison.holding_symbol == "WEAK"
    )
    assert weak_comparison.recommended is True
    assert report.execution_authorized is False
    assert report.to_json() == report.to_json()


def test_weekly_report_never_recommends_entry_during_risk_regime() -> None:
    snapshot = _snapshot()
    config = load_config("configs/strategy.toml")
    regime = RegimeState(snapshot.as_of, True, True, 0, ("vix",))

    report = build_weekly_discovery_report(
        snapshot,
        config,
        positions=_positions(),
        main_symbols={"A", "B", "C", "D", "E", "F", "WEAK"},
        regime_state=regime,
    )

    assert all(candidate.action is RecommendationAction.WATCH for candidate in report.candidates)
    assert not any(comparison.recommended for comparison in report.comparisons)
    assert "risk_regime_active_new_entries_blocked" in report.alerts
