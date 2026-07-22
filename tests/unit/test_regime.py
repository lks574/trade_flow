from datetime import date, timedelta
from decimal import Decimal

from trade_flow.domain.config import load_config
from trade_flow.risk import (
    RegimeInput,
    RegimePolicy,
    RegimeState,
    adjust_weights_for_regime,
    build_regime_states,
)


def test_regime_enters_and_requires_three_false_days_to_exit() -> None:
    config = load_config("configs/strategy.toml").risk
    start = date(2026, 1, 1)
    inputs = [
        RegimeInput(start + timedelta(days=index), Decimal(20), Decimal(100)) for index in range(21)
    ]
    inputs.extend(
        [
            RegimeInput(start + timedelta(days=21), Decimal(31), Decimal(100)),
            RegimeInput(start + timedelta(days=22), Decimal(20), Decimal(100)),
            RegimeInput(start + timedelta(days=23), Decimal(20), Decimal(100)),
            RegimeInput(start + timedelta(days=24), Decimal(20), Decimal(100)),
        ]
    )

    states = build_regime_states(inputs, config)

    assert states[start + timedelta(days=21)].active
    assert states[start + timedelta(days=23)].active
    assert not states[start + timedelta(days=24)].active


def test_invalid_regime_data_is_fail_safe() -> None:
    config = load_config("configs/strategy.toml").risk
    session = date(2026, 1, 1)
    state = build_regime_states([RegimeInput(session, None, None)], config)[session]

    assert state.active
    assert not state.valid


def test_missing_wti_after_history_does_not_crash_and_fails_safe() -> None:
    # WTI history가 20거래일을 넘긴 뒤 WTI 종가가 빠진 세션(실데이터에서 VIX/WTI
    # 관측일 불일치로 발생). 크래시 없이 fail-closed(active, invalid) 여야 한다.
    config = load_config("configs/strategy.toml").risk
    start = date(2026, 1, 1)
    inputs = [
        RegimeInput(start + timedelta(days=index), Decimal(20), Decimal(100)) for index in range(25)
    ]
    gap_session = start + timedelta(days=25)
    inputs.append(RegimeInput(gap_session, Decimal(20), None))

    states = build_regime_states(inputs, config)

    assert states[gap_session].active
    assert not states[gap_session].valid
    assert "invalid_wti" in states[gap_session].reasons


def test_regime_policy_a_blocks_increases_and_b_caps_equity() -> None:
    config = load_config("configs/strategy.toml").risk
    state = RegimeState(date(2026, 1, 1), True, True, 0, ("vix",))
    target = {"A": Decimal("0.6"), "B": Decimal("0.3")}
    current = {"A": Decimal("0.2")}

    blocked = adjust_weights_for_regime(target, current, state, RegimePolicy.BUY_BLOCK, config)
    capped = adjust_weights_for_regime(target, current, state, RegimePolicy.EQUITY_CAP, config)

    assert blocked == {"A": Decimal("0.2"), "B": Decimal(0)}
    assert capped == {"A": Decimal("0.2"), "B": Decimal(0)}
