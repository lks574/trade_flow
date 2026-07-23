"""collect.py의 bar 변환 검증 — yfinance 응답은 이미 분할 조정돼 있다는 계약."""

import sys
from datetime import UTC, datetime
from decimal import Decimal

import pytest

pd = pytest.importorskip("pandas")  # collect extra 없는 환경에서는 스킵

sys.path.insert(0, "scripts")
import collect  # noqa: E402


def _history_with_split():
    """4:1 분할(3번째 세션 ex-date)을 포함한 yfinance 형태의 프레임.

    yfinance(auto_adjust=False)의 OHLC는 이미 분할 조정 값이므로 시계열이 연속이다.
    당시 실거래가는 분할 전 400/408, 분할 후 103/104.
    """
    index = pd.to_datetime(["2026-07-01", "2026-07-02", "2026-07-06", "2026-07-07"])
    return pd.DataFrame(
        {
            "Open": [100.0, 102.0, 103.0, 104.0],
            "High": [101.0, 103.0, 104.0, 105.0],
            "Low": [99.0, 101.0, 102.0, 103.0],
            "Close": [100.0, 102.0, 103.0, 104.0],
            "Volume": [1000, 1100, 4000, 4100],
            "Dividends": [0.0, 0.0, 0.0, 0.0],
            "Stock Splits": [0.0, 0.0, 4.0, 0.0],
        },
        index=index,
    )


def test_adjusted_columns_pass_through_without_second_division() -> None:
    bars = collect._bars_from_history("TEST", _history_with_split(), datetime.now(UTC))

    adjusted = [float(bar.split_adjusted_close) for bar in bars]
    # 이중조정 버그가 있으면 분할 전 값이 100/4=25로 내려가 가짜 점프가 생긴다.
    assert adjusted == [100.0, 102.0, 103.0, 104.0]
    # 연속성: 인접 세션 비율이 분할비(4)로 튀지 않는다.
    for prev, curr in zip(adjusted[:-1], adjusted[1:], strict=True):
        assert 0.9 < curr / prev < 1.1


def test_raw_columns_restore_pre_split_trading_price() -> None:
    bars = collect._bars_from_history("TEST", _history_with_split(), datetime.now(UTC))

    raw = [float(bar.close) for bar in bars]
    # 분할 전 실거래가는 조정가 × 4, ex-date부터는 조정가 그대로.
    assert raw == [400.0, 408.0, 103.0, 104.0]
    assert bars[0].cash_dividend == Decimal(0)


def test_no_split_history_is_identity() -> None:
    frame = _history_with_split()
    frame["Stock Splits"] = 0.0
    bars = collect._bars_from_history("TEST", frame, datetime.now(UTC))
    assert [float(b.close) for b in bars] == [float(b.split_adjusted_close) for b in bars]
