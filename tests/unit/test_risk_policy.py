from datetime import UTC, date, datetime
from decimal import Decimal
from types import MappingProxyType

from trade_flow.domain.config import load_config
from trade_flow.execution import AccountSnapshot, PositionSnapshot
from trade_flow.risk import RegimePolicy, RegimeState, apply_risk_policy
from trade_flow.strategy import StrategyResult


def _strategy_result() -> StrategyResult:
    return StrategyResult(
        date(2026, 1, 1),
        MappingProxyType({"A": Decimal("0.4"), "B": Decimal("0.4")}),
        Decimal("0.2"),
        MappingProxyType({}),
        MappingProxyType({}),
    )


def _account() -> AccountSnapshot:
    return AccountSnapshot(
        account_hash="account",
        captured_at=datetime(2026, 1, 1, tzinfo=UTC),
        nav=Decimal("1000"),
        cash=Decimal("600"),
        positions=MappingProxyType({"A": PositionSnapshot("A", 4, Decimal("120"), Decimal("100"))}),
    )


def test_shared_risk_policy_applies_stop_and_blocks_new_buys() -> None:
    config = load_config("configs/strategy.toml").risk
    regime = RegimeState(date(2026, 1, 1), True, True, 0, ("vix",))

    target = apply_risk_policy(
        _strategy_result(),
        _account(),
        regime,
        config,
        regime_policy=RegimePolicy.EQUITY_CAP,
        daily_return=Decimal(0),
    )

    assert target.target_weights["A"] == 0
    assert target.target_weights["B"] == 0
    assert target.blocked_buys
    assert "stop_loss:A" in target.reasons


def test_daily_loss_policy_preserves_reductions_but_removes_increases() -> None:
    config = load_config("configs/strategy.toml").risk
    normal = RegimeState(date(2026, 1, 1), False, True, 0, ())

    target = apply_risk_policy(
        _strategy_result(),
        _account(),
        normal,
        config,
        regime_policy=RegimePolicy.BUY_BLOCK,
        daily_return=Decimal("-0.03"),
    )

    assert target.target_weights["A"] == 0
    assert target.target_weights["B"] == 0
    assert "daily_loss_limit" in target.reasons
