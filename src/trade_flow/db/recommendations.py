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
    quality_pass: bool | None = None  # 게이트 판정(모멘텀 리스트에도 라벨로 기록)
    quality_fail: str | None = None  # 탈락 사유(쉼표 구분)


@dataclass(frozen=True)
class StoredRecommendation:
    as_of_date: date
    variant: str  # 'momentum' | 'quality_gated'
    rank: int
    symbol: str
    total_score: Decimal
    momentum_return: Decimal
    traded: bool
    quality_pass: bool | None
    quality_fail: str | None


class RecommendationRepository:
    """추천 리포트 영속화(사후 추적용).

    variant별로 기준일 집합을 통째로 교체한다(재실행 멱등). 'momentum'과
    'quality_gated' 두 군의 사후 성과는 track_recommendations.py가 대조 채점한다.
    """

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)

    def record(
        self, as_of: date, entries: list[RecommendationEntry], *, variant: str = "momentum"
    ) -> None:
        now = datetime.now(UTC).isoformat()
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                "DELETE FROM recommendations WHERE as_of_date = ? AND variant = ?",
                (as_of.isoformat(), variant),
            )
            connection.executemany(
                """
                INSERT INTO recommendations (
                    as_of_date, variant, rank, symbol, total_score, momentum_return,
                    traded, quality_pass, quality_fail, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        as_of.isoformat(),
                        variant,
                        entry.rank,
                        entry.symbol,
                        format(entry.total_score, "f"),
                        format(entry.momentum_return, "f"),
                        int(entry.traded),
                        None if entry.quality_pass is None else int(entry.quality_pass),
                        entry.quality_fail,
                        now,
                    )
                    for entry in entries
                ],
            )

    def all(self) -> list[StoredRecommendation]:
        with sqlite3.connect(self.database_path) as connection:
            rows = connection.execute(
                """
                SELECT as_of_date, variant, rank, symbol, total_score, momentum_return,
                       traded, quality_pass, quality_fail
                FROM recommendations ORDER BY as_of_date, variant, rank
                """
            ).fetchall()
        return [
            StoredRecommendation(
                as_of_date=date.fromisoformat(row[0]),
                variant=row[1],
                rank=row[2],
                symbol=row[3],
                total_score=Decimal(row[4]),
                momentum_return=Decimal(row[5]),
                traded=bool(row[6]),
                quality_pass=None if row[7] is None else bool(row[7]),
                quality_fail=row[8],
            )
            for row in rows
        ]
