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


def test_variants_are_independent(tmp_path) -> None:
    db = initialize_database(tmp_path / "ops.db")
    repo = RecommendationRepository(db)
    # 같은 기준일·같은 종목이 두 리스트에 공존할 수 있다(SOLV처럼).
    repo.record(date(2026, 7, 22), [_entry(1, "SOLV"), _entry(2, "MPC")])
    repo.record(date(2026, 7, 22), [_entry(1, "SOLV")], variant="quality_gated")
    stored = repo.all()
    assert [(r.variant, r.symbol) for r in stored] == [
        ("momentum", "SOLV"),
        ("momentum", "MPC"),
        ("quality_gated", "SOLV"),
    ]
    # variant별 교체는 서로를 건드리지 않는다.
    repo.record(date(2026, 7, 22), [_entry(1, "PRU")], variant="quality_gated")
    stored = repo.all()
    assert [(r.variant, r.symbol) for r in stored] == [
        ("momentum", "SOLV"),
        ("momentum", "MPC"),
        ("quality_gated", "PRU"),
    ]


def test_v5_table_migrates_to_v6_with_variant(tmp_path) -> None:
    import sqlite3

    # v5 스키마(variant 없음)로 기존 데이터 생성
    db = tmp_path / "ops.db"
    with sqlite3.connect(db) as connection:
        connection.executescript(
            """
            CREATE TABLE recommendations (
                as_of_date TEXT NOT NULL,
                rank INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                total_score TEXT NOT NULL,
                momentum_return TEXT NOT NULL,
                traded INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (as_of_date, symbol)
            );
            INSERT INTO recommendations VALUES
                ('2026-07-15', 1, 'MPC', '0.83', '0.40', 1, '2026-07-15T00:00:00Z');
            """
        )
    initialize_database(db)  # v6 마이그레이션 수행
    stored = RecommendationRepository(db).all()
    assert len(stored) == 1
    assert stored[0].variant == "momentum" and stored[0].symbol == "MPC"
    assert stored[0].quality_pass is None


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
