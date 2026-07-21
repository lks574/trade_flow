from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from trade_flow.data.market import DailyBar, MarketDataSnapshot


def _text(value: Decimal) -> str:
    return format(value, "f")


class PriceRepository:
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)

    def save_snapshot(self, snapshot: MarketDataSnapshot) -> int:
        snapshot.quality_report.require_valid()
        rows = [
            (
                bar.symbol,
                bar.session_date.isoformat(),
                _text(bar.open),
                _text(bar.high),
                _text(bar.low),
                _text(bar.close),
                _text(bar.split_adjusted_open),
                _text(bar.split_adjusted_high),
                _text(bar.split_adjusted_low),
                _text(bar.split_adjusted_close),
                bar.volume,
                _text(bar.cash_dividend),
                bar.source,
                bar.fetched_at.isoformat(),
            )
            for bar in snapshot.prices
        ]
        with sqlite3.connect(self.database_path) as connection:
            before = connection.total_changes
            connection.executemany(
                """
                INSERT INTO prices (
                    symbol, session_date, open, high, low, close,
                    split_adjusted_open, split_adjusted_high,
                    split_adjusted_low, split_adjusted_close,
                    volume, cash_dividend, source, fetched_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, session_date, source) DO UPDATE SET
                    open = excluded.open,
                    high = excluded.high,
                    low = excluded.low,
                    close = excluded.close,
                    split_adjusted_open = excluded.split_adjusted_open,
                    split_adjusted_high = excluded.split_adjusted_high,
                    split_adjusted_low = excluded.split_adjusted_low,
                    split_adjusted_close = excluded.split_adjusted_close,
                    volume = excluded.volume,
                    cash_dividend = excluded.cash_dividend,
                    fetched_at = excluded.fetched_at
                """,
                rows,
            )
            changed = connection.total_changes - before
            connection.commit()
        return changed

    def load_bars(
        self,
        *,
        symbols: Sequence[str],
        start: date,
        end: date,
        source: str | None = None,
    ) -> tuple[DailyBar, ...]:
        if not symbols:
            return ()
        placeholders = ",".join("?" for _ in symbols)
        query = f"""
            SELECT symbol, session_date, open, high, low, close,
                   split_adjusted_open, split_adjusted_high,
                   split_adjusted_low, split_adjusted_close,
                   volume, cash_dividend, source, fetched_at
            FROM prices
            WHERE symbol IN ({placeholders})
              AND session_date BETWEEN ? AND ?
        """
        parameters: list[object] = [*symbols, start.isoformat(), end.isoformat()]
        if source is not None:
            query += " AND source = ?"
            parameters.append(source)
        query += " ORDER BY symbol, session_date, source"
        with sqlite3.connect(self.database_path) as connection:
            rows = connection.execute(query, parameters).fetchall()
        return tuple(
            DailyBar(
                symbol=row[0],
                session_date=date.fromisoformat(row[1]),
                open=Decimal(row[2]),
                high=Decimal(row[3]),
                low=Decimal(row[4]),
                close=Decimal(row[5]),
                split_adjusted_open=Decimal(row[6]),
                split_adjusted_high=Decimal(row[7]),
                split_adjusted_low=Decimal(row[8]),
                split_adjusted_close=Decimal(row[9]),
                volume=row[10],
                cash_dividend=Decimal(row[11]),
                source=row[12],
                fetched_at=datetime.fromisoformat(row[13]),
            )
            for row in rows
        )
