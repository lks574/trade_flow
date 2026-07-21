from datetime import UTC, date, datetime
from decimal import Decimal
from types import MappingProxyType

from trade_flow.db import OrderRepository, RunRepository, initialize_database
from trade_flow.domain.config import load_config
from trade_flow.execution import (
    AccountSnapshot,
    BrokerOrder,
    PositionSnapshot,
    Quote,
    execute_rebalance,
)
from trade_flow.risk import RegimePolicy, RegimeState
from trade_flow.safety import ExecutionEnvironment, SafetyContext
from trade_flow.strategy import StrategyResult


class StatefulBroker:
    def __init__(self) -> None:
        self.cash = Decimal(0)
        self.positions = {"A": PositionSnapshot("A", 10, Decimal(100), Decimal(100))}
        self.orders = {}
        self.submitted_sides = []

    def account_snapshot(self):
        nav = self.cash + sum(
            Decimal(position.quantity) * position.market_price
            for position in self.positions.values()
        )
        return AccountSnapshot(
            "account",
            datetime(2026, 1, 2, tzinfo=UTC),
            nav,
            self.cash,
            MappingProxyType(dict(self.positions)),
        )

    def quote(self, symbol):
        return Quote(
            symbol,
            Decimal(100),
            Decimal(100),
            datetime(2026, 1, 2, tzinfo=UTC),
        )

    def find_by_intent(self, intent_id):
        return self.orders.get(intent_id)

    def submit(self, intent):
        self.submitted_sides.append(intent.side)
        if intent.side == "sell":
            position = self.positions[intent.symbol]
            self.cash += Decimal(intent.quantity) * intent.limit_price
            remaining = position.quantity - intent.quantity
            if remaining:
                self.positions[intent.symbol] = PositionSnapshot(
                    intent.symbol,
                    remaining,
                    position.average_price,
                    position.market_price,
                )
            else:
                self.positions.pop(intent.symbol)
        else:
            self.cash -= Decimal(intent.quantity) * intent.limit_price
            self.positions[intent.symbol] = PositionSnapshot(
                intent.symbol,
                intent.quantity,
                intent.limit_price,
                Decimal(100),
            )
        order = BrokerOrder(
            f"broker-{len(self.orders) + 1}",
            intent.intent_id,
            "filled",
            intent.quantity,
            0,
        )
        self.orders[intent.intent_id] = order
        return order

    def await_terminal(self, order, timeout_seconds):
        return order

    def cancel(self, broker_order_id):
        raise AssertionError("fixture fills immediately")


def test_rebalance_replans_buys_from_actual_post_sell_cash(tmp_path) -> None:
    config = load_config("configs/strategy.toml")
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
    strategy = StrategyResult(
        date(2026, 1, 1),
        MappingProxyType({"B": Decimal("0.8")}),
        Decimal("0.2"),
        MappingProxyType({}),
        MappingProxyType({}),
    )
    safety = SafetyContext(
        ExecutionEnvironment.PAPER,
        False,
        False,
        False,
        "account",
        frozenset(),
        False,
        True,
        True,
        True,
        True,
        Decimal(0),
        Decimal("0.03"),
    )
    broker = StatefulBroker()

    result = execute_rebalance(
        strategy,
        RegimeState(date(2026, 1, 1), False, True, 0, ()),
        config,
        broker,
        OrderRepository(database),
        run_id="run-1",
        trading_date=date(2026, 1, 2),
        safety_context=safety,
        daily_return=Decimal(0),
        regime_policy=RegimePolicy.BUY_BLOCK,
    )

    assert broker.submitted_sides == ["sell", "buy"]
    assert result.sell_plan.intents[0].rebalance_sequence == 0
    assert result.buy_plan.intents[0].rebalance_sequence == 1
    assert result.final_account.positions["B"].quantity > 0
