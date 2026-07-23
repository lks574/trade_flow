from datetime import date
from decimal import Decimal

from trade_flow.db import (
    RecommendationEntry,
    RecommendationRepository,
    initialize_database,
)


def _entry(rank: int, symbol: str, *, traded: bool = False) -> RecommendationEntry:
    return RecommendationEntry(
        rank=rank,
        symbol=symbol,
        total_score=Decimal("0.85"),
        momentum_return=Decimal("0.31"),
        traded=traded,
    )


def test_record_and_read_back(tmp_path) -> None:
    db = initialize_database(tmp_path / "ops.db")
    repo = RecommendationRepository(db)
    repo.record(date(2026, 7, 22), [_entry(1, "MPC", traded=True), _entry(2, "BBY")])

    stored = repo.all()
    assert [(r.rank, r.symbol, r.traded) for r in stored] == [
        (1, "MPC", True),
        (2, "BBY", False),
    ]
    assert stored[0].as_of_date == date(2026, 7, 22)
    assert stored[0].total_score == Decimal("0.85")


def test_record_same_date_replaces_whole_set(tmp_path) -> None:
    db = initialize_database(tmp_path / "ops.db")
    repo = RecommendationRepository(db)
    repo.record(date(2026, 7, 22), [_entry(1, "MPC"), _entry(2, "KLAC")])
    # 재실행: 기준일 집합 통째 교체 — 순위 밖으로 밀린 KLAC 잔재가 남으면 안 된다.
    repo.record(date(2026, 7, 22), [_entry(1, "BBY", traded=True)])

    stored = repo.all()
    assert [(r.rank, r.symbol) for r in stored] == [(1, "BBY")]
    assert stored[0].traded


def test_dates_are_kept_separate(tmp_path) -> None:
    db = initialize_database(tmp_path / "ops.db")
    repo = RecommendationRepository(db)
    repo.record(date(2026, 7, 15), [_entry(1, "MPC")])
    repo.record(date(2026, 7, 22), [_entry(1, "MPC")])
    assert len(repo.all()) == 2
