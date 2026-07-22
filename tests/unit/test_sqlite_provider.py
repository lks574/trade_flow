from datetime import UTC, date, datetime
from decimal import Decimal

from trade_flow.data import DailyBar
from trade_flow.data.sqlite_provider import SqliteMarketCalendar, SqliteMarketDataProvider
from trade_flow.db import MarketContextRepository, PriceRepository, initialize_database


def _bar(symbol: str, session: date, *, source: str = "yfinance") -> DailyBar:
    return DailyBar(
        symbol=symbol,
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
        source=source,
        fetched_at=datetime(2026, 7, 21, tzinfo=UTC),
    )


def _seed(tmp_path):
    database = initialize_database(tmp_path / "trade_flow.db")
    prices = PriceRepository(database)
    prices.save_bars(
        [
            _bar("AAPL", date(2026, 7, 17)),
            _bar("AAPL", date(2026, 7, 20)),
            _bar("MSFT", date(2026, 7, 20)),
        ]
    )
    context = MarketContextRepository(database)
    context.save(
        indicator="VIX",
        closes=[(date(2026, 7, 17), Decimal("18.0")), (date(2026, 7, 20), Decimal("21.0"))],
        source="yfinance",
        fetched_at=datetime(2026, 7, 21, tzinfo=UTC),
    )
    context.save(
        indicator="WTI",
        closes=[(date(2026, 7, 17), Decimal("70.0")), (date(2026, 7, 20), Decimal("72.0"))],
        source="yfinance",
        fetched_at=datetime(2026, 7, 21, tzinfo=UTC),
    )
    return database


def test_provider_daily_bars_reads_single_symbol(tmp_path) -> None:
    database = _seed(tmp_path)
    provider = SqliteMarketDataProvider(database)

    bars = provider.daily_bars("AAPL", date(2026, 7, 1), date(2026, 7, 31))

    assert [bar.session_date for bar in bars] == [date(2026, 7, 17), date(2026, 7, 20)]
    assert all(bar.symbol == "AAPL" for bar in bars)


def test_provider_regime_inputs_pairs_vix_and_wti(tmp_path) -> None:
    database = _seed(tmp_path)
    provider = SqliteMarketDataProvider(database)

    inputs = provider.regime_inputs(date(2026, 7, 1), date(2026, 7, 31))

    assert [item.session_date for item in inputs] == [date(2026, 7, 17), date(2026, 7, 20)]
    assert inputs[-1].vix_close == Decimal("21.0")
    assert inputs[-1].wti_close == Decimal("72.0")


def test_calendar_returns_union_of_price_sessions(tmp_path) -> None:
    database = _seed(tmp_path)
    calendar = SqliteMarketCalendar(database)

    # 7-17 traded only AAPL, 7-20 traded both -> both are still sessions.
    sessions = calendar.sessions(date(2026, 7, 1), date(2026, 7, 31))

    assert sessions == (date(2026, 7, 17), date(2026, 7, 20))


def test_calendar_respects_range_bounds(tmp_path) -> None:
    database = _seed(tmp_path)
    calendar = SqliteMarketCalendar(database)

    assert calendar.sessions(date(2026, 7, 18), date(2026, 7, 31)) == (date(2026, 7, 20),)


def test_source_filter_excludes_other_sources(tmp_path) -> None:
    database = initialize_database(tmp_path / "trade_flow.db")
    PriceRepository(database).save_bars(
        [
            _bar("AAPL", date(2026, 7, 20), source="yfinance"),
            _bar("AAPL", date(2026, 7, 20), source="other"),
        ]
    )
    provider = SqliteMarketDataProvider(database, source="yfinance")

    bars = provider.daily_bars("AAPL", date(2026, 7, 1), date(2026, 7, 31))

    assert len(bars) == 1
    assert bars[0].source == "yfinance"
