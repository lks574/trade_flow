from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path


@dataclass(frozen=True)
class RecommendationEntry:
    rank: int
    symbol: str
    total_score: Decimal
    momentum_return: Decimal
    traded: bool


@dataclass(frozen=True)
class StoredRecommendation:
    as_of_date: date
    rank: int
    symbol: str
    total_score: Decimal
    momentum_return: Decimal
    traded: bool


class RecommendationRepository:
    """추천 리포트 영속화(사후 추적용).

    recommend.py가 기준일별 상위 N을 저장하고, track_recommendations.py가
    +1/+3/+5 거래일 수익률을 계산해 적중 여부를 문서로 남긴다. 같은 기준일
    재실행은 upsert로 멱등이다.
    """

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)

    def record(self, as_of: date, entries: list[RecommendationEntry]) -> None:
        """기준일의 추천 집합을 통째로 교체한다(재실행 멱등).

        upsert만 하면 재실행에서 순위 밖으로 밀린 종목의 잔재 행이 남으므로,
        같은 기준일을 지우고 다시 쓴다(단일 트랜잭션).
        """
        now = datetime.now(UTC).isoformat()
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                "DELETE FROM recommendations WHERE as_of_date = ?", (as_of.isoformat(),)
            )
            connection.executemany(
                """
                INSERT INTO recommendations (
                    as_of_date, rank, symbol, total_score, momentum_return, traded, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        as_of.isoformat(),
                        entry.rank,
                        entry.symbol,
                        format(entry.total_score, "f"),
                        format(entry.momentum_return, "f"),
                        int(entry.traded),
                        now,
                    )
                    for entry in entries
                ],
            )

    def all(self) -> list[StoredRecommendation]:
        with sqlite3.connect(self.database_path) as connection:
            rows = connection.execute(
                """
                SELECT as_of_date, rank, symbol, total_score, momentum_return, traded
                FROM recommendations ORDER BY as_of_date, rank
                """
            ).fetchall()
        return [
            StoredRecommendation(
                as_of_date=date.fromisoformat(row[0]),
                rank=row[1],
                symbol=row[2],
                total_score=Decimal(row[3]),
                momentum_return=Decimal(row[4]),
                traded=bool(row[5]),
            )
            for row in rows
        ]
