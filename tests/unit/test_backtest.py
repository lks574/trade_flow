from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from trade_flow.backtest import run_backtest
from trade_flow.data import DailyBar, build_market_data_snapshot
from trade_flow.domain.config import load_config


def _snapshot():
    start = date(2025, 1, 1)
    bars = []
    for index in range(202):
        session = start + timedelta(days=index)
        close = Decimal(100) + Decimal(index) / Decimal(10)
        open_price = Decimal(150) if index == 201 else close
        bars.append(
            DailyBar(
                symbol="A",
                session_date=session,
                open=open_price,
                high=max(open_price, close) + Decimal(1),
                low=min(open_price, close) - Decimal(1),
                close=close,
                split_adjusted_open=open_price,
                split_adjusted_high=max(open_price, close) + Decimal(1),
                split_adjusted_low=min(open_price, close) - Decimal(1),
                split_adjusted_close=close,
                volume=1000,
                cash_dividend=Decimal(0),
                source="fixture",
                fetched_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
    sessions = [bar.session_date for bar in bars]
    return build_market_data_snapshot(
        bars,
        as_of=sessions[-1],
        expected_sessions=sessions,
        expected_symbols=["A"],
    )


def test_backtest_executes_close_signal_at_next_open_with_costs() -> None:
    config = load_config("configs/strategy.toml")

    result = run_backtest(
        _snapshot(),
        config,
        main_symbols=["A"],
        initial_cash=Decimal("20000000"),
        transaction_cost_bps=15,
    )

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.signal_date < trade.execution_date
    assert trade.price == Decimal(150)
    assert trade.side == "buy"
    assert trade.transaction_cost > 0
    assert result.equity_curve[-1].cash >= 0
