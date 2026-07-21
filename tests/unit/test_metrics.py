from datetime import date, timedelta
from decimal import Decimal
from types import MappingProxyType

from trade_flow.backtest import BacktestResult, EquityPoint, SimulatedTrade
from trade_flow.validation import calculate_metrics


def test_metrics_include_drawdown_recovery_turnover_and_win_rate() -> None:
    start = date(2020, 1, 1)
    values = [Decimal("100"), Decimal("120"), Decimal("90"), Decimal("125")]
    curve = tuple(
        EquityPoint(start + timedelta(days=index * 365), value, value, Decimal(0))
        for index, value in enumerate(values)
    )
    trades = (
        SimulatedTrade(start, start, "A", "buy", 1, Decimal("100"), Decimal(0), None),
        SimulatedTrade(
            start,
            start,
            "A",
            "sell",
            1,
            Decimal("120"),
            Decimal(0),
            Decimal("20"),
        ),
    )
    result = BacktestResult(curve, trades, MappingProxyType({}))

    metrics = calculate_metrics(result)

    assert metrics.total_return == 0.25
    assert metrics.maximum_drawdown == -0.25
    assert metrics.maximum_recovery_sessions == 2
    assert metrics.sell_win_rate == 1.0
    assert metrics.trade_count == 2
    assert metrics.turnover > 0

    later = calculate_metrics(result, start=start + timedelta(days=365))
    assert later.trade_count == 0
    assert later.total_return > 0
