from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from hashlib import sha256
from types import MappingProxyType

from trade_flow.domain.config import ExecutionConfig
from trade_flow.execution.models import AccountSnapshot, OrderIntent, OrderPlan, Quote


def _round_to_tick(value: Decimal, tick: Decimal, *, upward: bool) -> Decimal:
    rounding = ROUND_CEILING if upward else ROUND_FLOOR
    units = (value / tick).to_integral_value(rounding=rounding)
    return units * tick


def _intent_id(
    account_hash: str,
    trading_date: date,
    strategy_version: str,
    symbol: str,
    side: str,
    rebalance_sequence: int,
) -> str:
    payload = "/".join(
        (
            account_hash,
            trading_date.isoformat(),
            strategy_version,
            symbol,
            side,
            str(rebalance_sequence),
        )
    )
    return sha256(payload.encode("utf-8")).hexdigest()


def plan_orders(
    account: AccountSnapshot,
    target_weights: Mapping[str, Decimal],
    quotes: Mapping[str, Quote],
    *,
    trading_date: date,
    strategy_version: str,
    cash_buffer_fraction: Decimal,
    config: ExecutionConfig,
    rebalance_sequence: int = 0,
    risk_reduced_symbols: frozenset[str] = frozenset(),
) -> OrderPlan:
    if any(weight < 0 for weight in target_weights.values()) or sum(
        target_weights.values()
    ) > Decimal(1):
        raise ValueError("target weights must be non-negative and sum to at most one")
    if not Decimal(0) <= cash_buffer_fraction < Decimal(1):
        raise ValueError("cash buffer fraction must be in [0, 1)")
    symbols = set(account.positions) | set(target_weights)
    targets: dict[str, int] = {}
    limits: dict[tuple[str, str], Decimal] = {}
    drift: dict[str, str] = {}
    for symbol in sorted(symbols):
        quote = quotes.get(symbol)
        if quote is None:
            drift[symbol] = "missing_quote"
            continue
        buy_limit = _round_to_tick(
            quote.ask * (Decimal(1) + config.limit_offset_fraction),
            config.default_tick_size,
            upward=True,
        )
        sell_limit = _round_to_tick(
            quote.bid * (Decimal(1) - config.limit_offset_fraction),
            config.default_tick_size,
            upward=False,
        )
        limits[(symbol, "buy")] = buy_limit
        limits[(symbol, "sell")] = sell_limit
        target_amount = account.nav * target_weights.get(symbol, Decimal(0))
        targets[symbol] = int((target_amount / buy_limit).to_integral_value(rounding=ROUND_FLOOR))

    if config.rebalance_band > 0 and account.nav > 0:
        # §3.5 no-trade band: 보유 중이고 여전히 선정된 종목의 비중 드리프트가 밴드 이내이고
        # 리스크 축소 대상이 아니면 재조정 주문을 생략(현재 수량 유지)하고 drift로 기록한다.
        # 신규 진입(현재 0)·청산/손절(목표 0)·리스크 축소는 밴드와 무관하게 실행한다.
        for symbol in list(targets):
            if symbol in risk_reduced_symbols:
                continue
            current = account.positions.get(symbol)
            target_weight = target_weights.get(symbol, Decimal(0))
            if current is None or current.quantity <= 0 or target_weight <= 0:
                continue
            current_weight = Decimal(current.quantity) * current.market_price / account.nav
            if abs(target_weight - current_weight) <= config.rebalance_band:
                targets[symbol] = current.quantity
                drift[symbol] = "within_rebalance_band"

    sells: list[OrderIntent] = []
    buy_requests: list[tuple[str, int]] = []
    for symbol in sorted(targets):
        current = account.positions.get(symbol)
        current_quantity = current.quantity if current else 0
        difference = targets[symbol] - current_quantity
        if difference < 0:
            side = "sell"
            quantity = -difference
            sells.append(
                OrderIntent(
                    _intent_id(
                        account.account_hash,
                        trading_date,
                        strategy_version,
                        symbol,
                        side,
                        rebalance_sequence,
                    ),
                    trading_date,
                    symbol,
                    side,
                    quantity,
                    limits[(symbol, side)],
                    rebalance_sequence,
                )
            )
        elif difference > 0:
            buy_requests.append((symbol, difference))

    available_cash = max(Decimal(0), account.cash - account.nav * cash_buffer_fraction)
    fee_rate = Decimal(config.estimated_fee_bps) / Decimal(10000)
    buys: list[OrderIntent] = []
    for symbol, requested in sorted(
        buy_requests,
        key=lambda item: (-target_weights.get(item[0], Decimal(0)), item[0]),
    ):
        price = limits[(symbol, "buy")]
        per_share = price * (Decimal(1) + fee_rate)
        affordable = int((available_cash / per_share).to_integral_value(rounding=ROUND_FLOOR))
        quantity = min(requested, affordable)
        if quantity <= 0:
            drift[symbol] = "insufficient_cash"
            continue
        available_cash -= Decimal(quantity) * per_share
        buys.append(
            OrderIntent(
                _intent_id(
                    account.account_hash,
                    trading_date,
                    strategy_version,
                    symbol,
                    "buy",
                    rebalance_sequence,
                ),
                trading_date,
                symbol,
                "buy",
                quantity,
                price,
                rebalance_sequence,
            )
        )
        if quantity < requested:
            drift[symbol] = "cash_limited_quantity"
    return OrderPlan(
        intents=tuple([*sells, *buys]),
        drift=MappingProxyType(dict(sorted(drift.items()))),
    )
