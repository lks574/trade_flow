from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from pathlib import Path

from trade_flow.sentiment import SentimentObservation


class SentimentRepository:
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)

    def save(self, observations: Sequence[SentimentObservation]) -> int:
        rows = [
            (
                item.symbol,
                item.session_date.isoformat(),
                format(item.score, "f") if item.score is not None else None,
                format(item.relevance, "f") if item.relevance is not None else None,
                item.article_count,
                item.source,
                item.missing_reason,
            )
            for item in observations
        ]
        with sqlite3.connect(self.database_path) as connection:
            before = connection.total_changes
            connection.executemany(
                """
                INSERT INTO sentiment (
                    symbol, session_date, score, relevance,
                    article_count, source, missing_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, session_date, source) DO UPDATE SET
                    score = excluded.score,
                    relevance = excluded.relevance,
                    article_count = excluded.article_count,
                    missing_reason = excluded.missing_reason
                """,
                rows,
            )
            changed = connection.total_changes - before
            connection.commit()
        return changed

    def load(self, *, start: date, end: date) -> tuple[SentimentObservation, ...]:
        with sqlite3.connect(self.database_path) as connection:
            rows = connection.execute(
                """
                SELECT symbol, session_date, score, relevance,
                       article_count, source, missing_reason
                FROM sentiment
                WHERE session_date BETWEEN ? AND ?
                ORDER BY session_date, symbol, source
                """,
                (start.isoformat(), end.isoformat()),
            ).fetchall()
        return tuple(
            SentimentObservation(
                symbol=row[0],
                session_date=date.fromisoformat(row[1]),
                score=Decimal(row[2]) if row[2] is not None else None,
                relevance=Decimal(row[3]) if row[3] is not None else None,
                article_count=row[4],
                source=row[5],
                missing_reason=row[6],
            )
            for row in rows
        )
