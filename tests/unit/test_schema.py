import sqlite3

from trade_flow.db import SCHEMA_VERSION, initialize_database


def test_initialize_database_creates_required_tables(tmp_path) -> None:
    path = initialize_database(tmp_path / "trade_flow.db")

    with sqlite3.connect(path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
            )
        }
        version = connection.execute("PRAGMA user_version").fetchone()[0]

    assert tables == {
        "fills",
        "market_context",
        "order_events",
        "orders",
        "price_targets",
        "prices",
        "recommendations",
        "runs",
        "sentiment",
        "snapshots",
    }
    assert version == SCHEMA_VERSION
