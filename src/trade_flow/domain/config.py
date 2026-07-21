from __future__ import annotations

import json
import tomllib
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    """Raised when a project configuration violates a documented invariant."""


def _decimal(value: object, field: str) -> Decimal:
    if isinstance(value, bool):
        raise ConfigError(f"{field} must be numeric")
    try:
        return Decimal(str(value))
    except Exception as exc:
        raise ConfigError(f"{field} must be numeric") from exc


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{field} must be an integer")
    return value


def _mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ConfigError(f"{field} must be a table")
    return value


@dataclass(frozen=True)
class FactorWeights:
    momentum: Decimal
    trend: Decimal
    rsi: Decimal
    macd: Decimal

    def __post_init__(self) -> None:
        values = (self.momentum, self.trend, self.rsi, self.macd)
        if any(value < 0 for value in values):
            raise ConfigError("factor weights must be non-negative")
        if sum(values) != Decimal("1"):
            raise ConfigError("factor weights must sum to 1")


@dataclass(frozen=True)
class StrategyConfig:
    main_count: int
    momentum_days: int
    sma_short_days: int
    sma_long_days: int
    rsi_days: int
    rsi_threshold: Decimal
    macd_fast_days: int
    macd_slow_days: int
    macd_signal_days: int
    tie_break_liquidity_days: int
    main_target_weight: Decimal
    general_symbol_weight_cap: Decimal
    high_volatility_total_cap: Decimal
    high_volatility_symbol_cap: Decimal
    high_volatility_max_symbols: int
    cash_buffer_weight: Decimal
    minimum_price_days: int
    maximum_recent_missing_days: int
    factor_weights: FactorWeights

    def __post_init__(self) -> None:
        if not 3 <= self.main_count <= 5:
            raise ConfigError("main_count must be between 3 and 5")
        positive_periods = (
            self.momentum_days,
            self.sma_short_days,
            self.sma_long_days,
            self.rsi_days,
            self.macd_fast_days,
            self.macd_slow_days,
            self.macd_signal_days,
            self.tie_break_liquidity_days,
            self.minimum_price_days,
        )
        if any(period <= 0 for period in positive_periods):
            raise ConfigError("indicator periods must be positive")
        if self.sma_short_days >= self.sma_long_days:
            raise ConfigError("sma_short_days must be less than sma_long_days")
        if self.macd_fast_days >= self.macd_slow_days:
            raise ConfigError("macd_fast_days must be less than macd_slow_days")
        if self.maximum_recent_missing_days != 0:
            raise ConfigError("recent price data cannot contain missing sessions")
        allocation = (
            self.main_target_weight + self.high_volatility_total_cap + self.cash_buffer_weight
        )
        if allocation != Decimal("1"):
            raise ConfigError("main, high-volatility, and cash weights must sum to 1")
        if self.high_volatility_symbol_cap * self.high_volatility_max_symbols > (
            self.high_volatility_total_cap
        ):
            raise ConfigError("high-volatility symbol caps exceed the sleeve cap")
        if self.general_symbol_weight_cap <= 0 or self.general_symbol_weight_cap > 1:
            raise ConfigError("general_symbol_weight_cap must be in (0, 1]")


@dataclass(frozen=True)
class RiskConfig:
    stop_loss_fraction: Decimal
    daily_loss_limit_fraction: Decimal
    regime_vix_threshold: Decimal
    regime_wti_return_days: int
    regime_wti_return_threshold: Decimal
    regime_exit_confirmation_days: int
    experimental_equity_cap: Decimal

    def __post_init__(self) -> None:
        fractions = (
            self.stop_loss_fraction,
            self.daily_loss_limit_fraction,
            self.regime_wti_return_threshold,
            self.experimental_equity_cap,
        )
        if any(value <= 0 or value >= 1 for value in fractions):
            raise ConfigError("risk fractions must be in (0, 1)")
        if self.regime_vix_threshold <= 0:
            raise ConfigError("regime_vix_threshold must be positive")
        if self.regime_wti_return_days <= 0 or self.regime_exit_confirmation_days <= 0:
            raise ConfigError("regime periods must be positive")


@dataclass(frozen=True)
class ValidationConfig:
    minimum_backtest_years: int
    holdout_years: int
    walk_forward_train_years: int
    walk_forward_validation_years: int
    transaction_cost_bps: tuple[int, ...]

    def __post_init__(self) -> None:
        if self.minimum_backtest_years <= self.holdout_years:
            raise ConfigError("backtest history must be longer than the holdout")
        if self.walk_forward_train_years <= 0 or self.walk_forward_validation_years <= 0:
            raise ConfigError("walk-forward periods must be positive")
        if not self.transaction_cost_bps or any(cost < 0 for cost in self.transaction_cost_bps):
            raise ConfigError("transaction costs must be non-negative")


