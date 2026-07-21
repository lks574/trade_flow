import sqlite3
from datetime import UTC, date, datetime
from decimal import Decimal
from types import MappingProxyType

from trade_flow.db import (
    FillRepository,
    RunRepository,
    SnapshotRepository,
    initialize_database,
)
from trade_flow.execution import PositionSnapshot


def test_fill_and_snapshot_writers_are_idempotent(tmp_path) -> None:
    database = initialize_database(tmp_path / "trade_flow.db")
    RunRepository(database).start(
        run_id="run-1",
        environment="paper",
        account_hash="account",
        trading_date=date(2026, 1, 2),
        signal_date=date(2026, 1, 1),
        data_hash="data",
        config_hash="config",
        universe_hash="universe",
    )
    captured = datetime(2026, 1, 2, tzinfo=UTC)
    fills = FillRepository(database)
    snapshots = SnapshotRepository(database)

    assert fills.save(
        broker_fill_id="fill-1",
        broker_order_id="order-1",
        quantity=2,
        price=Decimal("100.25"),
        fee=Decimal("0.30"),
        filled_at=captured,
    )
    assert not fills.save(
        broker_fill_id="fill-1",
        broker_order_id="order-1",
        quantity=2,
        price=Decimal("100.25"),
        fee=Decimal("0.30"),
        filled_at=captured,
    )
    positions = MappingProxyType({"A": PositionSnapshot("A", 2, Decimal("100.25"), Decimal("101"))})
    assert snapshots.save(
        run_id="run-1",
        captured_at=captured,
        nav=Decimal("1000"),
        cash=Decimal("798"),
        positions=positions,
        source="broker",
    )
    assert not snapshots.save(
        run_id="run-1",
        captured_at=captured,
        nav=Decimal("1000"),
        cash=Decimal("798"),
        positions=positions,
        source="broker",
    )

    with sqlite3.connect(database) as connection:
        stored = connection.execute(
            "SELECT positions_json FROM snapshots WHERE run_id = 'run-1'"
        ).fetchone()[0]
    assert stored == ('{"A":{"average_price":"100.25","market_price":"101","quantity":2}}')
