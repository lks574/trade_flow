from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Protocol

_PERMIT_KEY = object()


class IntentLike(Protocol):
    intent_id: str
    side: str


class PlanLike(Protocol):
    intents: tuple[IntentLike, ...]
    drift: Mapping[str, str]


class ExecutionEnvironment(StrEnum):
    PAPER = "paper"
    PRODUCTION = "production"


@dataclass(frozen=True)
class SafetyContext:
    environment: ExecutionEnvironment
    dry_run: bool
    allow_real_orders: bool
    release_approved: bool
    account_hash: str
    allowed_account_hashes: frozenset[str]
    kill_switch_active: bool
    data_fresh: bool
    account_reconciled: bool
    open_orders_reconciled: bool
    within_execution_window: bool
    daily_return: Decimal
    daily_loss_limit: Decimal

    def __post_init__(self) -> None:
        if not Decimal(0) < self.daily_loss_limit < Decimal(1):
            raise ValueError("daily loss limit must be in (0, 1)")
        if not self.account_hash:
            raise ValueError("account hash is required")


@dataclass(frozen=True)
class ExecutionPermit:
    run_id: str
    intent_ids: frozenset[str]
    environment: ExecutionEnvironment
    _key: object = field(repr=False, compare=False)


class SafetyBlocked(RuntimeError):
    def __init__(self, reasons: tuple[str, ...]) -> None:
        self.reasons = reasons
        super().__init__("execution blocked: " + ", ".join(reasons))


def apply_safety_filters[PlanT: PlanLike](context: SafetyContext, plan: PlanT) -> PlanT:
    if context.daily_return > -context.daily_loss_limit:
        return plan
    removed = [intent for intent in plan.intents if intent.side == "buy"]
    if not removed:
        return plan
    drift = dict(plan.drift)
    for intent in removed:
        drift[intent.symbol] = "daily_loss_limit"
    return replace(
        plan,
        intents=tuple(intent for intent in plan.intents if intent.side != "buy"),
        drift=MappingProxyType(dict(sorted(drift.items()))),
    )


def authorize_execution(context: SafetyContext, plan: PlanLike, *, run_id: str) -> ExecutionPermit:
    reasons: list[str] = []
    if context.kill_switch_active:
        reasons.append("kill_switch")
    if context.dry_run:
        reasons.append("dry_run")
    if not context.data_fresh:
        reasons.append("stale_data")
    if not context.account_reconciled:
        reasons.append("account_not_reconciled")
    if not context.open_orders_reconciled:
        reasons.append("open_orders_not_reconciled")
    if not context.within_execution_window:
        reasons.append("outside_execution_window")
    if any(intent.side == "buy" for intent in plan.intents) and (
        context.daily_return <= -context.daily_loss_limit
    ):
        reasons.append("daily_loss_limit")
    if context.environment is ExecutionEnvironment.PRODUCTION:
        if not context.allow_real_orders:
            reasons.append("real_orders_disabled")
        if not context.release_approved:
            reasons.append("release_not_approved")
        if context.account_hash not in context.allowed_account_hashes:
            reasons.append("account_not_allowed")
    if reasons:
        raise SafetyBlocked(tuple(reasons))
    return ExecutionPermit(
        run_id=run_id,
        intent_ids=frozenset(intent.intent_id for intent in plan.intents),
        environment=context.environment,
        _key=_PERMIT_KEY,
    )


def validate_permit(permit: ExecutionPermit, plan: PlanLike, run_id: str) -> None:
    if permit._key is not _PERMIT_KEY:
        raise SafetyBlocked(("invalid_permit",))
    if permit.run_id != run_id:
        raise SafetyBlocked(("permit_run_mismatch",))
    if permit.intent_ids != frozenset(intent.intent_id for intent in plan.intents):
        raise SafetyBlocked(("permit_plan_mismatch",))
