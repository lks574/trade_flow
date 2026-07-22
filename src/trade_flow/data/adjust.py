from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal


def split_adjustment_divisors(split_ratios: Sequence[Decimal]) -> list[Decimal]:
    """Back-adjust divisors for split-only price adjustment.

    ``split_ratios`` is chronological, one entry per session: the split ratio whose
    ex-date is that session (``Decimal(1)`` when there is no split). The returned
    divisor for session ``i`` is the product of every ratio with ex-date *after*
    ``i`` -- so a 2:1 split scales all prior prices down by 2 while the ex-date bar
    and later bars stay unchanged. Divide raw OHLC by these to get split-adjusted OHLC.
    """
    divisors = [Decimal(1)] * len(split_ratios)
    running = Decimal(1)
    for index in range(len(split_ratios) - 1, -1, -1):
        divisors[index] = running
        running *= split_ratios[index]
    return divisors


def _demo() -> None:
    # 2:1 split on the 3rd of four sessions -> first two bars halved, rest unchanged.
    divisors = split_adjustment_divisors([Decimal(1), Decimal(1), Decimal(2), Decimal(1)])
    assert divisors == [Decimal(2), Decimal(2), Decimal(1), Decimal(1)], divisors
    # No splits -> all divisors 1.
    assert split_adjustment_divisors([Decimal(1)] * 3) == [Decimal(1)] * 3
    # Two splits compound for the earliest bar.
    assert split_adjustment_divisors([Decimal(1), Decimal(2), Decimal(3)]) == [
        Decimal(6),
        Decimal(3),
        Decimal(1),
    ]
    print("ok")


if __name__ == "__main__":
    _demo()
