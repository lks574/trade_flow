"""Backtest validation windows, metrics, and reports."""

from trade_flow.validation.benchmarks import buy_and_hold_benchmark, cash_benchmark
from trade_flow.validation.events import EventStudyResult, EventWindow, analyze_event_windows
from trade_flow.validation.metrics import PerformanceMetrics, calculate_metrics
from trade_flow.validation.report import (
    BenchmarkResult,
    PeriodScenarioResult,
    ScenarioResult,
    ValidationReport,
    evaluate_scenarios,
)
from trade_flow.validation.windows import ValidationWindow, build_validation_windows

__all__ = [
    "EventStudyResult",
    "EventWindow",
    "BenchmarkResult",
    "PerformanceMetrics",
    "PeriodScenarioResult",
    "ScenarioResult",
    "ValidationReport",
    "ValidationWindow",
    "analyze_event_windows",
    "build_validation_windows",
    "buy_and_hold_benchmark",
    "calculate_metrics",
    "cash_benchmark",
    "evaluate_scenarios",
]
