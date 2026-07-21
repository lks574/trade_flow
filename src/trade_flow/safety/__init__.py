"""Execution authorization and staged release gates."""

from trade_flow.safety.gate import (
    ExecutionEnvironment,
    ExecutionPermit,
    SafetyBlocked,
    SafetyContext,
    authorize_execution,
)
from trade_flow.safety.release import (
    PaperSessionResult,
    ProductionSessionResult,
    ReleaseDecision,
    assess_paper_readiness,
    assess_production_readiness,
)
from trade_flow.safety.runtime import RuntimeConfig, kill_switch_active, load_runtime_config

__all__ = [
    "ExecutionEnvironment",
    "ExecutionPermit",
    "PaperSessionResult",
    "ProductionSessionResult",
    "ReleaseDecision",
    "RuntimeConfig",
    "SafetyBlocked",
    "SafetyContext",
    "assess_paper_readiness",
    "assess_production_readiness",
    "authorize_execution",
    "kill_switch_active",
    "load_runtime_config",
]
