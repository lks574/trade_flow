from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from types import MappingProxyType

from trade_flow.data.market import DailyBar, MarketDataSnapshot
from trade_flow.domain.config import StrategyConfig
from trade_flow.strategy.indicators import (
    macd,
    percentile_ranks,
    relative_strength_index,
    simple_moving_average,
)


@dataclass(frozen=True)
class FactorScore:
    momentum_return: Decimal
    momentum_percentile: Decimal
    trend: Decimal
    rsi: Decimal
    macd: Decimal
    average_dollar_volume: Decimal
    total: Decimal


@dataclass(frozen=True)
class StrategyResult:
    as_of: date
    target_weights: Mapping[str, Decimal]
    cash_weight: Decimal
    scores: Mapping[str, FactorScore]
    exclusions: Mapping[str, str]


def _bars_by_symbol(snapshot: MarketDataSnapshot) -> dict[str, tuple[DailyBar, ...]]:
    grouped: dict[str, list[DailyBar]] = defaultdict(list)
    for bar in snapshot.prices:
        grouped[bar.symbol].append(bar)
    return {
        symbol: tuple(sorted(bars, key=lambda item: item.session_date))
        for symbol, bars in grouped.items()
    }


def _raw_factors(
    bars: Sequence[DailyBar], config: StrategyConfig
) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal] | None:
    if len(bars) < config.minimum_price_days:
        return None
    closes = [bar.split_adjusted_close for bar in bars]
    long_sma = simple_moving_average(closes, config.sma_long_days)
    if closes[-1] <= long_sma:
        return None
    momentum = closes[-1] / closes[-(config.momentum_days + 1)] - Decimal(1)
    trend = Decimal(simple_moving_average(closes, config.sma_short_days) > long_sma)
    rsi_value = relative_strength_index(closes, config.rsi_days)
    rsi_signal = Decimal(rsi_value < config.rsi_threshold)
    macd_line, signal_line = macd(
        closes,
        config.macd_fast_days,
        config.macd_slow_days,
        config.macd_signal_days,
    )
    macd_signal = Decimal(macd_line > signal_line)
    recent = bars[-config.tie_break_liquidity_days :]
    average_dollar_volume = sum(
        bar.split_adjusted_close * Decimal(bar.volume) for bar in recent
    ) / Decimal(len(recent))
    return momentum, trend, rsi_signal, macd_signal, average_dollar_volume


def _ranked_symbols(scores: Mapping[str, FactorScore], candidates: Iterable[str]) -> list[str]:
    available = set(candidates) & set(scores)
    return sorted(
        available,
        key=lambda symbol: (
            -scores[symbol].total,
            -scores[symbol].momentum_return,
            -scores[symbol].average_dollar_volume,
            symbol,
        ),
    )


def signal(
    snapshot: MarketDataSnapshot,
    config: StrategyConfig,
    *,
    main_symbols: Iterable[str],
    high_volatility_symbols: Iterable[str] = (),
) -> StrategyResult:
    snapshot.quality_report.require_valid()
    grouped = _bars_by_symbol(snapshot)
    main_set = set(main_symbols)
    high_volatility_set = set(high_volatility_symbols) - main_set
    requested = main_set | high_volatility_set
    raw: dict[str, tuple[Decimal, Decimal, Decimal, Decimal, Decimal]] = {}
    exclusions: dict[str, str] = {}
    for symbol in sorted(requested):
        bars = grouped.get(symbol, ())
        factors = _raw_factors(bars, config)
        if factors is None:
            exclusions[symbol] = (
                "insufficient_history"
                if len(bars) < config.minimum_price_days
                else "below_sma_long"
            )
            continue
        raw[symbol] = factors

    momentum_ranks = percentile_ranks({symbol: values[0] for symbol, values in raw.items()})
    weights = config.factor_weights
    scores: dict[str, FactorScore] = {}
    for symbol, values in raw.items():
        momentum_return, trend, rsi_value, macd_value, liquidity = values
        momentum_percentile = momentum_ranks[symbol]
        total = (
            weights.momentum * momentum_percentile
            + weights.trend * trend
            + weights.rsi * rsi_value
            + weights.macd * macd_value
        )
        scores[symbol] = FactorScore(
            momentum_return=momentum_return,
            momentum_percentile=momentum_percentile,
            trend=trend,
            rsi=rsi_value,
            macd=macd_value,
            average_dollar_volume=liquidity,
            total=total,
        )

    target_weights: dict[str, Decimal] = {}
    main_ranked = _ranked_symbols(scores, main_set)[: config.main_count]
    main_weight = min(
        config.main_target_weight / Decimal(config.main_count),
        config.general_symbol_weight_cap,
    )
    target_weights.update({symbol: main_weight for symbol in main_ranked})

    high_ranked = _ranked_symbols(scores, high_volatility_set)[: config.high_volatility_max_symbols]
    high_weight = min(
        config.high_volatility_symbol_cap,
        config.high_volatility_total_cap / Decimal(config.high_volatility_max_symbols),
    )
    target_weights.update({symbol: high_weight for symbol in high_ranked})
    cash_weight = Decimal(1) - sum(target_weights.values())
    return StrategyResult(
        as_of=snapshot.as_of,
        target_weights=MappingProxyType(dict(sorted(target_weights.items()))),
        cash_weight=cash_weight,
        scores=MappingProxyType(dict(sorted(scores.items()))),
        exclusions=MappingProxyType(dict(sorted(exclusions.items()))),
    )
