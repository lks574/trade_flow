from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from trade_flow.data import DailyBar, DataQualityError, build_market_data_snapshot


def _bar(symbol: str, session_date: date, *, high: str = "11", volume: int = 100) -> DailyBar:
    return DailyBar(
        symbol=symbol,
        session_date=session_date,
        open=Decimal("10"),
        high=Decimal(high),
        low=Decimal("9"),
        close=Decimal("10.5"),
        split_adjusted_open=Decimal("10"),
        split_adjusted_high=Decimal(high),
        split_adjusted_low=Decimal("9"),
        split_adjusted_close=Decimal("10.5"),
        volume=volume,
        cash_dividend=Decimal("0"),
        source="fixture",
        fetched_at=datetime(2026, 7, 21, tzinfo=UTC),
    )


def test_snapshot_is_deterministic_and_rejects_future_data() -> None:
    as_of = date(2026, 7, 20)
    sessions = [as_of - timedelta(days=1), as_of]
    bars = [_bar("AAPL", session) for session in reversed(sessions)]

    first = build_market_data_snapshot(
        bars,
        as_of=as_of,
        expected_sessions=sessions,
        expected_symbols=["AAPL"],
        recent_session_count=2,
    )
    second = build_market_data_snapshot(
        list(reversed(bars)),
        as_of=as_of,
        expected_sessions=sessions,
        expected_symbols=["AAPL"],
        recent_session_count=2,
    )

    assert first.data_hash == second.data_hash
    first.quality_report.require_valid()

    future = build_market_data_snapshot(
        [*bars, _bar("AAPL", as_of + timedelta(days=1))],
        as_of=as_of,
        expected_sessions=[*sessions, as_of + timedelta(days=1)],
        expected_symbols=["AAPL"],
        recent_session_count=2,
    )
    with pytest.raises(DataQualityError, match="future_bar"):
        future.quality_report.require_valid()


def test_quality_report_detects_duplicate_missing_and_invalid_bars() -> None:
    sessions = [date(2026, 7, 17), date(2026, 7, 20)]
    invalid = _bar("AAPL", sessions[0], high="8", volume=-1)
    snapshot = build_market_data_snapshot(
        [invalid, invalid],
        as_of=sessions[-1],
        expected_sessions=sessions,
        expected_symbols=["AAPL"],
        recent_session_count=2,
    )

    codes = {issue.code for issue in snapshot.quality_report.issues}
    assert {"duplicate_bar", "invalid_raw_ohlc", "negative_volume", "missing_recent_bar"} <= codes


def test_daily_bar_requires_timezone_aware_fetch_time() -> None:
    with pytest.raises(DataQualityError, match="timezone-aware"):
        bar = _bar("AAPL", date(2026, 7, 20))
        DailyBar(**{**bar.__dict__, "fetched_at": datetime(2026, 7, 21)})


def test_snapshot_rejects_two_sources_for_same_canonical_session() -> None:
    session = date(2026, 7, 20)
    first = _bar("AAPL", session)
    second = DailyBar(**{**first.__dict__, "source": "another-provider"})

    snapshot = build_market_data_snapshot(
        [first, second],
        as_of=session,
        expected_sessions=[session],
        expected_symbols=["AAPL"],
        recent_session_count=1,
    )

    with pytest.raises(DataQualityError, match="duplicate_bar"):
        snapshot.quality_report.require_valid()


def test_quality_report_flags_interior_gap_not_pre_listing_absence() -> None:
    # 5 세션. GAP 심볼은 세션2가 내부 결측(상장 후 공백) -> interior_gap.
    # LATE 심볼은 세션2부터 시작(상장 전 부재) -> interior_gap 아님.
    sessions = [date(2026, 1, 1) + timedelta(days=index) for index in range(5)]
    as_of = sessions[-1]
    bars = []
    for index in (0, 1, 3, 4):
        bars.append(_bar("GAP", sessions[index]))
    for index in (2, 3, 4):
        bars.append(_bar("LATE", sessions[index]))

    snapshot = build_market_data_snapshot(
        bars,
        as_of=as_of,
        expected_sessions=sessions,
        expected_symbols=["GAP", "LATE"],
        recent_session_count=1,  # 마지막 세션만 검사 -> 둘 다 존재, missing_recent 없음
    )

    gaps = [
        issue
        for issue in snapshot.quality_report.issues
        if issue.code == "interior_gap"
    ]
    assert len(gaps) == 1
    assert gaps[0].symbol == "GAP"
    assert gaps[0].session_date == sessions[2]
    # LATE는 상장 전 부재이므로 interior_gap 없음.
    assert all(issue.symbol != "LATE" for issue in gaps)
