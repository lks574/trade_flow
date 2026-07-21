from datetime import UTC, date, datetime
from decimal import Decimal
from types import MappingProxyType

import pytest

from trade_flow.db import OrderRepository, RunRepository, initialize_database
from trade_flow.domain.config import load_config
from trade_flow.execution import (
    AccountSnapshot,
    BrokerOrder,
    ExecutionUncertain,
    OrderIntent,
    OrderPlan,
    PositionSnapshot,
    Quote,
    SubmissionStatusUnknown,
    execute_plan,
    plan_orders,
)


def _account() -> AccountSnapshot:
    return AccountSnapshot(
        account_hash="account-hash",
        captured_at=datetime(2026, 1, 2, tzinfo=UTC),
        nav=Decimal("10000"),
        cash=Decimal("5000"),
        positions=MappingProxyType(
            {"SELL": PositionSnapshot("SELL", 10, Decimal("100"), Decimal("100"))}
        ),
    )


def _quotes() -> dict[str, Quote]:
    captured = datetime(2026, 1, 2, tzinfo=UTC)
    return {
        "BUY": Quote("BUY", Decimal("99.9"), Decimal("100"), captured),
        "SELL": Quote("SELL", Decimal("100"), Decimal("100.1"), captured),
    }


def test_planner_sells_first_and_preserves_cash_buffer() -> None:
    config = load_config("configs/strategy.toml")

    plan = plan_orders(
        _account(),
        {"BUY": Decimal("0.8")},
        _quotes(),
        trading_date=date(2026, 1, 2),
        strategy_version=config.strategy_version,
        cash_buffer_fraction=config.strategy.cash_buffer_weight,
        config=config.execution,
    )

    assert plan.intents[0].side == "sell"
    assert plan.intents[0].quantity == 10
    assert plan.intents[1].side == "buy"
    assert plan.intents[1].quantity < 80
    repeated = plan_orders(
        _account(),
        {"BUY": Decimal("0.8")},
        _quotes(),
        trading_date=date(2026, 1, 2),
        strategy_version=config.strategy_version,
        cash_buffer_fraction=config.strategy.cash_buffer_weight,
        config=config.execution,
    )
    assert [intent.intent_id for intent in plan.intents] == [
        intent.intent_id for intent in repeated.intents
    ]

    with pytest.raises(ValueError, match="target weights"):
        plan_orders(
            _account(),
            {"BUY": Decimal("1.1")},
            _quotes(),
            trading_date=date(2026, 1, 2),
            strategy_version=config.strategy_version,
            cash_buffer_fraction=config.strategy.cash_buffer_weight,
            config=config.execution,
        )


def _repositories(tmp_path):
    database = initialize_database(tmp_path / "trade_flow.db")
    RunRepository(database).start(
        run_id="run-1",
        environment="paper",
        account_hash="account-hash",
        trading_date=date(2026, 1, 2),
        signal_date=date(2026, 1, 1),
        data_hash="data",
        config_hash="config",
        universe_hash="universe",
    )
    return OrderRepository(database)


def _intent() -> OrderIntent:
    return OrderIntent("intent-1", date(2026, 1, 2), "A", "buy", 1, Decimal("100"), 0)


class RecoveringBroker:
    def __init__(self, *, recover: bool = True) -> None:
        self.recover = recover
        self.submit_count = 0
        self.order = None

    def find_by_intent(self, intent_id):
        return self.order if self.recover else None

    def submit(self, intent):
        self.submit_count += 1
        self.order = BrokerOrder("broker-1", intent.intent_id, "filled", 1, 0)
        raise SubmissionStatusUnknown

    def await_terminal(self, order, timeout_seconds):
        return order

    def cancel(self, broker_order_id):
        raise AssertionError("filled order must not be cancelled")


def test_lost_submit_response_is_reconciled_without_duplicate(tmp_path) -> None:
    repository = _repositories(tmp_path)
    broker = RecoveringBroker()
    plan = OrderPlan((_intent(),), MappingProxyType({}))

    recovered = execute_plan(plan, broker, repository, run_id="run-1", timeout_seconds=10)
    repeated = execute_plan(plan, broker, repository, run_id="run-1", timeout_seconds=10)

    assert recovered[0].status == "filled"
    assert repeated == ()
    assert broker.submit_count == 1
    assert repository.status("intent-1") == "filled"


def test_unknown_submit_status_blocks_following_orders(tmp_path) -> None:
    repository = _repositories(tmp_path)
    broker = RecoveringBroker(recover=False)
    plan = OrderPlan((_intent(),), MappingProxyType({}))

    with pytest.raises(ExecutionUncertain, match="cannot reconcile"):
        execute_plan(plan, broker, repository, run_id="run-1", timeout_seconds=10)

    assert broker.submit_count == 1
    assert repository.status("intent-1") == "unknown"


def test_unreconciled_local_intent_is_never_resubmitted(tmp_path) -> None:
    repository = _repositories(tmp_path)
    intent = _intent()
    assert repository.reserve("run-1", intent)
    broker = RecoveringBroker(recover=False)

    with pytest.raises(ExecutionUncertain, match="local intent"):
        execute_plan(
            OrderPlan((intent,), MappingProxyType({})),
            broker,
            repository,
            run_id="run-1",
            timeout_seconds=10,
        )

    assert broker.submit_count == 0
