import math
from datetime import date
from decimal import Decimal

import pytest

from trade_flow.research import MarketContext, compute_price_target


def _series(n: int = 80, daily: float = 0.01) -> tuple[list, list, list]:
    """일일 +1% 추세 + 결정적 노이즈(±0.5%) 시계열 — σ>0 보장."""
    closes = [
        Decimal(str(round(100 * math.exp(daily * i + 0.005 * math.sin(i * 1.7)), 4)))
        for i in range(n)
    ]
    highs = [c * Decimal("1.01") for c in closes]
    lows = [c * Decimal("0.99") for c in closes]
    return closes, highs, lows


def test_target_structure_and_ordering() -> None:
    closes, highs, lows = _series()
    t = compute_price_target(
        "TEST", as_of=date(2026, 7, 22), closes=closes, highs=highs, lows=lows,
        horizon_sessions=5,
    )
    assert t.low_68 < t.expected < t.high_68
    assert t.stop < t.basis_close
    # 상승 추세 → 감쇠된 양의 drift → 기대가 > 기준가.
    assert t.expected > t.basis_close
    # drift 감쇠 0.3배: 일일 1% 추세면 기대 수익은 5세션 ≈ 1.5% 근처(±수치 오차).
    assert 0.005 < t.expected_return < 0.03


def test_high_vix_kills_drift_and_widens_band() -> None:
    closes, highs, lows = _series()
    calm = compute_price_target(
        "TEST", as_of=date(2026, 7, 22), closes=closes, highs=highs, lows=lows,
        horizon_sessions=5, context=MarketContext(vix=15.0, wti_momentum_21d=None),
    )
    stressed = compute_price_target(
        "TEST", as_of=date(2026, 7, 22), closes=closes, highs=highs, lows=lows,
        horizon_sessions=5, context=MarketContext(vix=30.0, wti_momentum_21d=None),
    )
    # VIX 25+: 방향 예측 포기(drift=0 → 기대≈기준가, 센트 반올림 오차만 허용).
    assert stressed.drift_daily == 0.0
    assert abs(stressed.expected_return) < 1e-4
    calm_width = float(calm.high_68 - calm.low_68)
    stressed_width = float(stressed.high_68 - stressed.low_68)
    assert stressed_width > calm_width


def test_sentiment_tilts_drift_within_limit() -> None:
    closes, highs, lows = _series()
    kwargs = dict(
        as_of=date(2026, 7, 22), closes=closes, highs=highs, lows=lows, horizon_sessions=5
    )
    neutral = compute_price_target("TEST", **kwargs)
    bullish = compute_price_target("TEST", sentiment_score=1.0, **kwargs)
    bearish = compute_price_target("TEST", sentiment_score=-1.0, **kwargs)
    # 상승 추세에서 감정 +1은 drift를 최대 +30% 키우고, -1은 -30% 줄인다.
    assert bearish.expected < neutral.expected < bullish.expected
    assert bullish.drift_daily == pytest.approx(neutral.drift_daily * 1.3)
    assert bearish.drift_daily == pytest.approx(neutral.drift_daily * 0.7)


def test_input_validation() -> None:
    closes, highs, lows = _series(n=30)  # lookback 미달
    with pytest.raises(ValueError, match="need at least"):
        compute_price_target(
            "TEST", as_of=date(2026, 7, 22), closes=closes, highs=highs, lows=lows,
            horizon_sessions=5,
        )
    closes, highs, lows = _series()
    with pytest.raises(ValueError, match="sentiment_score"):
        compute_price_target(
            "TEST", as_of=date(2026, 7, 22), closes=closes, highs=highs, lows=lows,
            horizon_sessions=5, sentiment_score=2.0,
        )
