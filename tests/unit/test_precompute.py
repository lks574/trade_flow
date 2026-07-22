from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from trade_flow.backtest.precompute import precompute_factor_series
from trade_flow.data.market import DailyBar
from trade_flow.domain.config import load_config
from trade_flow.strategy.signal import _raw_factors


def _bars(n: int) -> list[DailyBar]:
    start = date(2024, 1, 1)
    bars = []
    prev = Decimal(100)
    for i in range(n):
        # 추세 + 진동 + 주기적 하락으로 SMA200 상/하회를 모두 만든다.
        close = Decimal(100) + Decimal(i) / Decimal(3) + Decimal((i * 7) % 13 - 6)
        if 220 <= i < 235:
            close -= Decimal(30)
        close = close if close > Decimal("1") else Decimal("1")
        hi = max(prev, close) + Decimal(1)
        lo = min(prev, close) - Decimal(1)
        lo = lo if lo > 0 else Decimal("0.5")
        bars.append(
            DailyBar(
                symbol="X",
                session_date=start + timedelta(days=i),
                open=prev,
                high=hi,
                low=lo,
                close=close,
                split_adjusted_open=prev,
                split_adjusted_high=hi,
                split_adjusted_low=lo,
                split_adjusted_close=close,
                volume=1000 + i,
                cash_dividend=Decimal(0),
                source="fixture",
                fetched_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
        prev = close
    return bars


def test_precompute_factor_series_matches_raw_factors_on_every_prefix() -> None:
    config = load_config("configs/strategy.toml").strategy
    bars = _bars(300)
    series = precompute_factor_series(bars, config)

    # 모든 적격 인덱스에서 슬라이스 재계산과 bit-identical 이어야 한다.
    saw_eligible = False
    saw_below_sma = False
    for i in range(config.minimum_price_days - 1, len(bars)):
        expected = _raw_factors(bars[: i + 1], config)
        assert series[i] == expected, f"mismatch at index {i}"
        if expected is None:
            saw_below_sma = True
        else:
            saw_eligible = True
    # 픽스처가 두 경로(적격/SMA 하회)를 모두 지나야 검증이 의미 있다.
    assert saw_eligible and saw_below_sma


def test_precompute_all_none_when_below_minimum_history() -> None:
    config = load_config("configs/strategy.toml").strategy
    bars = _bars(config.minimum_price_days - 1)
    assert precompute_factor_series(bars, config) == [None] * len(bars)
