from datetime import UTC, date, datetime
from decimal import Decimal

from trade_flow.db import MarketContextRepository, initialize_database
from trade_flow.db.market_context import VIX, WTI


def test_regime_inputs_join_vix_and_wti_by_session(tmp_path) -> None:
    database = initialize_database(tmp_path / "trade_flow.db")
    repository = MarketContextRepository(database)
    fetched_at = datetime(2026, 7, 21, tzinfo=UTC)
    day1, day2 = date(2026, 7, 20), date(2026, 7, 21)

    repository.save(
        indicator=VIX,
        closes=[(day1, Decimal("15.5")), (day2, Decimal("31.0"))],
        source="fixture",
        fetched_at=fetched_at,
    )
    # day2 has no WTI close -> RegimeInput.wti_close should be None there.
    repository.save(
        indicator=WTI,
        closes=[(day1, Decimal("80.0"))],
        source="fixture",
        fetched_at=fetched_at,
    )

    inputs = repository.load_regime_inputs(start=day1, end=day2, source="fixture")
    assert [item.session_date for item in inputs] == [day1, day2]
    assert inputs[0].vix_close == Decimal("15.5")
    assert inputs[0].wti_close == Decimal("80.0")
    assert inputs[1].vix_close == Decimal("31.0")
    assert inputs[1].wti_close is None


def test_save_is_idempotent(tmp_path) -> None:
    database = initialize_database(tmp_path / "trade_flow.db")
    repository = MarketContextRepository(database)
    fetched_at = datetime(2026, 7, 21, tzinfo=UTC)
    closes = [(date(2026, 7, 20), Decimal("15.5"))]

    repository.save(indicator=VIX, closes=closes, source="fixture", fetched_at=fetched_at)
    repository.save(
        indicator=VIX,
        closes=[(date(2026, 7, 20), Decimal("16.0"))],
        source="fixture",
        fetched_at=fetched_at,
    )
    inputs = repository.load_regime_inputs(
        start=date(2026, 7, 20), end=date(2026, 7, 20), source="fixture"
    )
    assert len(inputs) == 1
    assert inputs[0].vix_close == Decimal("16.0")
