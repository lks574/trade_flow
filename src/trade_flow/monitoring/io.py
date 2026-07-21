from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from trade_flow.data import MarketDataSnapshot, build_market_data_snapshot
from trade_flow.db import PriceRepository
from trade_flow.execution import PositionSnapshot
from trade_flow.monitoring.models import EventDirection, EventSeverity, MarketEvent


def _object(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    return value


def load_positions(path: str | Path) -> Mapping[str, PositionSnapshot]:
    raw = _object(json.loads(Path(path).read_text(encoding="utf-8")), "portfolio")
    rows = raw.get("positions")
    if not isinstance(rows, list):
        raise ValueError("portfolio.positions must be an array")
    positions: dict[str, PositionSnapshot] = {}
    for index, value in enumerate(rows):
        row = _object(value, f"portfolio.positions[{index}]")
        symbol = str(row.get("symbol", "")).strip().upper()
        if not symbol or symbol in positions:
            raise ValueError("portfolio symbols must be non-empty and unique")
        quantity = row.get("quantity")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
            raise ValueError(f"portfolio.positions[{index}].quantity must be a positive integer")
        positions[symbol] = PositionSnapshot(
            symbol=symbol,
            quantity=quantity,
            average_price=Decimal(str(row.get("average_price", "0"))),
            market_price=Decimal(str(row.get("market_price", "0"))),
        )
    return positions


def load_events(path: str | Path | None) -> tuple[MarketEvent, ...]:
    if path is None:
        return ()
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("events must be an array")
    events: list[MarketEvent] = []
    seen: set[str] = set()
    for index, value in enumerate(raw):
        row = _object(value, f"events[{index}]")
        event_id = str(row.get("event_id", "")).strip()
        if event_id in seen:
            raise ValueError("event ids must be unique")
        affected = row.get("affected_symbols", [])
        if not isinstance(affected, list):
            raise ValueError(f"events[{index}].affected_symbols must be an array")
        event = MarketEvent(
            event_id=event_id,
            published_at=datetime.fromisoformat(str(row.get("published_at", ""))),
            headline=str(row.get("headline", "")).strip(),
            source=str(row.get("source", "")).strip(),
            scope=str(row.get("scope", "")).strip(),
            direction=EventDirection(str(row.get("direction", ""))),
            severity=EventSeverity(str(row.get("severity", ""))),
            confidence=Decimal(str(row.get("confidence", "0"))),
            summary=str(row.get("summary", "")).strip(),
            affected_symbols=tuple(sorted({str(item).strip().upper() for item in affected})),
        )
        events.append(event)
        seen.add(event_id)
    return tuple(sorted(events, key=lambda event: (event.published_at, event.event_id)))


def load_monitoring_snapshot(
    database_path: str | Path,
    *,
    symbols: set[str],
    as_of: date,
    source: str,
    minimum_price_days: int,
) -> MarketDataSnapshot:
    if not symbols:
        raise ValueError("monitoring requires at least one active or held symbol")
    lookback_days = max(400, minimum_price_days * 2)
    bars = PriceRepository(database_path).load_bars(
        symbols=sorted(symbols),
        start=as_of - timedelta(days=lookback_days),
        end=as_of,
        source=source,
    )
    sessions = sorted({bar.session_date for bar in bars})
    effective_as_of = sessions[-1] if sessions else as_of
    return build_market_data_snapshot(
        bars,
        as_of=effective_as_of,
        expected_sessions=sessions,
        expected_symbols=symbols,
    )
