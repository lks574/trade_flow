from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal


def simple_moving_average(values: Sequence[Decimal], period: int) -> Decimal:
    if period <= 0 or len(values) < period:
        raise ValueError("insufficient values for moving average")
    return sum(values[-period:]) / Decimal(period)


def exponential_moving_average(values: Sequence[Decimal], period: int) -> tuple[Decimal, ...]:
    if period <= 0 or not values:
        raise ValueError("EMA requires a positive period and at least one value")
    alpha = Decimal(2) / Decimal(period + 1)
    output = [values[0]]
    for value in values[1:]:
        output.append(alpha * value + (Decimal(1) - alpha) * output[-1])
    return tuple(output)


def relative_strength_index(values: Sequence[Decimal], period: int) -> Decimal:
    if period <= 0 or len(values) <= period:
        raise ValueError("insufficient values for RSI")
    changes = [current - previous for previous, current in zip(values, values[1:], strict=False)]
    gains = [max(change, Decimal(0)) for change in changes]
    losses = [max(-change, Decimal(0)) for change in changes]
    average_gain = sum(gains[:period]) / Decimal(period)
    average_loss = sum(losses[:period]) / Decimal(period)
    for gain, loss in zip(gains[period:], losses[period:], strict=False):
        average_gain = (average_gain * Decimal(period - 1) + gain) / Decimal(period)
        average_loss = (average_loss * Decimal(period - 1) + loss) / Decimal(period)
    if average_loss == 0:
        return Decimal(100) if average_gain > 0 else Decimal(50)
    relative_strength = average_gain / average_loss
    return Decimal(100) - Decimal(100) / (Decimal(1) + relative_strength)


def macd(
    values: Sequence[Decimal], fast_period: int, slow_period: int, signal_period: int
) -> tuple[Decimal, Decimal]:
    if fast_period >= slow_period:
        raise ValueError("MACD fast period must be shorter than slow period")
    if len(values) < slow_period + signal_period:
        raise ValueError("insufficient values for MACD")
    fast = exponential_moving_average(values, fast_period)
    slow = exponential_moving_average(values, slow_period)
    line = tuple(fast_value - slow_value for fast_value, slow_value in zip(fast, slow, strict=True))
    signal_line = exponential_moving_average(line, signal_period)
    return line[-1], signal_line[-1]


def percentile_ranks(values: dict[str, Decimal]) -> dict[str, Decimal]:
    if not values:
        return {}
    if len(values) == 1:
        return {next(iter(values)): Decimal(1)}
    ordered_values = sorted(set(values.values()))
    ranks: dict[Decimal, Decimal] = {}
    for value in ordered_values:
        positions = [index for index, item in enumerate(sorted(values.values())) if item == value]
        average_position = Decimal(sum(positions)) / Decimal(len(positions))
        ranks[value] = average_position / Decimal(len(values) - 1)
    return {symbol: ranks[value] for symbol, value in values.items()}
