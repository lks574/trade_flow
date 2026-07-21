from decimal import Decimal

from trade_flow.strategy.indicators import (
    macd,
    percentile_ranks,
    relative_strength_index,
    simple_moving_average,
)


def test_indicator_reference_values() -> None:
    values = [Decimal(value) for value in range(1, 41)]

    assert simple_moving_average(values, 5) == Decimal(38)
    assert relative_strength_index(values, 14) == Decimal(100)
    line, signal = macd(values, 12, 26, 9)
    assert line > signal


def test_percentile_rank_uses_average_rank_for_ties() -> None:
    ranks = percentile_ranks(
        {"A": Decimal("1"), "B": Decimal("2"), "C": Decimal("2"), "D": Decimal("4")}
    )

    assert ranks["A"] == Decimal(0)
    assert ranks["B"] == ranks["C"] == Decimal("0.5")
    assert ranks["D"] == Decimal(1)
