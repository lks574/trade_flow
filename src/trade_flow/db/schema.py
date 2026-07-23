from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 6

_SCHEMA = """
CREATE TABLE IF NOT EXISTS prices (
    symbol TEXT NOT NULL,
    session_date TEXT NOT NULL,
    open TEXT NOT NULL,
    high TEXT NOT NULL,
    low TEXT NOT NULL,
    close TEXT NOT NULL,
    split_adjusted_open TEXT NOT NULL,
    split_adjusted_high TEXT NOT NULL,
    split_adjusted_low TEXT NOT NULL,
    split_adjusted_close TEXT NOT NULL,
    volume INTEGER NOT NULL CHECK (volume >= 0),
    cash_dividend TEXT NOT NULL DEFAULT '0',
    source TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (symbol, session_date, source)
);

CREATE TABLE IF NOT EXISTS market_context (
    indicator TEXT NOT NULL,
    session_date TEXT NOT NULL,
    close TEXT NOT NULL,
    source TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (indicator, session_date, source)
);

CREATE TABLE IF NOT EXISTS sentiment (
    symbol TEXT NOT NULL,
    session_date TEXT NOT NULL,
    score TEXT,
    relevance TEXT,
    article_count INTEGER NOT NULL DEFAULT 0 CHECK (article_count >= 0),
    source TEXT NOT NULL,
    missing_reason TEXT,
    PRIMARY KEY (symbol, session_date, source)
);

CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    environment TEXT NOT NULL,
    account_hash TEXT,
    trading_date TEXT,
    signal_date TEXT,
    data_hash TEXT NOT NULL,
    config_hash TEXT NOT NULL,
    universe_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    notification_status TEXT,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    exit_code INTEGER
);

CREATE TABLE IF NOT EXISTS orders (
    intent_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    broker_order_id TEXT,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
    requested_qty INTEGER NOT NULL CHECK (requested_qty > 0),
    limit_price TEXT NOT NULL,
    status TEXT NOT NULL,
    error_code TEXT
);

CREATE TABLE IF NOT EXISTS order_events (
    event_id INTEGER PRIMARY KEY,
    intent_id TEXT NOT NULL REFERENCES orders(intent_id),
    status TEXT NOT NULL,
    broker_order_id TEXT,
    error_code TEXT,
    recorded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fills (
    broker_fill_id TEXT PRIMARY KEY,
    broker_order_id TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    price TEXT NOT NULL,
    fee TEXT NOT NULL DEFAULT '0',
    filled_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS snapshots (
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    captured_at TEXT NOT NULL,
    nav TEXT NOT NULL,
    cash TEXT NOT NULL,
    positions_json TEXT NOT NULL,
    source TEXT NOT NULL,
    PRIMARY KEY (run_id, captured_at, source)
);

-- 추천 리포트 영속화(사후 추적용). as_of_date는 신호 기준일(데이터 최종 세션).
-- variant: 'momentum'(순수 모멘텀) | 'quality_gated'(퀄리티 게이트+섹터상한) —
-- 두 군의 사후 성과를 track_recommendations.py가 대조 채점한다.
CREATE TABLE IF NOT EXISTS recommendations (
    as_of_date TEXT NOT NULL,
    variant TEXT NOT NULL DEFAULT 'momentum',
    rank INTEGER NOT NULL CHECK (rank > 0),
    symbol TEXT NOT NULL,
    total_score TEXT NOT NULL,
    momentum_return TEXT NOT NULL,
    traded INTEGER NOT NULL CHECK (traded IN (0, 1)),
    quality_pass INTEGER,
    quality_fail TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (as_of_date, variant, symbol)
);

-- 목표가 예보 영속화(캘리브레이션 채점용). 구간이 명목 68%를 지키는지 사후 검증.
CREATE TABLE IF NOT EXISTS price_targets (
    as_of_date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    horizon_sessions INTEGER NOT NULL CHECK (horizon_sessions > 0),
    basis_close TEXT NOT NULL,
    expected TEXT NOT NULL,
    low_68 TEXT NOT NULL,
    high_68 TEXT NOT NULL,
    stop TEXT NOT NULL,
    drift_daily REAL NOT NULL,
    sigma_daily REAL NOT NULL,
    sentiment_score REAL,
    sentiment_articles INTEGER,
    macro_flags TEXT,
    vix REAL,
    wti_momentum_21d REAL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (as_of_date, symbol, horizon_sessions)
);
"""


def _migrate_recommendations_v6(connection: sqlite3.Connection) -> None:
    """v5 recommendations(variant 없음)를 v6 스키마로 재구축(기존 행은 momentum)."""
    columns = [row[1] for row in connection.execute("PRAGMA table_info(recommendations)")]
    if not columns or "variant" in columns:
        return
    connection.executescript(
        """
        ALTER TABLE recommendations RENAME TO recommendations_v5;
        CREATE TABLE recommendations (
            as_of_date TEXT NOT NULL,
            variant TEXT NOT NULL DEFAULT 'momentum',
            rank INTEGER NOT NULL CHECK (rank > 0),
            symbol TEXT NOT NULL,
            total_score TEXT NOT NULL,
            momentum_return TEXT NOT NULL,
            traded INTEGER NOT NULL CHECK (traded IN (0, 1)),
            quality_pass INTEGER,
            quality_fail TEXT,
            created_at TEXT NOT NULL,
            PRIMARY KEY (as_of_date, variant, symbol)
        );
        INSERT INTO recommendations (
            as_of_date, variant, rank, symbol, total_score, momentum_return,
            traded, created_at
        )
        SELECT as_of_date, 'momentum', rank, symbol, total_score, momentum_return,
               traded, created_at
        FROM recommendations_v5;
        DROP TABLE recommendations_v5;
        """
    )


def initialize_database(path: str | Path) -> Path:
    database_path = Path(path)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        _migrate_recommendations_v6(connection)
        connection.executescript(_SCHEMA)
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        connection.commit()
    return database_path
