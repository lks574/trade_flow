from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from trade_flow.execution import PositionSnapshot


class FillRepository:
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)

    def save(
        self,
        *,
        broker_fill_id: str,
        broker_order_id: str,
        quantity: int,
        price: Decimal,
        fee: Decimal,
        filled_at: datetime,
    ) -> bool:
        if quantity <= 0 or price <= 0 or fee < 0:
            raise ValueError("fill quantity, price, or fee is invalid")
        if filled_at.tzinfo is None or filled_at.utcoffset() is None:
            raise ValueError("fill time must be timezone-aware")
        with sqlite3.connect(self.database_path) as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO fills (
                    broker_fill_id, broker_order_id, quantity, price, fee, filled_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    broker_fill_id,
                    broker_order_id,
                    quantity,
                    format(price, "f"),
                    format(fee, "f"),
                    filled_at.isoformat(),
                ),
            )
            return cursor.rowcount == 1


class SnapshotRepository:
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)

    def save(
        self,
        *,
        run_id: str,
        captured_at: datetime,
        nav: Decimal,
        cash: Decimal,
        positions: Mapping[str, PositionSnapshot],
        source: str,
    ) -> bool:
        if captured_at.tzinfo is None or captured_at.utcoffset() is None:
            raise ValueError("snapshot time must be timezone-aware")
        payload = json.dumps(
            {
                symbol: {
                    "quantity": position.quantity,
                    "average_price": format(position.average_price, "f"),
                    "market_price": format(position.market_price, "f"),
                }
                for symbol, position in sorted(positions.items())
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        with sqlite3.connect(self.database_path) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO snapshots (
                    run_id, captured_at, nav, cash, positions_json, source
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    captured_at.isoformat(),
                    format(nav, "f"),
                    format(cash, "f"),
                    payload,
                    source,
                ),
            )
            return cursor.rowcount == 1
