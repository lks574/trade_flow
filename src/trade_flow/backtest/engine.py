from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import ROUND_FLOOR, Decimal
from types import MappingProxyType

from trade_flow.backtest.precompute import precompute_factor_series
from trade_flow.data import DailyBar, MarketDataSnapshot
from trade_flow.data.universe import UniverseSpec
from trade_flow.domain.config import AppConfig
from trade_flow.execution.models import AccountSnapshot, PositionSnapshot
from trade_flow.risk import RegimePolicy, RegimeState, apply_risk_policy
from trade_flow.strategy.signal import select_targets


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


def _active_symbols(symbols: Iterable[str] | UniverseSpec, session_date: date) -> set[str]:
    if isinstance(symbols, UniverseSpec):
        return {mapping.symbol for mapping in symbols.active_symbols(session_date)}
    return set(symbols)


def _execute_targets(
    *,
    signal_date: date,
    execution_date: date,
    target_weights: Mapping[str, Decimal],
    open_prices: Mapping[str, Decimal],
    cash: Decimal,
    positions: dict[str, Position],
    cost_rate: Decimal,
    rebalance_band: Decimal = Decimal(0),
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
    if rebalance_band > 0 and nav > 0:
        # 리서치 토글: 보유 중이고 여전히 선정된 종목의 비중 드리프트가 밴드 이내이면
        # 재조정을 생략(현재 수량 유지)한다. 신규 진입(현재 0)과 청산·손절(목표 0)은
        # 항상 실행한다. band=0(기본)이면 기존 동작과 동일하다.
        for symbol in list(desired):
            current_quantity = positions.get(symbol, Position(0, Decimal(0))).quantity
            target_weight = target_weights.get(symbol, Decimal(0))
            if current_quantity <= 0 or target_weight <= 0:
                continue
            current_weight = Decimal(current_quantity) * open_prices[symbol] / nav
            if abs(target_weight - current_weight) <= rebalance_band:
                desired[symbol] = current_quantity
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
    main_symbols: Iterable[str] | UniverseSpec,
    high_volatility_symbols: Iterable[str] | UniverseSpec = (),
    initial_cash: Decimal = Decimal("20000000"),
    transaction_cost_bps: int = 15,
    regime_states: Mapping[date, RegimeState] | None = None,
    regime_policy: RegimePolicy = RegimePolicy.BUY_BLOCK,
    rebalance_band: Decimal = Decimal(0),
    selection_hysteresis: int = 0,
) -> BacktestResult:
    snapshot.quality_report.require_valid()
    if initial_cash <= 0 or transaction_cost_bps < 0:
        raise ValueError("initial cash must be positive and transaction cost cannot be negative")
    bars_by_date: dict[date, dict[str, DailyBar]] = defaultdict(dict)
    for bar in snapshot.prices:
        bars_by_date[bar.session_date][bar.symbol] = bar
    sessions = sorted(bars_by_date)
    # 심볼별 팩터 시계열을 1회 사전계산한다(세션마다 전체 history 재계산 O(N^2) 회피).
    # factor_series[symbol][i] == signal._raw_factors(symbol의 i+1번째까지 바) (bit-identical).
    bars_by_symbol: dict[str, list[DailyBar]] = defaultdict(list)
    for session_date in sessions:
        for symbol, bar in bars_by_date[session_date].items():
            bars_by_symbol[symbol].append(bar)
    factor_series = {
        symbol: precompute_factor_series(bars, config.strategy)
        for symbol, bars in bars_by_symbol.items()
    }
    seen_count: dict[str, int] = defaultdict(int)
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
                rebalance_band=rebalance_band,
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
        for symbol in today:
            seen_count[symbol] += 1

        if session_index + 1 < config.strategy.minimum_price_days:
            previous_nav = nav
            continue
        main_set = _active_symbols(main_symbols, session_date)
        high_set = _active_symbols(high_volatility_symbols, session_date)
        high_volatility_set = high_set - main_set
        requested = main_set | high_volatility_set
        # signal()과 동일한 적격성 판정을 사전계산 시계열에서 조회한다. 세션별 스냅샷을
        # 다시 만들지 않으므로 signal의 sub-snapshot require_valid는 생략된다(최상위
        # 스냅샷이 이미 require_valid를 통과했으므로 유효 데이터에서는 결과 동일).
        raw: dict[str, tuple[Decimal, Decimal, Decimal, Decimal, Decimal]] = {}
        exclusions: dict[str, str] = {}
        for symbol in sorted(requested):
            count = seen_count.get(symbol, 0)
            if count < config.strategy.minimum_price_days:
                exclusions[symbol] = "insufficient_history"
                continue
            factors = factor_series[symbol][count - 1]
            if factors is None:
                exclusions[symbol] = "below_sma_long"
            else:
                raw[symbol] = factors
        strategy_result = select_targets(
            raw,
            exclusions,
            config.strategy,
            main_set=main_set,
            high_volatility_set=high_volatility_set,
            as_of=session_date,
            held_symbols=frozenset(
                symbol for symbol, position in positions.items() if position.quantity > 0
            ),
            selection_hysteresis=selection_hysteresis,
        )
        if regime_states is None:
            # ponytail: None = 레짐 오버레이 미요청(연구/메커니즘용). 오버레이를 요청한
            # 경우(dict) 세션 누락은 데이터 공백이므로 fail-closed로 신규 매수를 막는다.
            state = RegimeState(session_date, False, True, 0, ())
        else:
            state = regime_states.get(
                session_date,
                RegimeState(session_date, True, False, 0, ("regime_missing",)),
            )
        account = AccountSnapshot(
            account_hash="backtest",
            captured_at=datetime.combine(session_date, time.min, tzinfo=UTC),
            nav=nav,
            cash=cash,
            positions=MappingProxyType(
                {
                    symbol: PositionSnapshot(
                        symbol,
                        position.quantity,
                        position.average_cost,
                        close_prices[symbol],
                    )
                    for symbol, position in positions.items()
                    if symbol in close_prices
                }
            ),
        )
        daily_return = nav / previous_nav - Decimal(1) if previous_nav > 0 else Decimal(0)
        risk_target = apply_risk_policy(
            strategy_result,
            account,
            state,
            config.risk,
            regime_policy=regime_policy,
            daily_return=daily_return,
        )
        target_weights = dict(risk_target.target_weights)
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
