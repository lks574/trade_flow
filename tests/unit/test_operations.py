from datetime import date
from decimal import Decimal

from trade_flow.operations import NavHistory


def test_nav_history_daily_return_and_record(tmp_path) -> None:
    hist = NavHistory(tmp_path / "nav.json")
    # 첫 기록 전엔 daily_return 0.
    assert hist.daily_return(Decimal("100"), on=date(2026, 7, 21)) == Decimal(0)
    hist.record(date(2026, 7, 20), Decimal("100"))
    hist.record(date(2026, 7, 21), Decimal("110"))
    # 7/22의 전 거래일(7/21=110) 대비 121 -> +10%.
    assert hist.daily_return(Decimal("121"), on=date(2026, 7, 22)) == Decimal("0.1")
    # 당일 재실행: on 미포함이라 7/21 기준 유지(7/22 값 무시).
    hist.record(date(2026, 7, 22), Decimal("121"))
    assert hist.daily_return(Decimal("121"), on=date(2026, 7, 22)) == Decimal("0.1")


def test_nav_history_last_before_ignores_same_and_future(tmp_path) -> None:
    hist = NavHistory(tmp_path / "nav.json")
    hist.record(date(2026, 7, 20), Decimal("100"))
    hist.record(date(2026, 7, 25), Decimal("200"))
    assert hist.last_before(date(2026, 7, 22)) == (date(2026, 7, 20), Decimal("100"))
    assert hist.last_before(date(2026, 7, 20)) is None  # 동일일 미포함


def test_nav_history_missing_file_is_empty(tmp_path) -> None:
    hist = NavHistory(tmp_path / "absent.json")
    assert hist.last_before(date(2026, 7, 22)) is None
    assert hist.daily_return(Decimal("100"), on=date(2026, 7, 22)) == Decimal(0)
