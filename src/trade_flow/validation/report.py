from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal

from trade_flow.backtest import run_backtest
from trade_flow.data import MarketDataSnapshot
from trade_flow.data.universe import UniverseSpec
from trade_flow.domain.config import AppConfig
from trade_flow.risk import RegimePolicy, RegimeState
from trade_flow.validation.benchmarks import buy_and_hold_benchmark, cash_benchmark
from trade_flow.validation.metrics import PerformanceMetrics, calculate_metrics
from trade_flow.validation.windows import build_validation_windows


@dataclass(frozen=True)
class ScenarioResult:
    transaction_cost_bps: int
    regime_policy: str
    metrics: PerformanceMetrics


@dataclass(frozen=True)
class PeriodScenarioResult:
    period: str
    start: date
    end: date
    transaction_cost_bps: int
    regime_policy: str
    metrics: PerformanceMetrics


@dataclass(frozen=True)
class BenchmarkResult:
    name: str
    transaction_cost_bps: int
    metrics: PerformanceMetrics


@dataclass(frozen=True)
class ValidationReport:
    data_hash: str
    config_hash: str
    scenarios: tuple[ScenarioResult, ...]
    period_scenarios: tuple[PeriodScenarioResult, ...]
    benchmarks: tuple[BenchmarkResult, ...]

    def to_json(self) -> str:
        return json.dumps(
            asdict(self),
            default=lambda value: value.isoformat() if isinstance(value, date) else str(value),
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )


def evaluate_scenarios(
    snapshot: MarketDataSnapshot,
    config: AppConfig,
    *,
    main_symbols: set[str] | UniverseSpec,
    high_volatility_symbols: set[str] | UniverseSpec | None = None,
    initial_cash: Decimal = Decimal("20000000"),
    regime_states: Mapping[date, RegimeState] | None = None,
    benchmark_symbol: str = "SPY",
) -> ValidationReport:
    results: list[ScenarioResult] = []
    periods: list[PeriodScenarioResult] = []
    benchmarks: list[BenchmarkResult] = []
    typed_states = regime_states or {}
    sessions = sorted({bar.session_date for bar in snapshot.prices})
    if len(sessions) <= config.strategy.minimum_price_days:
        raise ValueError("market data has insufficient sessions after warm-up")
    try:
        minimum_end = sessions[0].replace(
            year=sessions[0].year + config.validation.minimum_backtest_years
        )
    except ValueError:
        minimum_end = sessions[0].replace(
            year=sessions[0].year + config.validation.minimum_backtest_years,
            day=28,
        )
    if sessions[-1] < minimum_end:
        raise ValueError("market data does not satisfy minimum_backtest_years")
    try:
        holdout_start = sessions[-1].replace(
            year=sessions[-1].year - config.validation.holdout_years
        )
    except ValueError:
        holdout_start = sessions[-1].replace(
            year=sessions[-1].year - config.validation.holdout_years,
            day=28,
        )
    evaluation_start = sessions[config.strategy.minimum_price_days]
    windows = build_validation_windows(
        sessions,
        train_years=config.validation.walk_forward_train_years,
        validation_years=config.validation.walk_forward_validation_years,
        holdout_years=config.validation.holdout_years,
    )
    for cost in config.validation.transaction_cost_bps:
        for policy in (RegimePolicy.BUY_BLOCK, RegimePolicy.EQUITY_CAP):
            backtest = run_backtest(
                snapshot,
                config,
                main_symbols=main_symbols,
                high_volatility_symbols=high_volatility_symbols or set(),
                initial_cash=initial_cash,
                transaction_cost_bps=cost,
                regime_states=typed_states,
                regime_policy=policy,
            )
            results.append(ScenarioResult(cost, policy.value, calculate_metrics(backtest)))
            periods.append(
                PeriodScenarioResult(
                    "holdout",
                    holdout_start,
                    sessions[-1],
                    cost,
                    policy.value,
                    calculate_metrics(backtest, start=holdout_start),
                )
            )
            for index, window in enumerate(windows, start=1):
                periods.append(
                    PeriodScenarioResult(
                        f"walk_forward_{index}",
                        window.validation_start,
                        window.validation_end,
                        cost,
                        policy.value,
                        calculate_metrics(
                            backtest,
                            start=window.validation_start,
                            end=window.validation_end,
                        ),
                    )
                )
        if any(bar.symbol == benchmark_symbol for bar in snapshot.prices):
            benchmark = buy_and_hold_benchmark(
                snapshot,
                symbol=benchmark_symbol,
                initial_cash=initial_cash,
                transaction_cost_bps=cost,
                start=evaluation_start,
            )
            benchmarks.append(BenchmarkResult(benchmark_symbol, cost, calculate_metrics(benchmark)))
    benchmarks.append(
        BenchmarkResult(
            "cash",
            0,
            calculate_metrics(cash_benchmark(snapshot, initial_cash), start=evaluation_start),
        )
    )
    return ValidationReport(
        data_hash=snapshot.data_hash,
        config_hash=config.config_hash,
        scenarios=tuple(results),
        period_scenarios=tuple(periods),
        benchmarks=tuple(benchmarks),
    )
