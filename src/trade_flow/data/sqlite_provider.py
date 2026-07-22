"""Concrete SQLite-backed market data provider and trading calendar.

This bridges the ``trade_flow.db`` persistence layer up to the
``trade_flow.data`` contracts, so it depends on ``db`` (which in turn depends
on ``data``). It is intentionally NOT re-exported from ``trade_flow.data``'s
package ``__init__``: doing so would import ``db`` during ``data`` package
initialization and create a circular import. Import it from this module
directly: ``from trade_flow.data.sqlite_provider import SqliteMarketDataProvider``.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from trade_flow.data.market import DailyBar
from trade_flow.db.market_context import MarketContextRepository
from trade_flow.db.prices import PriceRepository
from trade_flow.risk import RegimeInput


class SqliteMarketCalendar:
    """Trading calendar derived from the session dates present in ``prices``.

    The operational dataset ships no exchange-calendar table and no index bar
    (SPY is absent), so the observed union of price session dates is the
    authoritative session list. This matches how the quality report validates
    recent-session coverage: a session exists iff at least one symbol traded.
    """

    def __init__(self, database_path: str | Path, *, source: str | None = None) -> None:
        self.database_path = Path(database_path)
        self._source = source

    @property
    def name(self) -> str:
        return "sqlite_prices_sessions"

    @property
    def version(self) -> str:
        return "v1"

    def sessions(self, start: date, end: date) -> Sequence[date]:
        query = "SELECT DISTINCT session_date FROM prices WHERE session_date BETWEEN ? AND ?"
        parameters: list[object] = [start.isoformat(), end.isoformat()]
        if self._source is not None:
            query += " AND source = ?"
            parameters.append(self._source)
        query += " ORDER BY session_date"
        with sqlite3.connect(self.database_path) as connection:
            rows = connection.execute(query, parameters).fetchall()
        return tuple(date.fromisoformat(row[0]) for row in rows)


class SqliteMarketDataProvider:
    """Concrete ``MarketDataProvider`` backed by the operational SQLite DB.

    Composes the existing ``PriceRepository`` (split-adjusted daily bars with
    dividends kept separate) and ``MarketContextRepository`` (VIX/WTI regime
    closes). ``source`` filters to a single provider when the DB holds more than
    one; the default (``None``) returns every stored source, which is correct
    while the dataset carries a single collection source.
    """

    def __init__(self, database_path: str | Path, *, source: str | None = None) -> None:
        self.database_path = Path(database_path)
        self._prices = PriceRepository(database_path)
        self._context = MarketContextRepository(database_path)
        self._source = source

    @property
    def name(self) -> str:
        return "sqlite_trade_flow"

    @property
    def version(self) -> str:
        return "v1"

    def daily_bars(self, symbol: str, start: date, end: date) -> Sequence[DailyBar]:
        return self._prices.load_bars(
            symbols=[symbol], start=start, end=end, source=self._source
        )

    def regime_inputs(self, start: date, end: date) -> Sequence[RegimeInput]:
        return self._context.load_regime_inputs(start=start, end=end, source=self._source)
