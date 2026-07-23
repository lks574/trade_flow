from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType

from trade_flow.domain.config import RiskConfig


class RegimePolicy(StrEnum):
    BUY_BLOCK = "buy_block"
    EQUITY_CAP = "equity_cap"


@dataclass(frozen=True)
class RegimeInput:
    session_date: date
    vix_close: Decimal | None
    wti_close: Decimal | None


@dataclass(frozen=True)
class RegimeState:
    session_date: date
    active: bool
    valid: bool
    false_streak: int
    reasons: tuple[str, ...]


def build_regime_states(
    inputs: Sequence[RegimeInput], config: RiskConfig
) -> Mapping[date, RegimeState]:
    ordered = sorted(inputs, key=lambda item: item.session_date)
    wti_history: list[Decimal] = []
    output: dict[date, RegimeState] = {}
    active = False
    false_streak = 0
    for item in ordered:
        reasons: list[str] = []
        valid = True
        if item.vix_close is None or item.vix_close <= 0:
            valid = False
            reasons.append("invalid_vix")
        if item.wti_close is None or item.wti_close <= 0:
            valid = False
            reasons.append("invalid_wti")
        if item.wti_close is not None and item.wti_close > 0:
            wti_history.append(item.wti_close)
        if len(wti_history) <= config.regime_wti_return_days:
            valid = False
            reasons.append("insufficient_wti_history")

        entry_triggered = False
        wti_triggered = False
        if item.vix_close is not None and item.vix_close > config.regime_vix_threshold:
            entry_triggered = True
            reasons.append("vix")
        # WTI 종가가 있는 세션에서만 20거래일 수익률을 계산한다. 종가가 없으면 위에서
        # 이미 valid=False(invalid_wti)로 fail-closed 처리되므로 트리거 계산을 건너뛴다.
        if (
            item.wti_close is not None
            and item.wti_close > 0
            and len(wti_history) > config.regime_wti_return_days
        ):
            previous_wti = wti_history[-(config.regime_wti_return_days + 1)]
            wti_return = wti_history[-1] / previous_wti - Decimal(1)
            if wti_return > config.regime_wti_return_threshold:
                entry_triggered = True
                wti_triggered = True
                reasons.append("wti")

        # 재진입 강화(비대칭 임계): 진입은 regime_vix_threshold, 해제는 exit 임계 이하가
        # regime_exit_confirmation_days 연속일 때만. exit 임계가 0이면 진입 임계로 폴백해
        # 기존 동작과 동일(bit-identical). exit < 진입이면 [exit, 진입] 구간이 hysteresis 밴드.
        exit_vix_threshold = (
            config.regime_exit_vix_threshold
            if config.regime_exit_vix_threshold > 0
            else config.regime_vix_threshold
        )
        still_risky = wti_triggered or (
            item.vix_close is not None and item.vix_close > exit_vix_threshold
        )

        if not valid or entry_triggered:
            active = True
            false_streak = 0
        elif active:
            if still_risky:
                false_streak = 0
            else:
                false_streak += 1
                if false_streak >= config.regime_exit_confirmation_days:
                    active = False
                    false_streak = 0
        else:
            false_streak = 0
        output[item.session_date] = RegimeState(
            session_date=item.session_date,
            active=active,
            valid=valid,
            false_streak=false_streak,
            reasons=tuple(reasons),
        )
    return MappingProxyType(output)


def adjust_weights_for_regime(
    target_weights: Mapping[str, Decimal],
    current_weights: Mapping[str, Decimal],
    state: RegimeState,
    policy: RegimePolicy,
    config: RiskConfig,
) -> Mapping[str, Decimal]:
    if not state.active:
        return MappingProxyType(dict(sorted(target_weights.items())))
    if policy is RegimePolicy.BUY_BLOCK:
        adjusted = {
            symbol: min(weight, current_weights.get(symbol, Decimal(0)))
            for symbol, weight in target_weights.items()
        }
    else:
        total = sum(target_weights.values())
        scale = min(Decimal(1), config.experimental_equity_cap / total) if total else Decimal(1)
        adjusted = {
            symbol: min(weight * scale, current_weights.get(symbol, Decimal(0)))
            for symbol, weight in target_weights.items()
        }
        if total > config.experimental_equity_cap and adjusted:
            excess = sum(adjusted.values()) - config.experimental_equity_cap
            if excess > 0:
                first_symbol = sorted(adjusted)[0]
                adjusted[first_symbol] -= excess
    return MappingProxyType(dict(sorted(adjusted.items())))
