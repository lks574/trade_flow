"""Execution authorization and staged release gates."""

from trade_flow.safety.gate import (
    ExecutionEnvironment,
    ExecutionPermit,
    SafetyBlocked,
    SafetyContext,
    apply_safety_filters,
    authorize_execution,
)
from trade_flow.safety.release import (
    PaperSessionResult,
    ProductionSessionResult,
    ReleaseDecision,
    assess_paper_readiness,
    assess_production_readiness,
)
from trade_flow.safety.runtime import (
    EnvironmentMismatchError,
    RuntimeConfig,
    kill_switch_active,
    load_runtime_config,
    validate_environment_binding,
)

__all__ = [
    "EnvironmentMismatchError",
    "ExecutionEnvironment",
    "ExecutionPermit",
    "PaperSessionResult",
    "ProductionSessionResult",
    "ReleaseDecision",
    "RuntimeConfig",
    "SafetyBlocked",
    "SafetyContext",
    "apply_safety_filters",
    "assess_paper_readiness",
    "assess_production_readiness",
    "authorize_execution",
    "kill_switch_active",
    "load_runtime_config",
    "validate_environment_binding",
]
