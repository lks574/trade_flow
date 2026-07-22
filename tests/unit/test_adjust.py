from decimal import Decimal

from trade_flow.data import split_adjustment_divisors


def test_split_divisors_back_adjust_prior_bars() -> None:
    # 2:1 split on the 3rd of four sessions -> earlier bars halved, rest unchanged.
    assert split_adjustment_divisors([Decimal(1), Decimal(1), Decimal(2), Decimal(1)]) == [
        Decimal(2),
        Decimal(2),
        Decimal(1),
        Decimal(1),
    ]


def test_split_divisors_compound() -> None:
    assert split_adjustment_divisors([Decimal(1), Decimal(2), Decimal(3)]) == [
        Decimal(6),
        Decimal(3),
        Decimal(1),
    ]


def test_split_divisors_no_splits() -> None:
    assert split_adjustment_divisors([Decimal(1)] * 3) == [Decimal(1)] * 3
