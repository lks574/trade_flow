from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_FLOOR, Decimal
from types import MappingProxyType

from trade_flow.data import DailyBar, MarketDataSnapshot, build_market_data_snapshot
from trade_flow.domain.config import AppConfig
from trade_flow.risk import RegimePolicy, RegimeState, adjust_weights_for_regime
from trade_flow.strategy import signal


@dataclass(frozen=True)
class Position:
    quantity: int
    average_cost: Decimal


@dataclass(frozen=True)
class SimulatedTrade:
    signal_date: date
    execution_date: date
    symbol: str
    side: str
    quantity: int
    price: Decimal
    transaction_cost: Decimal
    realized_pnl: Decimal | None


@dataclass(frozen=True)
class EquityPoint:
    session_date: date
    nav: Decimal
    cash: Decimal
    equity: Decimal


@dataclass(frozen=True)
class BacktestResult:
    equity_curve: tuple[EquityPoint, ...]
    trades: tuple[SimulatedTrade, ...]
    final_positions: Mapping[str, Position]
    evaluation_start_date: date | None = None


def _position_weights(
    positions: Mapping[str, Position], prices: Mapping[str, Decimal], nav: Decimal
) -> dict[str, Decimal]:
    if nav <= 0:
        return {}
    return {
        symbol: Decimal(position.quantity) * prices[symbol] / nav
        for symbol, position in positions.items()
        if symbol in prices and position.quantity > 0
    }


def _execute_targets(
    *,
    signal_date: date,
    execution_date: date,
    target_weights: Mapping[str, Decimal],
    open_prices: Mapping[str, Decimal],
    cash: Decimal,
    positions: dict[str, Position],
    cost_rate: Decimal,
) -> tuple[Decimal, list[SimulatedTrade]]:
    nav = cash + sum(
        Decimal(position.quantity) * open_prices.get(symbol, position.average_cost)
        for symbol, position in positions.items()
    )
    symbols = set(positions) | set(target_weights)
    desired = {
        symbol: int(
            (nav * target_weights.get(symbol, Decimal(0)) / open_prices[symbol]).to_integral_value(
                rounding=ROUND_FLOOR
            )
        )
        for symbol in symbols
        if symbol in open_prices
    }
    trades: list[SimulatedTrade] = []
    for symbol in sorted(symbols):
        current = positions.get(symbol, Position(0, Decimal(0))).quantity
        target = desired.get(symbol, current)
        quantity = current - target
        if quantity <= 0 or symbol not in open_prices:
            continue
        price = open_prices[symbol]
        cost = Decimal(quantity) * price * cost_rate
        cash += Decimal(quantity) * price - cost
        average_cost = positions[symbol].average_cost
        if target == 0:
            positions.pop(symbol, None)
        else:
            positions[symbol] = Position(target, positions[symbol].average_cost)
        trades.append(
            SimulatedTrade(
                signal_date,
                execution_date,
                symbol,
                "sell",
                quantity,
                price,
                cost,
                Decimal(quantity) * (price - average_cost) - cost,
            )
        )

    for symbol in sorted(symbols):
        current_position = positions.get(symbol, Position(0, Decimal(0)))
        target = desired.get(symbol, current_position.quantity)
        requested = target - current_position.quantity
        if requested <= 0 or symbol not in open_prices:
            continue
        price = open_prices[symbol]
        per_share = price * (Decimal(1) + cost_rate)
        affordable = int((cash / per_share).to_integral_value(rounding=ROUND_FLOOR))
        quantity = min(requested, affordable)
        if quantity <= 0:
            continue
        cost = Decimal(quantity) * price * cost_rate
        cash -= Decimal(quantity) * price + cost
        total_quantity = current_position.quantity + quantity
        average_cost = (
            Decimal(current_position.quantity) * current_position.average_cost
            + Decimal(quantity) * price
        ) / Decimal(total_quantity)
        positions[symbol] = Position(total_quantity, average_cost)
        trades.append(
            SimulatedTrade(
                signal_date,
                execution_date,
                symbol,
                "buy",
                quantity,
                price,
                cost,
                None,
            )
        )
    return cash, trades


