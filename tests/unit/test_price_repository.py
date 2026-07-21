from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from trade_flow.data import DailyBar, DataQualityError, build_market_data_snapshot
from trade_flow.db import PriceRepository, initialize_database


def _snapshot(*, valid: bool = True):
    session = date(2026, 7, 20)
    bar = DailyBar(
        symbol="AAPL",
        session_date=session,
        open=Decimal("10"),
        high=Decimal("11"),
        low=Decimal("9"),
        close=Decimal("10.5"),
        split_adjusted_open=Decimal("10"),
        split_adjusted_high=Decimal("11"),
        split_adjusted_low=Decimal("9"),
        split_adjusted_close=Decimal("10.5"),
        volume=100,
        cash_dividend=Decimal("0.25"),
        source="fixture",
        fetched_at=datetime(2026, 7, 21, tzinfo=UTC),
    )
    expected_symbols = ["AAPL"] if valid else ["AAPL", "MSFT"]
    return build_market_data_snapshot(
        [bar],
        as_of=session,
        expected_sessions=[session],
        expected_symbols=expected_symbols,
        recent_session_count=1,
    )


def test_repository_round_trip_preserves_decimal_data(tmp_path) -> None:
    database = initialize_database(tmp_path / "trade_flow.db")
    repository = PriceRepository(database)
    snapshot = _snapshot()

    assert repository.save_snapshot(snapshot) == 1
    loaded = repository.load_bars(
        symbols=["AAPL"],
        start=date(2026, 7, 20),
        end=date(2026, 7, 20),
        source="fixture",
    )

    assert loaded == snapshot.prices
    assert loaded[0].cash_dividend == Decimal("0.25")


def test_repository_refuses_invalid_snapshot(tmp_path) -> None:
    database = initialize_database(tmp_path / "trade_flow.db")
    repository = PriceRepository(database)

    with pytest.raises(DataQualityError, match="missing_recent_bar"):
        repository.save_snapshot(_snapshot(valid=False))
