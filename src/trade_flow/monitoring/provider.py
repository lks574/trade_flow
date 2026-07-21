from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from trade_flow.monitoring.models import MarketEvent


class MarketEventProvider(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def version(self) -> str: ...

    def events(
        self,
        *,
        symbols: Sequence[str],
        start: datetime,
        end: datetime,
    ) -> Sequence[MarketEvent]: ...