def run_backtest(
    snapshot: MarketDataSnapshot,
    config: AppConfig,
    *,
    main_symbols: Iterable[str],
    high_volatility_symbols: Iterable[str] = (),
    initial_cash: Decimal = Decimal("20000000"),
    transaction_cost_bps: int = 15,
    regime_states: Mapping[date, RegimeState] | None = None,
    regime_policy: RegimePolicy = RegimePolicy.BUY_BLOCK,
) -> BacktestResult:
    snapshot.quality_report.require_valid()
    if initial_cash <= 0 or transaction_cost_bps < 0:
        raise ValueError("initial cash must be positive and transaction cost cannot be negative")
    main_set = set(main_symbols)
    high_set = set(high_volatility_symbols)
    expected_symbols = main_set | high_set
    bars_by_date: dict[date, dict[str, DailyBar]] = defaultdict(dict)
    history: list[DailyBar] = []
    for bar in snapshot.prices:
        bars_by_date[bar.session_date][bar.symbol] = bar
    sessions = sorted(bars_by_date)
    positions: dict[str, Position] = {}
    cash = initial_cash
    pending: tuple[date, Mapping[str, Decimal]] | None = None
    trades: list[SimulatedTrade] = []
    curve: list[EquityPoint] = []
    previous_nav = initial_cash
    cost_rate = Decimal(transaction_cost_bps) / Decimal(10000)

    for session_index, session_date in enumerate(sessions):
        today = bars_by_date[session_date]
        for symbol, position in positions.items():
            bar = today.get(symbol)
            if bar is not None:
                cash += Decimal(position.quantity) * bar.cash_dividend

        if pending is not None:
            signal_date, target_weights = pending
            open_prices = {symbol: bar.split_adjusted_open for symbol, bar in today.items()}
            cash, executed = _execute_targets(
                signal_date=signal_date,
                execution_date=session_date,
                target_weights=target_weights,
                open_prices=open_prices,
                cash=cash,
                positions=positions,
                cost_rate=cost_rate,
            )
            trades.extend(executed)
            pending = None

        close_prices = {symbol: bar.split_adjusted_close for symbol, bar in today.items()}
        equity = sum(
            Decimal(position.quantity) * close_prices.get(symbol, position.average_cost)
            for symbol, position in positions.items()
        )
        nav = cash + equity
        curve.append(EquityPoint(session_date, nav, cash, equity))
        history.extend(today.values())

        if session_index + 1 < config.strategy.minimum_price_days:
            previous_nav = nav
            continue
        sliced = build_market_data_snapshot(
            history,
            as_of=session_date,
            expected_sessions=sessions[: session_index + 1],
            expected_symbols=expected_symbols,
        )
        strategy_result = signal(
            sliced,
            config.strategy,
            main_symbols=main_set,
            high_volatility_symbols=high_set,
        )
        target_weights = dict(strategy_result.target_weights)
        for symbol, position in positions.items():
            close = close_prices.get(symbol)
            if close is not None and close <= position.average_cost * (
                Decimal(1) - config.risk.stop_loss_fraction
            ):
                target_weights[symbol] = Decimal(0)

        state = (regime_states or {}).get(
            session_date,
            RegimeState(session_date, False, True, 0, ()),
        )
        current_weights = _position_weights(positions, close_prices, nav)
        target_weights = dict(
            adjust_weights_for_regime(
                target_weights,
                current_weights,
                state,
                regime_policy,
                config.risk,
            )
        )
        daily_loss_triggered = (
            previous_nav > 0
            and nav / previous_nav - Decimal(1) <= -config.risk.daily_loss_limit_fraction
        )
        if daily_loss_triggered:
            target_weights = {
                symbol: min(weight, current_weights.get(symbol, Decimal(0)))
                for symbol, weight in target_weights.items()
            }
        pending = (session_date, MappingProxyType(dict(sorted(target_weights.items()))))
        previous_nav = nav

    return BacktestResult(
        equity_curve=tuple(curve),
        trades=tuple(trades),
        final_positions=MappingProxyType(dict(sorted(positions.items()))),
        evaluation_start_date=(
            sessions[config.strategy.minimum_price_days]
            if len(sessions) > config.strategy.minimum_price_days
            else None
        ),
    )
