"""목표 주가 예보(확률 구간) 계산.

점 예측이 아니라 검증 가능한 확률 예보를 만든다:
  - 기대 경로: 최근 모멘텀 drift를 감쇠(0.3배) 반영한 로그정규 중앙 경로
  - 68% 구간: 실현 변동성(63세션 로그수익률 표준편차) 기반 ±1σ√h
  - 손절 제안: 1.5 × ATR(14)
  - 컨텍스트 조정: VIX 수준이 높으면 drift를 죽이고 구간을 넓힘(방향 예측 억제),
    감정점수는 drift를 ±30% 이내에서만 기울임(과신 방지)

모든 가정이 PriceTarget에 기록되어 사후 캘리브레이션 채점(구간 적중률이 명목
68%에 근접하는지)이 가능하다. 채점은 scripts/track_recommendations.py가 수행.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

# drift 감쇠: 과거 모멘텀이 그대로 이어진다는 가정은 과신이므로 0.3배만 반영.
_DRIFT_DAMPING = 0.3
# 감정 기울기 상한: 감정점수(-1~1)가 drift를 ±30%까지만 조정.
_SENTIMENT_TILT_LIMIT = 0.3
# VIX 경계: 이상이면 방향 예측을 포기(drift=0)하고 구간을 넓힌다.
_VIX_NO_DRIFT = 25.0
_VIX_HALF_DRIFT = 20.0
_VIX_BAND_WIDEN = 1.25

LOOKBACK_SESSIONS = 63
ATR_PERIOD = 14
STOP_ATR_MULTIPLE = 1.5


@dataclass(frozen=True)
class MarketContext:
    """예보 시점의 시장 컨텍스트. 지정학 스트레스는 VIX(주식 공포)와
    WTI 모멘텀(에너지/전쟁 프리미엄)의 정량 그림자로만 반영한다."""

    vix: float | None  # 최근 VIX 종가(없으면 None → 조정 생략)
    wti_momentum_21d: float | None  # WTI 21세션 수익률(에너지 컨텍스트 표시용)


@dataclass(frozen=True)
class PriceTarget:
    symbol: str
    as_of: date
    horizon_sessions: int
    basis_close: Decimal  # 기준 수정종가
    expected: Decimal  # 기대 경로(중앙값)
    low_68: Decimal
    high_68: Decimal
    stop: Decimal  # 손절 제안(1.5×ATR)
    drift_daily: float  # 감쇠·조정 후 일일 drift(로그)
    sigma_daily: float  # 일일 변동성(로그)
    sentiment_score: float | None  # 입력 감정점수(-1~1, 없으면 None)
    vix: float | None
    wti_momentum_21d: float | None

    @property
    def expected_return(self) -> float:
        return float(self.expected / self.basis_close) - 1.0


def _drift_multiplier(vix: float | None) -> float:
    if vix is None:
        return 1.0
    if vix >= _VIX_NO_DRIFT:
        return 0.0
    if vix >= _VIX_HALF_DRIFT:
        return 0.5
    return 1.0


def _band_multiplier(vix: float | None) -> float:
    return _VIX_BAND_WIDEN if vix is not None and vix >= _VIX_NO_DRIFT else 1.0


def compute_price_target(
    symbol: str,
    *,
    as_of: date,
    closes: list[Decimal],
    highs: list[Decimal],
    lows: list[Decimal],
    horizon_sessions: int,
    sentiment_score: float | None = None,
    context: MarketContext | None = None,
) -> PriceTarget:
    """수정 OHLC 시계열(오름차순, 마지막이 as_of 세션)로 목표가 예보를 만든다."""
    if horizon_sessions < 1:
        raise ValueError("horizon_sessions must be >= 1")
    if len(closes) < LOOKBACK_SESSIONS + 1:
        raise ValueError(f"need at least {LOOKBACK_SESSIONS + 1} closes, got {len(closes)}")
    if not (len(closes) == len(highs) == len(lows)):
        raise ValueError("closes/highs/lows must be same length")
    if sentiment_score is not None and not -1.0 <= sentiment_score <= 1.0:
        raise ValueError("sentiment_score must be in [-1, 1]")

    import math

    window = [float(c) for c in closes[-(LOOKBACK_SESSIONS + 1) :]]
    log_returns = [math.log(b / a) for a, b in zip(window[:-1], window[1:], strict=True)]
    mu_raw = statistics.fmean(log_returns)
    sigma = statistics.pstdev(log_returns)

    vix = context.vix if context else None
    drift = mu_raw * _DRIFT_DAMPING * _drift_multiplier(vix)
    if sentiment_score is not None:
        drift *= 1.0 + _SENTIMENT_TILT_LIMIT * sentiment_score
    band_sigma = sigma * _band_multiplier(vix)

    basis = closes[-1]
    h = horizon_sessions
    expected = float(basis) * math.exp(drift * h)
    spread = band_sigma * math.sqrt(h)
    low = float(basis) * math.exp(drift * h - spread)
    high = float(basis) * math.exp(drift * h + spread)

    # ATR(14): 수정 OHLC 기반 단순 평균 true range.
    trs = []
    for i in range(-ATR_PERIOD, 0):
        high_low = float(highs[i]) - float(lows[i])
        high_close = abs(float(highs[i]) - float(closes[i - 1]))
        low_close = abs(float(lows[i]) - float(closes[i - 1]))
        trs.append(max(high_low, high_close, low_close))
    atr = statistics.fmean(trs)
    stop = float(basis) - STOP_ATR_MULTIPLE * atr

    cents = Decimal("0.01")

    def _d(value: float) -> Decimal:
        return Decimal(str(value)).quantize(cents)

    return PriceTarget(
        symbol=symbol,
        as_of=as_of,
        horizon_sessions=horizon_sessions,
        basis_close=basis,
        expected=_d(expected),
        low_68=_d(low),
        high_68=_d(high),
        stop=_d(max(stop, 0.0)),
        drift_daily=drift,
        sigma_daily=sigma,
        sentiment_score=sentiment_score,
        vix=vix,
        wti_momentum_21d=context.wti_momentum_21d if context else None,
    )
