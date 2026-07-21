import json
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from trade_flow.data import DailyBar, build_market_data_snapshot
from trade_flow.db import PriceRepository, initialize_database
from trade_flow.monitoring import load_events, load_monitoring_snapshot, load_positions


def test_monitoring_inputs_load_decimal_positions_and_events(tmp_path) -> None:
    portfolio = tmp_path / "portfolio.json"
    portfolio.write_text(
        json.dumps(
            {
                "positions": [
                    {
                        "symbol": "aapl",
                        "quantity": 2,
                        "average_price": "210.25",
                        "market_price": "215.50",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    events = tmp_path / "events.json"
    events.write_text(
        json.dumps(
            [
                {
                    "event_id": "event-1",
                    "published_at": "2026-07-21T12:00:00+00:00",
                    "headline": "Material event",
                    "source": "fixture",
                    "scope": "company",
                    "direction": "negative",
                    "severity": "high",
                    "confidence": "0.90",
                    "summary": "fixture",
                    "affected_symbols": ["aapl"],
                }
            ]
        ),
        encoding="utf-8",
    )

    loaded_positions = load_positions(portfolio)
    loaded_events = load_events(events)

    assert tuple(loaded_positions) == ("AAPL",)
    assert loaded_positions["AAPL"].average_price.as_tuple().exponent == -2
    assert loaded_events[0].affected_symbols == ("AAPL",)


def test_event_timestamp_must_be_timezone_aware(tmp_path) -> None:
    events = tmp_path / "events.json"
    events.write_text(
        json.dumps(
            [
                {
                    "event_id": "event-1",
                    "published_at": "2026-07-21T12:00:00",
                    "headline": "Material event",
                    "source": "fixture",
                    "scope": "macro",
                    "direction": "mixed",
                    "severity": "high",
                    "confidence": "0.90",
                    "summary": "fixture",
                    "affected_symbols": [],
                }
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="timezone-aware"):
        load_events(events)


def test_monitoring_snapshot_uses_latest_completed_session(tmp_path) -> None:
    database = initialize_database(tmp_path / "trade_flow.db")
    session = date(2026, 7, 17)
    bar = DailyBar(
        symbol="AAPL",
        session_date=session,
        open=Decimal("100"),
        high=Decimal("102"),
        low=Decimal("99"),
        close=Decimal("101"),
        split_adjusted_open=Decimal("100"),
        split_adjusted_high=Decimal("102"),
        split_adjusted_low=Decimal("99"),
        split_adjusted_close=Decimal("101"),
        volume=100,
        cash_dividend=Decimal("0"),
        source="fixture",
        fetched_at=datetime(2026, 7, 18, tzinfo=UTC),
    )
    source_snapshot = build_market_data_snapshot(
        [bar],
        as_of=session,
        expected_sessions=[session],
        expected_symbols=["AAPL"],
    )
    PriceRepository(database).save_snapshot(source_snapshot)

    loaded = load_monitoring_snapshot(
        database,
        symbols={"AAPL"},
        as_of=date(2026, 7, 19),
        source="fixture",
        minimum_price_days=1,
    )

    assert loaded.as_of == session
