from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from math import sqrt

from trade_flow.data import DailyBar
from trade_flow.sentiment.model import SentimentObservation
from trade_flow.strategy.indicators import percentile_ranks


@dataclass(frozen=True)
class SentimentEvaluation:
    status: str
    observed_sessions: int
    coverage: float
    rank_ic: dict[int, float | None]


def _correlation(first: Sequence[Decimal], second: Sequence[Decimal]) -> float | None:
    if len(first) < 2 or len(first) != len(second):
        return None
    first_mean = sum(first) / Decimal(len(first))
    second_mean = sum(second) / Decimal(len(second))
    numerator = sum(
        (left - first_mean) * (right - second_mean)
        for left, right in zip(first, second, strict=True)
    )
    first_variance = sum((value - first_mean) ** 2 for value in first)
    second_variance = sum((value - second_mean) ** 2 for value in second)
    if first_variance == 0 or second_variance == 0:
        return None
    return float(numerator) / sqrt(float(first_variance * second_variance))


def evaluate_sentiment(
    observations: Sequence[SentimentObservation],
    bars: Sequence[DailyBar],
    *,
    horizons: Sequence[int],
    minimum_sessions: int,
) -> SentimentEvaluation:
    if minimum_sessions <= 0 or not horizons:
        raise ValueError("sentiment evaluation parameters must be positive")
    observed_sessions = len({item.session_date for item in observations})
    covered = [item for item in observations if item.score is not None]
    coverage = len(covered) / len(observations) if observations else 0.0
    if observed_sessions < minimum_sessions:
        return SentimentEvaluation(
            "insufficient_observation_period",
            observed_sessions,
            coverage,
            {horizon: None for horizon in horizons},
        )

    histories: dict[str, list[DailyBar]] = defaultdict(list)
    for bar in sorted(bars, key=lambda item: (item.symbol, item.session_date)):
        histories[bar.symbol].append(bar)
    index_by_symbol = {
        symbol: {bar.session_date: index for index, bar in enumerate(history)}
        for symbol, history in histories.items()
    }
    by_date: dict = defaultdict(list)
    for observation in covered:
        by_date[observation.session_date].append(observation)

    result: dict[int, float | None] = {}
    for horizon in horizons:
        daily_ic: list[float] = []
        for session_date, items in sorted(by_date.items()):
            scores: dict[str, Decimal] = {}
            returns: dict[str, Decimal] = {}
            for item in items:
                history = histories.get(item.symbol, [])
                index = index_by_symbol.get(item.symbol, {}).get(session_date)
                if index is None or index + horizon >= len(history) or item.score is None:
                    continue
                scores[item.symbol] = item.score
                returns[item.symbol] = history[index + horizon].split_adjusted_close / history[
                    index
                ].split_adjusted_close - Decimal(1)
            score_ranks = percentile_ranks(scores)
            return_ranks = percentile_ranks(returns)
            symbols = sorted(set(score_ranks) & set(return_ranks))
            correlation = _correlation(
                [score_ranks[symbol] for symbol in symbols],
                [return_ranks[symbol] for symbol in symbols],
            )
            if correlation is not None:
                daily_ic.append(correlation)
        result[horizon] = sum(daily_ic) / len(daily_ic) if daily_ic else None
    return SentimentEvaluation("ready_for_review", observed_sessions, coverage, result)
