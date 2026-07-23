from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256


class DataQualityError(ValueError):
    """Raised when market data is unsafe to use for a trading decision."""


@dataclass(frozen=True)
class DailyBar:
    symbol: str
    session_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    split_adjusted_open: Decimal
    split_adjusted_high: Decimal
    split_adjusted_low: Decimal
    split_adjusted_close: Decimal
    volume: int
    cash_dividend: Decimal
    source: str
    fetched_at: datetime

    def __post_init__(self) -> None:
        if not self.symbol or not self.source:
            raise DataQualityError("bar symbol and source are required")
        if self.fetched_at.tzinfo is None or self.fetched_at.utcoffset() is None:
            raise DataQualityError("fetched_at must be timezone-aware")


@dataclass(frozen=True)
class QualityIssue:
    code: str
    message: str
    symbol: str | None = None
    session_date: date | None = None


@dataclass(frozen=True)
class QualityReport:
    as_of: date
    latest_session: date | None
    checked_bars: int
    issues: tuple[QualityIssue, ...]

    @property
    def is_valid(self) -> bool:
        return not self.issues

    def require_valid(self) -> None:
        if self.issues:
            codes = ", ".join(sorted({issue.code for issue in self.issues}))
            raise DataQualityError(f"market data quality check failed: {codes}")


@dataclass(frozen=True)
class MarketDataSnapshot:
    as_of: date
    prices: tuple[DailyBar, ...]
    quality_report: QualityReport
    data_hash: str


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


def _bar_payload(bar: DailyBar) -> dict[str, object]:
    payload = asdict(bar)
    for field in (
        "open",
        "high",
        "low",
        "close",
        "split_adjusted_open",
        "split_adjusted_high",
        "split_adjusted_low",
        "split_adjusted_close",
        "cash_dividend",
    ):
        payload[field] = _decimal_text(payload[field])  # type: ignore[arg-type]
    payload["session_date"] = bar.session_date.isoformat()
    payload["fetched_at"] = bar.fetched_at.astimezone(UTC).isoformat()
    return payload


def _validate_ohlc(bar: DailyBar, issues: list[QualityIssue]) -> None:
    raw = (bar.open, bar.high, bar.low, bar.close)
    adjusted = (
        bar.split_adjusted_open,
        bar.split_adjusted_high,
        bar.split_adjusted_low,
        bar.split_adjusted_close,
    )
    if any(value <= 0 for value in raw + adjusted):
        issues.append(
            QualityIssue(
                "non_positive_price",
                "OHLC prices must be positive",
                bar.symbol,
                bar.session_date,
            )
        )
    if bar.high < max(bar.open, bar.low, bar.close) or bar.low > min(bar.open, bar.high, bar.close):
        issues.append(
            QualityIssue(
                "invalid_raw_ohlc",
                "raw OHLC range is inverted",
                bar.symbol,
                bar.session_date,
            )
        )
    if bar.split_adjusted_high < max(adjusted) or bar.split_adjusted_low > min(adjusted):
        issues.append(
            QualityIssue(
                "invalid_adjusted_ohlc",
                "split-adjusted OHLC range is inverted",
                bar.symbol,
                bar.session_date,
            )
        )
    if bar.volume < 0:
        issues.append(
            QualityIssue(
                "negative_volume", "volume cannot be negative", bar.symbol, bar.session_date
            )
        )
    if bar.cash_dividend < 0:
        issues.append(
            QualityIssue(
                "negative_dividend",
                "cash dividend cannot be negative",
                bar.symbol,
                bar.session_date,
            )
        )


def _quality_report(
    bars: Sequence[DailyBar],
    *,
    as_of: date,
    expected_sessions: Sequence[date],
    expected_symbols: Iterable[str],
    recent_session_count: int,
) -> QualityReport:
    issues: list[QualityIssue] = []
    keys = [(bar.symbol, bar.session_date) for bar in bars]
    for (symbol, session_date), count in Counter(keys).items():
        if count > 1:
            issues.append(
                QualityIssue(
                    "duplicate_bar", "duplicate canonical symbol/date bar", symbol, session_date
                )
            )

    expected_session_set = set(expected_sessions)
    observed: dict[str, set[date]] = defaultdict(set)
    for bar in bars:
        if bar.session_date > as_of:
            issues.append(
                QualityIssue(
                    "future_bar",
                    "bar is later than snapshot date",
                    bar.symbol,
                    bar.session_date,
                )
            )
        if bar.session_date not in expected_session_set:
            issues.append(
                QualityIssue(
                    "calendar_mismatch",
                    "bar date is not an expected market session",
                    bar.symbol,
                    bar.session_date,
                )
            )
        observed[bar.symbol].add(bar.session_date)
        _validate_ohlc(bar, issues)

    completed_sessions = sorted(session for session in expected_session_set if session <= as_of)
    recent_sessions = set(completed_sessions[-recent_session_count:])
    for symbol in sorted(set(expected_symbols)):
        for missing_date in sorted(recent_sessions - observed[symbol]):
            issues.append(
                QualityIssue(
                    "missing_recent_bar",
                    "expected recent market session is missing",
                    symbol,
                    missing_date,
                )
            )

    # 상장 후 내부 결측(interior_gap): 심볼이 실제로 존재한 구간(첫~마지막 관측 세션) 안에서
    # 빠진 세션은 데이터 공백이다. 상장 전(첫 관측 이전)·상폐 후(마지막 관측 이후) 부재는
    # 정상이므로 제외한다. 세션별 sub-snapshot 검증을 제거한 뒤 이 결측을 잡는 fail-closed 검사.
    for symbol in sorted(set(expected_symbols)):
        symbol_dates = observed[symbol]
        if not symbol_dates:
            continue
        first_seen, last_seen = min(symbol_dates), max(symbol_dates)
        for session_date in completed_sessions:
            if first_seen <= session_date <= last_seen and session_date not in symbol_dates:
                issues.append(
                    QualityIssue(
                        "interior_gap",
                        "expected session missing within symbol's listed interval",
                        symbol,
                        session_date,
                    )
                )

    latest = completed_sessions[-1] if completed_sessions else None
    return QualityReport(
        as_of=as_of,
        latest_session=latest,
        checked_bars=len(bars),
        issues=tuple(issues),
    )


def build_market_data_snapshot(
    bars: Sequence[DailyBar],
    *,
    as_of: date,
    expected_sessions: Sequence[date],
    expected_symbols: Iterable[str],
    recent_session_count: int = 20,
) -> MarketDataSnapshot:
    if recent_session_count <= 0:
        raise ValueError("recent_session_count must be positive")
    ordered = tuple(sorted(bars, key=lambda bar: (bar.symbol, bar.session_date, bar.source)))
    report = _quality_report(
        ordered,
        as_of=as_of,
        expected_sessions=expected_sessions,
        expected_symbols=expected_symbols,
        recent_session_count=recent_session_count,
    )
    payload = json.dumps(
        [_bar_payload(bar) for bar in ordered],
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return MarketDataSnapshot(
        as_of=as_of,
        prices=ordered,
        quality_report=report,
        data_hash=sha256(payload.encode("utf-8")).hexdigest(),
    )
