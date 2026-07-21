from __future__ import annotations

from typing import Protocol

from trade_flow.execution.models import (
    Broker,
    BrokerOrder,
    OrderIntent,
    OrderPlan,
    SubmissionStatusUnknown,
)
from trade_flow.safety.gate import ExecutionPermit, validate_permit


class OrderStore(Protocol):
    def reserve(self, run_id: str, intent: OrderIntent) -> bool: ...

    def update(self, intent_id: str, order: BrokerOrder) -> None: ...

    def mark_unknown(self, intent_id: str, error_code: str) -> None: ...

    def status(self, intent_id: str) -> str | None: ...


class ExecutionUncertain(RuntimeError):
    """Execution stopped because an order or cancellation cannot be reconciled."""


def _submit_once(
    intent: OrderIntent,
    broker: Broker,
    repository: OrderStore,
    *,
    run_id: str,
    timeout_seconds: int,
) -> BrokerOrder | None:
    reserved = repository.reserve(run_id, intent)
    if not reserved and repository.status(intent.intent_id) in {
        "filled",
        "cancelled",
        "rejected",
    }:
        return None
    existing = broker.find_by_intent(intent.intent_id)
    if existing is None:
        if not reserved:
            repository.mark_unknown(intent.intent_id, "local_intent_without_broker_order")
            raise ExecutionUncertain(f"cannot reconcile local intent {intent.intent_id}")
        try:
            order = broker.submit(intent)
        except SubmissionStatusUnknown:
            order = broker.find_by_intent(intent.intent_id)
            if order is None:
                repository.mark_unknown(intent.intent_id, "submission_status_unknown")
                raise ExecutionUncertain(
                    f"cannot reconcile order intent {intent.intent_id}"
                ) from None
    else:
        order = existing
    repository.update(intent.intent_id, order)
    terminal = broker.await_terminal(order, timeout_seconds)
    if not terminal.terminal:
        cancelled = broker.cancel(order.broker_order_id)
        terminal = broker.await_terminal(cancelled, timeout_seconds)
    repository.update(intent.intent_id, terminal)
    if not terminal.terminal:
        repository.mark_unknown(intent.intent_id, "cancellation_status_unknown")
        raise ExecutionUncertain(f"cannot confirm cancellation for {intent.intent_id}")
    return terminal


def execute_plan(
    plan: OrderPlan,
    broker: Broker,
    repository: OrderStore,
    *,
    run_id: str,
    timeout_seconds: int,
    permit: ExecutionPermit,
) -> tuple[BrokerOrder, ...]:
    validate_permit(permit, plan, run_id)
    completed: list[BrokerOrder] = []
    ordered = sorted(plan.intents, key=lambda intent: (intent.side != "sell", intent.symbol))
    for intent in ordered:
        order = _submit_once(
            intent,
            broker,
            repository,
            run_id=run_id,
            timeout_seconds=timeout_seconds,
        )
        if order is not None:
            completed.append(order)
    return tuple(completed)
