from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Protocol

from trade_flow.sentiment.model import (
    SentimentArticle,
    SentimentObservation,
    aggregate_sentiment,
    shadow_candidates,
)
from trade_flow.strategy import StrategyResult


class SentimentProvider(Protocol):
    @property
    def source(self) -> str: ...

    def articles(self, symbol: str, session_date: date) -> Sequence[SentimentArticle]: ...


def collect_shadow_sentiment(
    result: StrategyResult,
    session_date: date,
    provider: SentimentProvider,
    *,
    candidate_limit: int,
) -> tuple[SentimentObservation, ...]:
    observations: list[SentimentObservation] = []
    for symbol in shadow_candidates(result, candidate_limit):
        try:
            articles = provider.articles(symbol, session_date)
        except Exception:
            observations.append(
                SentimentObservation(
                    symbol=symbol,
                    session_date=session_date,
                    score=None,
                    relevance=None,
                    article_count=0,
                    source=provider.source,
                    missing_reason="provider_error",
                )
            )
            continue
        observations.append(
            aggregate_sentiment(
                symbol,
                session_date,
                articles,
                source=provider.source,
            )
        )
    return tuple(observations)
