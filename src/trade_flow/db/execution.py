from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path

from trade_flow.execution.models import BrokerOrder, OrderIntent


class RunRepository:
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)

    def start(
        self,
        *,
        run_id: str,
        environment: str,
        account_hash: str,
        trading_date: date,
        signal_date: date,
        data_hash: str,
        config_hash: str,
        universe_hash: str,
    ) -> None:
        with sqlite3.connect(self.database_path) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute(
                """
                INSERT INTO runs (
                    run_id, environment, account_hash, trading_date, signal_date,
                    data_hash, config_hash, universe_hash, status, started_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'started', ?)
                """,
                (
                    run_id,
                    environment,
                    account_hash,
                    trading_date.isoformat(),
                    signal_date.isoformat(),
                    data_hash,
                    config_hash,
                    universe_hash,
                    datetime.now(UTC).isoformat(),
                ),
            )


class OrderRepository:
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)

    def reserve(self, run_id: str, intent: OrderIntent) -> bool:
        with sqlite3.connect(self.database_path) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO orders (
                    intent_id, run_id, symbol, side, requested_qty, limit_price, status
                ) VALUES (?, ?, ?, ?, ?, ?, 'planned')
                """,
                (
                    intent.intent_id,
                    run_id,
                    intent.symbol,
                    intent.side,
                    intent.quantity,
                    format(intent.limit_price, "f"),
                ),
            )
            return cursor.rowcount == 1

    def status(self, intent_id: str) -> str | None:
        with sqlite3.connect(self.database_path) as connection:
            row = connection.execute(
                "SELECT status FROM orders WHERE intent_id = ?", (intent_id,)
            ).fetchone()
        return row[0] if row else None

    def update(self, intent_id: str, order: BrokerOrder) -> None:
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                """
                UPDATE orders
                SET broker_order_id = ?, status = ?, error_code = NULL
                WHERE intent_id = ?
                """,
                (order.broker_order_id, order.status, intent_id),
            )

    def mark_unknown(self, intent_id: str, error_code: str) -> None:
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                "UPDATE orders SET status = 'unknown', error_code = ? WHERE intent_id = ?",
                (error_code, intent_id),
            )
