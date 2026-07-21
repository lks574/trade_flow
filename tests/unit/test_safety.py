from datetime import date, timedelta
from decimal import Decimal
from types import MappingProxyType

import pytest

from trade_flow.data import UniverseGrade
from trade_flow.execution import OrderIntent, OrderPlan
from trade_flow.safety import (
    ExecutionEnvironment,
    PaperSessionResult,
    ProductionSessionResult,
    SafetyBlocked,
    SafetyContext,
    apply_safety_filters,
    assess_paper_readiness,
    assess_production_readiness,
    authorize_execution,
)


def _plan(side: str = "buy") -> OrderPlan:
    intent = OrderIntent("intent", date(2026, 1, 2), "A", side, 1, Decimal(100), 0)
    return OrderPlan((intent,), MappingProxyType({}))


def _context(**overrides) -> SafetyContext:
    values = {
        "environment": ExecutionEnvironment.PAPER,
        "dry_run": False,
        "allow_real_orders": False,
        "release_approved": False,
        "account_hash": "account",
        "allowed_account_hashes": frozenset(),
        "kill_switch_active": False,
        "data_fresh": True,
        "account_reconciled": True,
        "open_orders_reconciled": True,
        "within_execution_window": True,
        "daily_return": Decimal(0),
        "daily_loss_limit": Decimal("0.03"),
    }
    values.update(overrides)
    return SafetyContext(**values)


def test_safety_gate_blocks_stale_data_and_daily_loss_buys() -> None:
    with pytest.raises(SafetyBlocked) as stale:
        authorize_execution(_context(data_fresh=False), _plan(), run_id="run")
    with pytest.raises(SafetyBlocked) as loss:
        authorize_execution(_context(daily_return=Decimal("-0.03")), _plan(), run_id="run")

    assert "stale_data" in stale.value.reasons
    assert "daily_loss_limit" in loss.value.reasons
    permit = authorize_execution(
        _context(daily_return=Decimal("-0.03")), _plan("sell"), run_id="run"
    )
    assert permit.run_id == "run"

    mixed = OrderPlan(
        (_plan("sell").intents[0], _plan("buy").intents[0]),
        MappingProxyType({}),
    )
    filtered = apply_safety_filters(_context(daily_return=Decimal("-0.03")), mixed)
    assert [intent.side for intent in filtered.intents] == ["sell"]
    assert authorize_execution(_context(daily_return=Decimal("-0.03")), filtered, run_id="run")


def test_production_is_blocked_by_default_and_requires_allowlist() -> None:
    production = _context(
        environment=ExecutionEnvironment.PRODUCTION,
        dry_run=True,
        allow_real_orders=False,
    )
    with pytest.raises(SafetyBlocked) as blocked:
        authorize_execution(production, _plan(), run_id="run")

    assert {
        "dry_run",
        "real_orders_disabled",
        "release_not_approved",
        "account_not_allowed",
    } <= set(blocked.value.reasons)
    allowed = _context(
        environment=ExecutionEnvironment.PRODUCTION,
        dry_run=False,
        allow_real_orders=True,
        release_approved=True,
        allowed_account_hashes=frozenset({"account"}),
    )
    assert authorize_execution(allowed, _plan(), run_id="run").run_id == "run"


def test_release_gates_require_paper_and_production_sessions() -> None:
    start = date(2026, 1, 1)
    sessions = [start + timedelta(days=index) for index in range(20)]
    coverage = frozenset(
        {
            "duplicate_order",
            "kill_switch",
            "stale_data",
            "balance_failure",
            "daily_loss",
            "notification_failure",
        }
    )
    paper = {
        session: PaperSessionResult(session, True, 0, True, True, coverage) for session in sessions
    }

    assert assess_paper_readiness(paper, sessions, UniverseGrade.B).approved
    grade_c = assess_paper_readiness(paper, sessions, UniverseGrade.C)
    assert not grade_c.approved
    assert grade_c.required_sessions == 80

    production = [
        ProductionSessionResult(start + timedelta(days=index), "dry_run", 0, True)
        for index in range(5)
    ] + [
        ProductionSessionResult(start + timedelta(days=5 + index), "small_capital", 0, True)
        for index in range(20)
    ]
    assert assess_production_readiness(production).approved
