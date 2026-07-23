from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from trade_flow.research import PriceTarget


@dataclass(frozen=True)
class StoredPriceTarget:
    as_of_date: date
    symbol: str
    horizon_sessions: int
    basis_close: Decimal
    expected: Decimal
    low_68: Decimal
    high_68: Decimal
    stop: Decimal
    drift_daily: float
    sigma_daily: float
    sentiment_score: float | None
    sentiment_articles: int | None
    macro_flags: tuple[str, ...]
    vix: float | None
    wti_momentum_21d: float | None


class PriceTargetRepository:
    """목표가 예보 영속화. 같은 (기준일, 종목, 기간) 재실행은 통째 교체(멱등)."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)

    def record(
        self,
        targets: list[PriceTarget],
        *,
        sentiment_articles: dict[str, int] | None = None,
        macro_flags: tuple[str, ...] = (),
    ) -> None:
        now = datetime.now(UTC).isoformat()
        articles = sentiment_articles or {}
        with sqlite3.connect(self.database_path) as connection:
            connection.executemany(
                """
                INSERT INTO price_targets (
                    as_of_date, symbol, horizon_sessions, basis_close, expected,
                    low_68, high_68, stop, drift_daily, sigma_daily,
                    sentiment_score, sentiment_articles, macro_flags,
                    vix, wti_momentum_21d, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (as_of_date, symbol, horizon_sessions) DO UPDATE SET
                    basis_close = excluded.basis_close,
                    expected = excluded.expected,
                    low_68 = excluded.low_68,
                    high_68 = excluded.high_68,
                    stop = excluded.stop,
                    drift_daily = excluded.drift_daily,
                    sigma_daily = excluded.sigma_daily,
                    sentiment_score = excluded.sentiment_score,
                    sentiment_articles = excluded.sentiment_articles,
                    macro_flags = excluded.macro_flags,
                    vix = excluded.vix,
                    wti_momentum_21d = excluded.wti_momentum_21d,
                    created_at = excluded.created_at
                """,
                [
                    (
                        target.as_of.isoformat(),
                        target.symbol,
                        target.horizon_sessions,
                        format(target.basis_close, "f"),
                        format(target.expected, "f"),
                        format(target.low_68, "f"),
                        format(target.high_68, "f"),
                        format(target.stop, "f"),
                        target.drift_daily,
                        target.sigma_daily,
                        target.sentiment_score,
                        articles.get(target.symbol),
                        ",".join(macro_flags) if macro_flags else None,
                        target.vix,
                        target.wti_momentum_21d,
                        now,
                    )
                    for target in targets
                ],
            )

    def all(self) -> list[StoredPriceTarget]:
        with sqlite3.connect(self.database_path) as connection:
            rows = connection.execute(
                """
                SELECT as_of_date, symbol, horizon_sessions, basis_close, expected,
                       low_68, high_68, stop, drift_daily, sigma_daily,
                       sentiment_score, sentiment_articles, macro_flags,
                       vix, wti_momentum_21d
                FROM price_targets ORDER BY as_of_date, symbol, horizon_sessions
                """
            ).fetchall()
        return [
            StoredPriceTarget(
                as_of_date=date.fromisoformat(row[0]),
                symbol=row[1],
                horizon_sessions=row[2],
                basis_close=Decimal(row[3]),
                expected=Decimal(row[4]),
                low_68=Decimal(row[5]),
                high_68=Decimal(row[6]),
                stop=Decimal(row[7]),
                drift_daily=row[8],
                sigma_daily=row[9],
                sentiment_score=row[10],
                sentiment_articles=row[11],
                macro_flags=tuple(row[12].split(",")) if row[12] else (),
                vix=row[13],
                wti_momentum_21d=row[14],
            )
            for row in rows
        ]
