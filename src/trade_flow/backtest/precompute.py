"""심볼별 팩터 시계열 사전계산 (백테스트 성능용).

시점 t의 지표값은 ``closes[0..t]``에만 의존하므로, 각 지표의 전체 시계열을 심볼당
1회 forward-pass로 계산하면 세션마다 슬라이스를 재계산한 값과 **정확히 동일**하다
(EMA/RSI/SMA/momentum 모두 t까지의 점화식 값이 슬라이스 재계산과 bit-identical).

``precompute_factor_series(bars, config)[i]`` 는 ``signal._raw_factors(bars[:i+1], config)`` 와
같은 값을 반환한다(회귀 테스트로 검증). O(N^2) 재계산을 O(N)으로 바꾼다.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from trade_flow.data.market import DailyBar
from trade_flow.domain.config import StrategyConfig
from trade_flow.strategy.indicators import exponential_moving_average

RawFactors = tuple[Decimal, Decimal, Decimal, Decimal, Decimal]


def _rsi_from(average_gain: Decimal, average_loss: Decimal) -> Decimal:
    # strategy.indicators.relative_strength_index 의 종단 계산과 동일해야 한다.
    if average_loss == 0:
        return Decimal(100) if average_gain > 0 else Decimal(50)
    relative_strength = average_gain / average_loss
    return Decimal(100) - Decimal(100) / (Decimal(1) + relative_strength)


def _rsi_series(closes: Sequence[Decimal], period: int) -> list[Decimal | None]:
    """각 인덱스 i에서 relative_strength_index(closes[:i+1], period) 와 동일한 값."""
    n = len(closes)
    out: list[Decimal | None] = [None] * n
    if n <= period:
        return out
    gains: list[Decimal] = []
    losses: list[Decimal] = []
    for index in range(1, n):
        change = closes[index] - closes[index - 1]
        gains.append(change if change > 0 else Decimal(0))
        losses.append(-change if change < 0 else Decimal(0))
    # gains[j] 는 closes[j+1] 에 대응. 첫 period개 변화로 시드 → closes[:period+1] 의 RSI.
    average_gain = sum(gains[:period]) / Decimal(period)
    average_loss = sum(losses[:period]) / Decimal(period)
    out[period] = _rsi_from(average_gain, average_loss)
    for j in range(period, len(gains)):
        average_gain = (average_gain * Decimal(period - 1) + gains[j]) / Decimal(period)
        average_loss = (average_loss * Decimal(period - 1) + losses[j]) / Decimal(period)
        out[j + 1] = _rsi_from(average_gain, average_loss)
    return out


def precompute_factor_series(
    bars: Sequence[DailyBar], config: StrategyConfig
) -> list[RawFactors | None]:
    """인덱스 i에서 signal._raw_factors(sorted(bars)[:i+1], config) 와 동일한 튜플 또는 None."""
    ordered = sorted(bars, key=lambda bar: bar.session_date)
    n = len(ordered)
    out: list[RawFactors | None] = [None] * n
    if n < config.minimum_price_days:
        return out
    closes = [bar.split_adjusted_close for bar in ordered]
    dollars = [bar.split_adjusted_close * Decimal(bar.volume) for bar in ordered]
    ema_fast = exponential_moving_average(closes, config.macd_fast_days)
    ema_slow = exponential_moving_average(closes, config.macd_slow_days)
    macd_line = [fast - slow for fast, slow in zip(ema_fast, ema_slow, strict=True)]
    signal_line = exponential_moving_average(macd_line, config.macd_signal_days)
    rsi = _rsi_series(closes, config.rsi_days)
    long_period = config.sma_long_days
    short_period = config.sma_short_days
    liquidity_period = config.tie_break_liquidity_days
    for i in range(config.minimum_price_days - 1, n):
        long_sma = sum(closes[i - long_period + 1 : i + 1]) / Decimal(long_period)
        if closes[i] <= long_sma:
            continue
        short_sma = sum(closes[i - short_period + 1 : i + 1]) / Decimal(short_period)
        momentum = closes[i] / closes[i - config.momentum_days] - Decimal(1)
        trend = Decimal(short_sma > long_sma)
        rsi_value = rsi[i]
        rsi_signal = Decimal(rsi_value is not None and rsi_value < config.rsi_threshold)
        macd_signal = Decimal(macd_line[i] > signal_line[i])
        recent = dollars[i - liquidity_period + 1 : i + 1]
        average_dollar_volume = sum(recent) / Decimal(len(recent))
        out[i] = (momentum, trend, rsi_signal, macd_signal, average_dollar_volume)
    return out
