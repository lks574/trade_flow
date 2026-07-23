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


def test_price_target_repository_roundtrip(tmp_path) -> None:
    from trade_flow.db import PriceTargetRepository
    from trade_flow.research import PriceTarget

    db = initialize_database(tmp_path / "ops.db")
    repo = PriceTargetRepository(db)
    target = PriceTarget(
        symbol="MPC", as_of=date(2026, 7, 22), horizon_sessions=5,
        basis_close=Decimal("185.20"), expected=Decimal("187.10"),
        low_68=Decimal("178.00"), high_68=Decimal("196.00"), stop=Decimal("176.90"),
        drift_daily=0.002, sigma_daily=0.018, sentiment_score=0.25,
        vix=16.6, wti_momentum_21d=0.08,
    )
    repo.record([target], sentiment_articles={"MPC": 10}, macro_flags=("이란", "전쟁"))
    # 재실행 upsert 멱등.
    repo.record([target], sentiment_articles={"MPC": 10}, macro_flags=("이란", "전쟁"))

    stored = repo.all()
    assert len(stored) == 1
    row = stored[0]
    assert row.symbol == "MPC" and row.horizon_sessions == 5
    assert row.expected == Decimal("187.10") and row.stop == Decimal("176.90")
    assert row.sentiment_score == 0.25 and row.sentiment_articles == 10
    assert row.macro_flags == ("이란", "전쟁")
    assert row.vix == 16.6
