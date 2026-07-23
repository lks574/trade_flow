from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

# 서브모듈에서 직접 import: 패키지(trade_flow.risk)를 거치면 risk/__init__ -> risk.policy
# -> trade_flow.strategy -> ... -> db -> market_context 로 되돌아오는 순환에서 RegimeInput이
# 아직 바인딩되지 않아 ImportError가 난다(test_regime 단독 수집 등). regime 서브모듈은
# domain.config만 의존하므로 순환이 없다.
from trade_flow.risk.regime import RegimeInput

VIX = "VIX"
WTI = "WTI"


def _text(value: Decimal) -> str:
    return format(value, "f")


class MarketContextRepository:
    """Stores regime indicator closes (VIX, WTI). Close-only by design: RegimeInput
    needs only closes, so OHLCV would be dead columns."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)

    def save(
        self,
        *,
        indicator: str,
        closes: Sequence[tuple[date, Decimal]],
        source: str,
        fetched_at: datetime,
    ) -> int:
        if fetched_at.tzinfo is None or fetched_at.utcoffset() is None:
            raise ValueError("fetched_at must be timezone-aware")
        rows = [
            (indicator, session.isoformat(), _text(close), source, fetched_at.isoformat())
            for session, close in closes
        ]
        with sqlite3.connect(self.database_path) as connection:
            before = connection.total_changes
            connection.executemany(
                """
                INSERT INTO market_context (indicator, session_date, close, source, fetched_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(indicator, session_date, source) DO UPDATE SET
                    close = excluded.close,
                    fetched_at = excluded.fetched_at
                """,
                rows,
            )
            changed = connection.total_changes - before
            connection.commit()
        return changed

    def load_regime_inputs(
        self, *, start: date, end: date, source: str | None = None
    ) -> tuple[RegimeInput, ...]:
        query = """
            SELECT indicator, session_date, close
            FROM market_context
            WHERE indicator IN (?, ?) AND session_date BETWEEN ? AND ?
        """
        parameters: list[object] = [VIX, WTI, start.isoformat(), end.isoformat()]
        if source is not None:
            query += " AND source = ?"
            parameters.append(source)
        with sqlite3.connect(self.database_path) as connection:
            rows = connection.execute(query, parameters).fetchall()
        vix: dict[date, Decimal] = {}
        wti: dict[date, Decimal] = {}
        for indicator, session_text, close_text in rows:
            session = date.fromisoformat(session_text)
            (vix if indicator == VIX else wti)[session] = Decimal(close_text)
        return tuple(
            RegimeInput(session, vix.get(session), wti.get(session))
            for session in sorted(vix.keys() | wti.keys())
        )
