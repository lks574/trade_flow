from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from trade_flow.data import DailyBar, build_market_data_snapshot
from trade_flow.validation import buy_and_hold_benchmark, calculate_metrics, cash_benchmark


def _snapshot():
    bars = []
    for index, close in enumerate((Decimal("100"), Decimal("110"), Decimal("120"))):
        session = date(2026, 1, 1) + timedelta(days=index)
        bars.append(
            DailyBar(
                symbol="SPY",
                session_date=session,
                open=close,
                high=close,
                low=close,
                close=close,
                split_adjusted_open=close,
                split_adjusted_high=close,
                split_adjusted_low=close,
                split_adjusted_close=close,
                volume=100,
                cash_dividend=Decimal(0),
                source="fixture",
                fetched_at=datetime(2026, 1, 4, tzinfo=UTC),
            )
        )
    sessions = [bar.session_date for bar in bars]
    return build_market_data_snapshot(
        bars,
        as_of=sessions[-1],
        expected_sessions=sessions,
        expected_symbols=["SPY"],
        recent_session_count=3,
    )


def test_spy_and_cash_benchmarks() -> None:
    snapshot = _snapshot()
    spy = buy_and_hold_benchmark(
        snapshot,
        symbol="SPY",
        initial_cash=Decimal("1000"),
        transaction_cost_bps=0,
    )
    cash = cash_benchmark(snapshot, Decimal("1000"))

    assert calculate_metrics(spy).total_return > 0
    assert calculate_metrics(cash).total_return == 0
