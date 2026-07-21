from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from math import sqrt
from statistics import fmean, stdev

from trade_flow.backtest import BacktestResult


@dataclass(frozen=True)
class PerformanceMetrics:
    total_return: float
    cagr: float
    maximum_drawdown: float
    sharpe: float
    calmar: float
    turnover: float
    sell_win_rate: float
    maximum_recovery_sessions: int
    trade_count: int


def _drawdown_and_recovery(values: list[Decimal]) -> tuple[float, int]:
    peak = values[0]
    peak_index = 0
    maximum_drawdown = Decimal(0)
    maximum_recovery = 0
    for index, value in enumerate(values):
        if value >= peak:
            maximum_recovery = max(maximum_recovery, index - peak_index)
            peak = value
            peak_index = index
        elif peak > 0:
            maximum_drawdown = min(maximum_drawdown, value / peak - Decimal(1))
            maximum_recovery = max(maximum_recovery, index - peak_index)
    return float(maximum_drawdown), maximum_recovery


def calculate_metrics(
    result: BacktestResult, *, start: date | None = None, end: date | None = None
) -> PerformanceMetrics:
    curve = result.equity_curve
    if result.evaluation_start_date is not None:
        curve = tuple(
            point for point in curve if point.session_date >= result.evaluation_start_date
        )
    if start is not None:
        curve = tuple(point for point in curve if point.session_date >= start)
    if end is not None:
        curve = tuple(point for point in curve if point.session_date <= end)
    if len(curve) < 2:
        raise ValueError("at least two equity points are required")
    values = [point.nav for point in curve]
    if any(value <= 0 for value in values):
        raise ValueError("NAV must remain positive")
    total_return = float(values[-1] / values[0] - Decimal(1))
    elapsed_days = (curve[-1].session_date - curve[0].session_date).days
    years = elapsed_days / 365.2425
    cagr = (float(values[-1] / values[0]) ** (1 / years) - 1) if years > 0 else 0.0
    returns = [
        float(current / previous - Decimal(1))
        for previous, current in zip(values, values[1:], strict=False)
    ]
    sharpe = 0.0
    if len(returns) >= 2 and stdev(returns) > 0:
        sharpe = sqrt(252) * fmean(returns) / stdev(returns)
    maximum_drawdown, maximum_recovery = _drawdown_and_recovery(values)
    calmar = cagr / abs(maximum_drawdown) if maximum_drawdown < 0 else 0.0
    average_nav = sum(values) / Decimal(len(values))
    period_trades = [
        trade
        for trade in result.trades
        if (start is None or trade.execution_date >= start)
        and (end is None or trade.execution_date <= end)
    ]
    traded_notional = sum(Decimal(trade.quantity) * trade.price for trade in period_trades)
    turnover = float(traded_notional / average_nav) if average_nav > 0 else 0.0
    sells = [trade for trade in period_trades if trade.side == "sell"]
    winning_sells = sum(
        trade.realized_pnl is not None and trade.realized_pnl > 0 for trade in sells
    )
    sell_win_rate = winning_sells / len(sells) if sells else 0.0
    return PerformanceMetrics(
        total_return=total_return,
        cagr=cagr,
        maximum_drawdown=maximum_drawdown,
        sharpe=sharpe,
        calmar=calmar,
        turnover=turnover,
        sell_win_rate=sell_win_rate,
        maximum_recovery_sessions=maximum_recovery,
        trade_count=len(period_trades),
    )
