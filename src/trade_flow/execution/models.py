from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True)
class PositionSnapshot:
    symbol: str
    quantity: int
    average_price: Decimal
    market_price: Decimal

    def __post_init__(self) -> None:
        if self.quantity < 0 or self.average_price < 0 or self.market_price <= 0:
            raise ValueError("position quantity and prices are invalid")


@dataclass(frozen=True)
class AccountSnapshot:
    account_hash: str
    captured_at: datetime
    nav: Decimal
    cash: Decimal
    positions: Mapping[str, PositionSnapshot]

    def __post_init__(self) -> None:
        if self.captured_at.tzinfo is None or self.captured_at.utcoffset() is None:
            raise ValueError("account snapshot time must be timezone-aware")
        if self.nav <= 0 or self.cash < 0:
            raise ValueError("account NAV must be positive and cash cannot be negative")


@dataclass(frozen=True)
class Quote:
    symbol: str
    bid: Decimal
    ask: Decimal
    captured_at: datetime

    def __post_init__(self) -> None:
        if self.bid <= 0 or self.ask <= 0 or self.bid > self.ask:
            raise ValueError("quote must have positive ordered bid and ask")
        if self.captured_at.tzinfo is None or self.captured_at.utcoffset() is None:
            raise ValueError("quote time must be timezone-aware")


@dataclass(frozen=True)
class OrderIntent:
    intent_id: str
    trading_date: date
    symbol: str
    side: str
    quantity: int
    limit_price: Decimal
    rebalance_sequence: int

    def __post_init__(self) -> None:
        if self.side not in {"buy", "sell"}:
            raise ValueError("order side must be buy or sell")
        if self.quantity <= 0 or self.limit_price <= 0 or self.rebalance_sequence < 0:
            raise ValueError("order quantity, price, and sequence are invalid")


@dataclass(frozen=True)
class OrderPlan:
    intents: tuple[OrderIntent, ...]
    drift: Mapping[str, str]


@dataclass(frozen=True)
class BrokerOrder:
    broker_order_id: str
    intent_id: str
    status: str
    filled_quantity: int
    remaining_quantity: int

    @property
    def terminal(self) -> bool:
        return self.status in {"filled", "cancelled", "rejected"}


class SubmissionStatusUnknown(TimeoutError):
    """The submit call outcome is unknown and must be reconciled before retry."""


class Broker(Protocol):
    def find_by_intent(self, intent_id: str) -> BrokerOrder | None: ...

    def submit(self, intent: OrderIntent) -> BrokerOrder: ...

    def await_terminal(self, order: BrokerOrder, timeout_seconds: int) -> BrokerOrder: ...

    def cancel(self, broker_order_id: str) -> BrokerOrder: ...