@dataclass(frozen=True)
class AppConfig:
    strategy_version: str
    strategy: StrategyConfig
    risk: RiskConfig
    validation: ValidationConfig

    def canonical_mapping(self) -> dict[str, object]:
        return _canonicalize(asdict(self))

    @property
    def config_hash(self) -> str:
        payload = json.dumps(
            self.canonical_mapping(),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        return sha256(payload.encode("utf-8")).hexdigest()


def _canonicalize(value: object) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, Mapping):
        return {str(key): _canonicalize(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_canonicalize(item) for item in value]
    return value


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path)
    with config_path.open("rb") as file:
        raw = tomllib.load(file)

    strategy_raw = _mapping(raw.get("strategy"), "strategy")
    factor_raw = _mapping(strategy_raw.get("factor_weights"), "strategy.factor_weights")
    risk_raw = _mapping(raw.get("risk"), "risk")
    validation_raw = _mapping(raw.get("validation"), "validation")

    factor_weights = FactorWeights(
        momentum=_decimal(factor_raw.get("momentum"), "factor_weights.momentum"),
        trend=_decimal(factor_raw.get("trend"), "factor_weights.trend"),
        rsi=_decimal(factor_raw.get("rsi"), "factor_weights.rsi"),
        macd=_decimal(factor_raw.get("macd"), "factor_weights.macd"),
    )
    strategy = StrategyConfig(
        main_count=_integer(strategy_raw.get("main_count"), "strategy.main_count"),
        momentum_days=_integer(strategy_raw.get("momentum_days"), "strategy.momentum_days"),
        sma_short_days=_integer(strategy_raw.get("sma_short_days"), "strategy.sma_short_days"),
        sma_long_days=_integer(strategy_raw.get("sma_long_days"), "strategy.sma_long_days"),
        rsi_days=_integer(strategy_raw.get("rsi_days"), "strategy.rsi_days"),
        rsi_threshold=_decimal(strategy_raw.get("rsi_threshold"), "strategy.rsi_threshold"),
        macd_fast_days=_integer(strategy_raw.get("macd_fast_days"), "strategy.macd_fast_days"),
        macd_slow_days=_integer(strategy_raw.get("macd_slow_days"), "strategy.macd_slow_days"),
        macd_signal_days=_integer(
            strategy_raw.get("macd_signal_days"), "strategy.macd_signal_days"
        ),
        tie_break_liquidity_days=_integer(
            strategy_raw.get("tie_break_liquidity_days"),
            "strategy.tie_break_liquidity_days",
        ),
        main_target_weight=_decimal(
            strategy_raw.get("main_target_weight"), "strategy.main_target_weight"
        ),
        general_symbol_weight_cap=_decimal(
            strategy_raw.get("general_symbol_weight_cap"),
            "strategy.general_symbol_weight_cap",
        ),
        high_volatility_total_cap=_decimal(
            strategy_raw.get("high_volatility_total_cap"),
            "strategy.high_volatility_total_cap",
        ),
        high_volatility_symbol_cap=_decimal(
            strategy_raw.get("high_volatility_symbol_cap"),
            "strategy.high_volatility_symbol_cap",
        ),
        high_volatility_max_symbols=_integer(
            strategy_raw.get("high_volatility_max_symbols"),
            "strategy.high_volatility_max_symbols",
        ),
        cash_buffer_weight=_decimal(
            strategy_raw.get("cash_buffer_weight"), "strategy.cash_buffer_weight"
        ),
        minimum_price_days=_integer(
            strategy_raw.get("minimum_price_days"), "strategy.minimum_price_days"
        ),
        maximum_recent_missing_days=_integer(
            strategy_raw.get("maximum_recent_missing_days"),
            "strategy.maximum_recent_missing_days",
        ),
        factor_weights=factor_weights,
    )
    risk = RiskConfig(
        stop_loss_fraction=_decimal(risk_raw.get("stop_loss_fraction"), "risk.stop_loss_fraction"),
        daily_loss_limit_fraction=_decimal(
            risk_raw.get("daily_loss_limit_fraction"), "risk.daily_loss_limit_fraction"
        ),
        regime_vix_threshold=_decimal(
            risk_raw.get("regime_vix_threshold"), "risk.regime_vix_threshold"
        ),
        regime_wti_return_days=_integer(
            risk_raw.get("regime_wti_return_days"), "risk.regime_wti_return_days"
        ),
        regime_wti_return_threshold=_decimal(
            risk_raw.get("regime_wti_return_threshold"),
            "risk.regime_wti_return_threshold",
        ),
        regime_exit_confirmation_days=_integer(
            risk_raw.get("regime_exit_confirmation_days"),
            "risk.regime_exit_confirmation_days",
        ),
        experimental_equity_cap=_decimal(
            risk_raw.get("experimental_equity_cap"), "risk.experimental_equity_cap"
        ),
    )
    costs = validation_raw.get("transaction_cost_bps")
    if not isinstance(costs, list):
        raise ConfigError("validation.transaction_cost_bps must be an array")
    validation = ValidationConfig(
        minimum_backtest_years=_integer(
            validation_raw.get("minimum_backtest_years"),
            "validation.minimum_backtest_years",
        ),
        holdout_years=_integer(validation_raw.get("holdout_years"), "validation.holdout_years"),
        walk_forward_train_years=_integer(
            validation_raw.get("walk_forward_train_years"),
            "validation.walk_forward_train_years",
        ),
        walk_forward_validation_years=_integer(
            validation_raw.get("walk_forward_validation_years"),
            "validation.walk_forward_validation_years",
        ),
        transaction_cost_bps=tuple(
            _integer(cost, f"validation.transaction_cost_bps[{index}]")
            for index, cost in enumerate(costs)
        ),
    )
    strategy_version = raw.get("strategy_version")
    if not isinstance(strategy_version, str) or not strategy_version.strip():
        raise ConfigError("strategy_version must be a non-empty string")
    return AppConfig(
        strategy_version=strategy_version,
        strategy=strategy,
        risk=risk,
        validation=validation,
    )
