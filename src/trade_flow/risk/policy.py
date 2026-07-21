from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType

from trade_flow.domain.config import RiskConfig
from trade_flow.execution.models import AccountSnapshot
from trade_flow.risk.regime import RegimePolicy, RegimeState, adjust_weights_for_regime
from trade_flow.strategy import StrategyResult


@dataclass(frozen=True)
class RiskAdjustedTarget:
    target_weights: Mapping[str, Decimal]
    cash_weight: Decimal
    blocked_buys: bool
    reasons: tuple[str, ...]


def _current_weights(account: AccountSnapshot) -> dict[str, Decimal]:
    return {
        symbol: Decimal(position.quantity) * position.market_price / account.nav
        for symbol, position in account.positions.items()
        if position.quantity > 0
    }


def apply_risk_policy(
    strategy_result: StrategyResult,
    account: AccountSnapshot,
    regime: RegimeState,
    config: RiskConfig,
    *,
    regime_policy: RegimePolicy,
    daily_return: Decimal,
) -> RiskAdjustedTarget:
    targets = dict(strategy_result.target_weights)
    reasons: list[str] = []
    for symbol, position in account.positions.items():
        if position.market_price <= position.average_price * (
            Decimal(1) - config.stop_loss_fraction
        ):
            targets[symbol] = Decimal(0)
            reasons.append(f"stop_loss:{symbol}")

    current_weights = _current_weights(account)
    targets = dict(
        adjust_weights_for_regime(
            targets,
            current_weights,
            regime,
            regime_policy,
            config,
        )
    )
    blocked_buys = regime.active
    if regime.active:
        reasons.append(f"regime:{regime_policy.value}")
    if daily_return <= -config.daily_loss_limit_fraction:
        targets = {
            symbol: min(weight, current_weights.get(symbol, Decimal(0)))
            for symbol, weight in targets.items()
        }
        blocked_buys = True
        reasons.append("daily_loss_limit")

    cash_weight = Decimal(1) - sum(targets.values())
    if cash_weight < 0:
        raise ValueError("risk-adjusted target exceeds total NAV")
    return RiskAdjustedTarget(
        target_weights=MappingProxyType(dict(sorted(targets.items()))),
        cash_weight=cash_weight,
        blocked_buys=blocked_buys,
        reasons=tuple(reasons),
    )
