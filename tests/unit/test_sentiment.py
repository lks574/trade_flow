from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import MappingProxyType

from trade_flow.data import DailyBar
from trade_flow.db import SentimentRepository, initialize_database
from trade_flow.sentiment import (
    SentimentArticle,
    SentimentObservation,
    aggregate_sentiment,
    collect_shadow_sentiment,
    evaluate_sentiment,
)
from trade_flow.strategy import FactorScore, StrategyResult


def _bar(symbol: str, session: date, close: Decimal) -> DailyBar:
    return DailyBar(
        symbol=symbol,
        session_date=session,
        open=close,
        high=close,
        low=close,
        close=close,
        split_adjusted_open=close,
        split_adjusted_high=close,
        split_adjusted_low=close,
        split_adjusted_close=close,
        volume=100,
        cash_dividend=Decimal(0),
        source="fixture",
        fetched_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_aggregate_distinguishes_missing_from_neutral() -> None:
    session = date(2026, 1, 1)
    missing = aggregate_sentiment("A", session, [], source="fixture")
    neutral = aggregate_sentiment(
        "A",
        session,
        [
            SentimentArticle(
                "A", datetime(2026, 1, 1, tzinfo=UTC), Decimal(0), Decimal(1), "fixture"
            )
        ],
        source="fixture",
    )

    assert missing.score is None
    assert missing.missing_reason == "no_articles"
    assert neutral.score == 0
    assert neutral.missing_reason is None


def test_sentiment_repository_round_trip(tmp_path) -> None:
    database = initialize_database(tmp_path / "trade_flow.db")
    repository = SentimentRepository(database)
    observation = SentimentObservation(
        "A", date(2026, 1, 1), Decimal("0.25"), Decimal("0.8"), 2, "fixture", None
    )

    assert repository.save([observation]) == 1
    assert repository.load(start=date(2026, 1, 1), end=date(2026, 1, 1)) == (observation,)


def test_sentiment_requires_60_sessions_then_calculates_rank_ic() -> None:
    start = date(2026, 1, 1)
    observations = []
    bars = []
    for index in range(61):
        session = start + timedelta(days=index)
        bars.extend(
            [
                _bar("A", session, Decimal(100 + index)),
                _bar("B", session, Decimal(200 - index)),
            ]
        )
        if index < 60:
            observations.extend(
                [
                    SentimentObservation("A", session, Decimal(1), Decimal(1), 1, "fixture", None),
                    SentimentObservation("B", session, Decimal(-1), Decimal(1), 1, "fixture", None),
                ]
            )

    waiting = evaluate_sentiment(observations[:-2], bars, horizons=[1], minimum_sessions=60)
    ready = evaluate_sentiment(observations, bars, horizons=[1], minimum_sessions=60)

    assert waiting.status == "insufficient_observation_period"
    assert ready.status == "ready_for_review"
    assert ready.rank_ic[1] == 1.0
    assert ready.coverage == 1.0


def test_shadow_collector_caps_candidates_and_records_provider_errors() -> None:
    factor = FactorScore(
        Decimal(1),
        Decimal(1),
        Decimal(1),
        Decimal(1),
        Decimal(1),
        Decimal(100),
        Decimal(1),
    )
    result = StrategyResult(
        date(2026, 1, 1),
        MappingProxyType({}),
        Decimal(1),
        MappingProxyType({"A": factor, "B": factor}),
        MappingProxyType({}),
    )

    class FailingProvider:
        source = "fixture"

        def articles(self, symbol, session_date):
            raise RuntimeError("temporary failure")

    observations = collect_shadow_sentiment(
        result,
        date(2026, 1, 1),
        FailingProvider(),
        candidate_limit=1,
    )

    assert len(observations) == 1
    assert observations[0].symbol == "A"
    assert observations[0].missing_reason == "provider_error"
