from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from types import MappingProxyType
from typing import Protocol

from trade_flow.db.execution import OrderRepository
from trade_flow.domain.config import AppConfig
from trade_flow.execution.executor import execute_plan
from trade_flow.execution.models import (
    AccountSnapshot,
    BrokerOrder,
    OrderIntent,
    OrderPlan,
    Quote,
)
from trade_flow.execution.planner import plan_orders
from trade_flow.risk import (
    RegimePolicy,
    RegimeState,
    RiskAdjustedTarget,
    apply_risk_policy,
)
from trade_flow.safety import SafetyContext, apply_safety_filters, authorize_execution
from trade_flow.strategy import StrategyResult


def _risk_reduced_symbols(
    strategy_result: StrategyResult, risk_target: RiskAdjustedTarget
) -> frozenset[str]:
    """리스크 정책이 전략 목표보다 낮춘 종목. no-trade band 억제에서 제외해야 한다(§3.5)."""
    strategy_weights = strategy_result.target_weights
    return frozenset(
        symbol
        for symbol, weight in risk_target.target_weights.items()
        if weight < strategy_weights.get(symbol, Decimal(0))
    )


class RebalanceBroker(Protocol):
    def account_snapshot(self) -> AccountSnapshot: ...

    def quote(self, symbol: str) -> Quote: ...

    def find_by_intent(self, intent_id: str) -> BrokerOrder | None: ...

    def submit(self, intent: OrderIntent) -> BrokerOrder: ...

    def await_terminal(self, order: BrokerOrder, timeout_seconds: int) -> BrokerOrder: ...

    def cancel(self, broker_order_id: str) -> BrokerOrder: ...


@dataclass(frozen=True)
class RebalanceResult:
    risk_target: RiskAdjustedTarget
    sell_plan: OrderPlan
    buy_plan: OrderPlan
    broker_orders: tuple[BrokerOrder, ...]
    final_account: AccountSnapshot


def _quotes(
    broker: RebalanceBroker,
    account: AccountSnapshot,
    targets: Mapping[str, Decimal],
) -> dict[str, Quote]:
    return {
        symbol: broker.quote(symbol) for symbol in sorted(set(account.positions) | set(targets))
    }


def _side(plan: OrderPlan, side: str) -> OrderPlan:
    return OrderPlan(
        intents=tuple(intent for intent in plan.intents if intent.side == side),
        drift=MappingProxyType(dict(plan.drift)),
    )


def execute_rebalance(
    strategy_result: StrategyResult,
    regime: RegimeState,
    config: AppConfig,
    broker: RebalanceBroker,
    repository: OrderRepository,
    *,
    run_id: str,
    trading_date: date,
    safety_context: SafetyContext,
    daily_return: Decimal,
    regime_policy: RegimePolicy,
) -> RebalanceResult:
    initial_account = broker.account_snapshot()
    if initial_account.account_hash != safety_context.account_hash:
        raise ValueError("safety context account does not match broker account")
    if daily_return != safety_context.daily_return:
        raise ValueError("risk and safety daily returns do not match")
    risk_target = apply_risk_policy(
        strategy_result,
        initial_account,
        regime,
        config.risk,
        regime_policy=regime_policy,
        daily_return=daily_return,
    )
    initial_plan = plan_orders(
        initial_account,
        risk_target.target_weights,
        _quotes(broker, initial_account, risk_target.target_weights),
        trading_date=trading_date,
        strategy_version=config.strategy_version,
        cash_buffer_fraction=config.strategy.cash_buffer_weight,
        config=config.execution,
        rebalance_sequence=0,
        risk_reduced_symbols=_risk_reduced_symbols(strategy_result, risk_target),
    )
    sell_plan = _side(initial_plan, "sell")
    completed: list[BrokerOrder] = []
    if sell_plan.intents:
        permit = authorize_execution(safety_context, sell_plan, run_id=run_id)
        completed.extend(
            execute_plan(
                sell_plan,
                broker,
                repository,
                run_id=run_id,
                timeout_seconds=config.execution.order_timeout_seconds,
                permit=permit,
            )
        )

    refreshed_account = broker.account_snapshot()
    if refreshed_account.account_hash != initial_account.account_hash:
        raise ValueError("broker account changed during rebalance")
    risk_target = apply_risk_policy(
        strategy_result,
        refreshed_account,
        regime,
        config.risk,
        regime_policy=regime_policy,
        daily_return=daily_return,
    )
    refreshed_plan = plan_orders(
        refreshed_account,
        risk_target.target_weights,
        _quotes(broker, refreshed_account, risk_target.target_weights),
        trading_date=trading_date,
        strategy_version=config.strategy_version,
        cash_buffer_fraction=config.strategy.cash_buffer_weight,
        config=config.execution,
        rebalance_sequence=1,
        risk_reduced_symbols=_risk_reduced_symbols(strategy_result, risk_target),
    )
    buy_plan = apply_safety_filters(safety_context, _side(refreshed_plan, "buy"))
    if buy_plan.intents:
        permit = authorize_execution(safety_context, buy_plan, run_id=run_id)
        completed.extend(
            execute_plan(
                buy_plan,
                broker,
                repository,
                run_id=run_id,
                timeout_seconds=config.execution.order_timeout_seconds,
                permit=permit,
            )
        )
    return RebalanceResult(
        risk_target=risk_target,
        sell_plan=sell_plan,
        buy_plan=buy_plan,
        broker_orders=tuple(completed),
        final_account=broker.account_snapshot(),
    )
