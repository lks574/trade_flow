from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import TYPE_CHECKING, Protocol

from trade_flow.data.market import DailyBar

if TYPE_CHECKING:
    from trade_flow.risk import RegimeInput


class MarketCalendar(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def version(self) -> str: ...

    def sessions(self, start: date, end: date) -> Sequence[date]: ...


class MarketDataProvider(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def version(self) -> str: ...

    def daily_bars(self, symbol: str, start: date, end: date) -> Sequence[DailyBar]: ...

    def regime_inputs(self, start: date, end: date) -> Sequence[RegimeInput]: ...
