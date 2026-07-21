import json
from datetime import date

from trade_flow.validation import (
    BenchmarkResult,
    PerformanceMetrics,
    PeriodScenarioResult,
    ScenarioResult,
    ValidationReport,
)


def _metrics() -> PerformanceMetrics:
    return PerformanceMetrics(0.1, 0.1, -0.05, 1.0, 2.0, 0.5, 0.6, 10, 4)


def test_validation_report_serializes_dates_deterministically() -> None:
    report = ValidationReport(
        data_hash="data",
        config_hash="config",
        scenarios=(ScenarioResult(15, "buy_block", _metrics()),),
        period_scenarios=(
            PeriodScenarioResult(
                "holdout",
                date(2024, 1, 1),
                date(2025, 12, 31),
                15,
                "buy_block",
                _metrics(),
            ),
        ),
        benchmarks=(BenchmarkResult("cash", 0, _metrics()),),
    )

    first = report.to_json()
    second = report.to_json()

    assert first == second
    assert json.loads(first)["period_scenarios"][0]["start"] == "2024-01-01"
