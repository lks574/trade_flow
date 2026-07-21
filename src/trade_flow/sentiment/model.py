from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from trade_flow.strategy import StrategyResult


@dataclass(frozen=True)
class SentimentArticle:
    symbol: str
    published_at: datetime
    score: Decimal
    relevance: Decimal
    source: str

    def __post_init__(self) -> None:
        if self.published_at.tzinfo is None or self.published_at.utcoffset() is None:
            raise ValueError("published_at must be timezone-aware")
        if not Decimal(-1) <= self.score <= Decimal(1):
            raise ValueError("article sentiment score must be in [-1, 1]")
        if not Decimal(0) <= self.relevance <= Decimal(1):
            raise ValueError("article relevance must be in [0, 1]")


@dataclass(frozen=True)
class SentimentObservation:
    symbol: str
    session_date: date
    score: Decimal | None
    relevance: Decimal | None
    article_count: int
    source: str
    missing_reason: str | None

    def __post_init__(self) -> None:
        if self.article_count < 0:
            raise ValueError("article_count cannot be negative")
        if self.score is None and not self.missing_reason:
            raise ValueError("missing sentiment requires a reason")
        if self.score is not None:
            if self.missing_reason is not None or self.article_count <= 0:
                raise ValueError("observed sentiment requires articles and no missing reason")
            if not Decimal(-1) <= self.score <= Decimal(1):
                raise ValueError("sentiment score must be in [-1, 1]")


def aggregate_sentiment(
    symbol: str,
    session_date: date,
    articles: Sequence[SentimentArticle],
    *,
    source: str,
) -> SentimentObservation:
    matching = [article for article in articles if article.symbol == symbol]
    if not matching:
        return SentimentObservation(symbol, session_date, None, None, 0, source, "no_articles")
    total_relevance = sum(article.relevance for article in matching)
    if total_relevance == 0:
        return SentimentObservation(
            symbol,
            session_date,
            None,
            Decimal(0),
            len(matching),
            source,
            "no_relevant_articles",
        )
    score = sum(article.score * article.relevance for article in matching) / total_relevance
    average_relevance = total_relevance / Decimal(len(matching))
    return SentimentObservation(
        symbol,
        session_date,
        score,
        average_relevance,
        len(matching),
        source,
        None,
    )


def shadow_candidates(result: StrategyResult, limit: int) -> tuple[str, ...]:
    if limit <= 0:
        raise ValueError("shadow candidate limit must be positive")
    ranked = sorted(
        result.scores,
        key=lambda symbol: (
            -result.scores[symbol].total,
            -result.scores[symbol].momentum_return,
            -result.scores[symbol].average_dollar_volume,
            symbol,
        ),
    )
    return tuple(ranked[:limit])
