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


def test_regime_exit_hysteresis_keeps_active_in_dip_band() -> None:
    # 진입 후 VIX가 [exit, entry) 밴드(예: 27, 진입 30/해제 25)에 머물면,
    # 기본(해제 30)은 해제되지만 hysteresis(해제 25)는 계속 active여야 한다.
    from dataclasses import replace

    base = load_config("configs/strategy.toml").risk  # regime_exit_vix_threshold=30
    start = date(2026, 1, 1)
    inputs = [
        RegimeInput(start + timedelta(days=index), Decimal(20), Decimal(100)) for index in range(21)
    ]
    inputs.append(RegimeInput(start + timedelta(days=21), Decimal(31), Decimal(100)))  # 진입
    for index in range(22, 27):  # VIX 27로 5거래일: 진입(30) 아래, 해제밴드(25) 위
        inputs.append(RegimeInput(start + timedelta(days=index), Decimal(27), Decimal(100)))

    default_states = build_regime_states(inputs, base)
    # 해제 임계 30: 27<=30 -> 위험 아님 -> 3일 후 해제.
    assert not default_states[start + timedelta(days=24)].active

    hyst = replace(base, regime_exit_vix_threshold=Decimal(25))
    hyst_states = build_regime_states(inputs, hyst)
    # 해제 임계 25: 27>25 -> 아직 위험 -> 밴드 내내 active 유지.
    assert hyst_states[start + timedelta(days=26)].active


def test_regime_exit_threshold_zero_sentinel_matches_entry_threshold() -> None:
    # 센티넬 0은 진입 임계로 폴백 -> 명시적 30과 동일한 상태열(bit-identical).
    from dataclasses import replace

    base = load_config("configs/strategy.toml").risk
    start = date(2026, 1, 1)
    inputs = [
        RegimeInput(start + timedelta(days=index), Decimal(20), Decimal(100)) for index in range(21)
    ]
    inputs.append(RegimeInput(start + timedelta(days=21), Decimal(31), Decimal(100)))
    for index in range(22, 27):
        inputs.append(RegimeInput(start + timedelta(days=index), Decimal(27), Decimal(100)))

    explicit30 = build_regime_states(inputs, replace(base, regime_exit_vix_threshold=Decimal(30)))
    sentinel0 = build_regime_states(inputs, replace(base, regime_exit_vix_threshold=Decimal(0)))
    e30 = [(s.active, s.false_streak) for s in explicit30.values()]
    s0 = [(s.active, s.false_streak) for s in sentinel0.values()]
    assert e30 == s0


def test_regime_exit_threshold_above_entry_rejected() -> None:
    import pytest

    from trade_flow.domain.config import ConfigError

    base = load_config("configs/strategy.toml").risk
    from dataclasses import replace

    with pytest.raises(ConfigError):
        replace(base, regime_exit_vix_threshold=Decimal(35))  # 진입(30) 초과 금지
