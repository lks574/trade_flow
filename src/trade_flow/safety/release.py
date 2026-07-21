from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from trade_flow.data import UniverseGrade

REQUIRED_FAILURE_INJECTIONS = frozenset(
    {
        "duplicate_order",
        "kill_switch",
        "stale_data",
        "balance_failure",
        "daily_loss",
        "notification_failure",
    }
)


@dataclass(frozen=True)
class PaperSessionResult:
    session_date: date
    unattended: bool
    critical_errors: int
    alert_detected: bool
    positions_reconciled: bool
    failure_injections: frozenset[str]


@dataclass(frozen=True)
class ProductionSessionResult:
    session_date: date
    stage: str
    critical_errors: int
    positions_reconciled: bool


@dataclass(frozen=True)
class ReleaseDecision:
    approved: bool
    reasons: tuple[str, ...]
    required_sessions: int
    completed_sessions: int


def assess_paper_readiness(
    results: Mapping[date, PaperSessionResult],
    expected_sessions: Sequence[date],
    universe_grade: UniverseGrade,
) -> ReleaseDecision:
    required = 20 + (60 if universe_grade is UniverseGrade.C else 0)
    expected = sorted(set(expected_sessions))
    window = expected[-required:]
    completed = [results[session] for session in window if session in results]
    reasons: list[str] = []
    if len(window) < required or len(completed) < required:
        reasons.append("insufficient_consecutive_sessions")
    if any(item.critical_errors for item in completed):
        reasons.append("critical_errors_present")
    if any(not item.unattended for item in completed):
        reasons.append("manual_intervention_present")
    if any(not item.alert_detected for item in completed):
        reasons.append("silent_failure_present")
    if any(not item.positions_reconciled for item in completed):
        reasons.append("position_mismatch_present")
    covered = frozenset().union(*(item.failure_injections for item in completed))
    if not covered >= REQUIRED_FAILURE_INJECTIONS:
        reasons.append("failure_injection_coverage_incomplete")
    return ReleaseDecision(not reasons, tuple(reasons), required, len(completed))


def assess_production_readiness(
    results: Sequence[ProductionSessionResult],
) -> ReleaseDecision:
    dry_run = [item for item in results if item.stage == "dry_run"]
    small = [item for item in results if item.stage == "small_capital"]
    reasons: list[str] = []
    if len(dry_run) < 5:
        reasons.append("insufficient_production_dry_run")
    if len(small) < 20:
        reasons.append("insufficient_small_capital_sessions")
    ordered = sorted(results, key=lambda item: item.session_date)
    first_small = next(
        (index for index, item in enumerate(ordered) if item.stage == "small_capital"),
        len(ordered),
    )
    if any(item.stage == "dry_run" for item in ordered[first_small:]):
        reasons.append("production_stage_order_invalid")
    if any(item.critical_errors for item in results):
        reasons.append("critical_errors_present")
    if any(not item.positions_reconciled for item in results):
        reasons.append("position_mismatch_present")
    return ReleaseDecision(not reasons, tuple(reasons), 25, len(results))
