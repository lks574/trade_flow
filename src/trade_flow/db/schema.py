from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1

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
"""


def initialize_database(path: str | Path) -> Path:
    database_path = Path(path)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(_SCHEMA)
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        connection.commit()
    return database_path
