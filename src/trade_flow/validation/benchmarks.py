from __future__ import annotations

from datetime import date
from decimal import ROUND_FLOOR, Decimal
from types import MappingProxyType

from trade_flow.backtest import BacktestResult, EquityPoint, Position, SimulatedTrade
from trade_flow.data import MarketDataSnapshot


def cash_benchmark(snapshot: MarketDataSnapshot, initial_cash: Decimal) -> BacktestResult:
    sessions = sorted({bar.session_date for bar in snapshot.prices})
    curve = tuple(
        EquityPoint(session, initial_cash, initial_cash, Decimal(0)) for session in sessions
    )
    return BacktestResult(curve, (), MappingProxyType({}))


def buy_and_hold_benchmark(
    snapshot: MarketDataSnapshot,
    *,
    symbol: str,
    initial_cash: Decimal,
    transaction_cost_bps: int,
    start: date | None = None,
) -> BacktestResult:
    bars = sorted(
        (
            bar
            for bar in snapshot.prices
            if bar.symbol == symbol and (start is None or bar.session_date >= start)
        ),
        key=lambda bar: bar.session_date,
    )
    if len(bars) < 2:
        raise ValueError(f"benchmark {symbol} requires at least two bars")
    rate = Decimal(transaction_cost_bps) / Decimal(10000)
    per_share = bars[0].split_adjusted_open * (Decimal(1) + rate)
    quantity = int((initial_cash / per_share).to_integral_value(rounding=ROUND_FLOOR))
    entry_cost = Decimal(quantity) * bars[0].split_adjusted_open * rate
    cash = initial_cash - Decimal(quantity) * bars[0].split_adjusted_open - entry_cost
    curve: list[EquityPoint] = []
    for bar in bars:
        cash += Decimal(quantity) * bar.cash_dividend
        equity = Decimal(quantity) * bar.split_adjusted_close
        curve.append(EquityPoint(bar.session_date, cash + equity, cash, equity))
    trade = SimulatedTrade(
        signal_date=bars[0].session_date,
        execution_date=bars[0].session_date,
        symbol=symbol,
        side="buy",
        quantity=quantity,
        price=bars[0].split_adjusted_open,
        transaction_cost=entry_cost,
        realized_pnl=None,
    )
    return BacktestResult(
        tuple(curve),
        (trade,),
        MappingProxyType(
            {symbol: Position(quantity=quantity, average_cost=bars[0].split_adjusted_open)}
        ),
        evaluation_start_date=bars[0].session_date,
    )
