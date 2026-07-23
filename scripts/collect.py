"""Collect daily bars for the universe plus VIX/WTI regime closes into the SQLite DB.

- Prices: split-adjusted OHLC (dividends kept separate as cash_dividend) via yfinance.
- Regime: ^VIX and CL=F closes over the longest available history.

All writes are idempotent (ON CONFLICT upsert), so re-running is safe.

Usage:  python scripts/collect.py [--db data/trade_flow.db] [--config configs/universe_main.toml]
                                  [--years 10] [--skip-prices] [--skip-regime]
Requires the `collect` extra:  pip install -e '.[collect]'
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from trade_flow.data import DailyBar, load_universe, split_adjustment_divisors
from trade_flow.db import MarketContextRepository, PriceRepository, initialize_database
from trade_flow.db.market_context import VIX, WTI

SOURCE = "yfinance"
REGIME_TICKERS = {VIX: "^VIX", WTI: "CL=F"}


_CENTS = Decimal("0.000001")


def _dec(value: object) -> Decimal:
    return Decimal(str(value))


def _restore_raw(value: Decimal, divisor: Decimal) -> Decimal:
    return (value * divisor).quantize(_CENTS)


def _bars_from_history(symbol: str, history, fetched_at: datetime) -> list[DailyBar]:
    # yfinance emits NaN rows on boundary/no-trade days; drop them so they never
    # reach the DB (a NaN bar is not a valid observation).
    history = history.dropna(subset=["Open", "High", "Low", "Close", "Volume"])
    ratios = [_dec(value) if value else Decimal(1) for value in history["Stock Splits"]]
    divisors = split_adjustment_divisors(ratios)
    # 주의: yfinance는 auto_adjust=False에서도 OHLC를 이미 분할 조정해 반환한다
    # (배당만 미반영). 과거에 이 값을 divisor로 한 번 더 나눠 이중조정되는 버그가
    # 있었다(분할일마다 조정 시계열에 가짜 점프). 조정 컬럼은 응답을 그대로 쓰고,
    # 원시(당시 실거래) 가격은 미래 분할비의 곱(divisor)을 곱해 역산한다.
    bars: list[DailyBar] = []
    for (timestamp, row), divisor in zip(history.iterrows(), divisors, strict=True):
        adj_open, adj_high = _dec(row["Open"]), _dec(row["High"])
        adj_low, adj_close = _dec(row["Low"]), _dec(row["Close"])
        bars.append(
            DailyBar(
                symbol=symbol,
                session_date=timestamp.date(),
                open=_restore_raw(adj_open, divisor),
                high=_restore_raw(adj_high, divisor),
                low=_restore_raw(adj_low, divisor),
                close=_restore_raw(adj_close, divisor),
                split_adjusted_open=adj_open.quantize(_CENTS),
                split_adjusted_high=adj_high.quantize(_CENTS),
                split_adjusted_low=adj_low.quantize(_CENTS),
                split_adjusted_close=adj_close.quantize(_CENTS),
                volume=int(row["Volume"]),
                cash_dividend=_dec(row.get("Dividends", 0) or 0),
                source=SOURCE,
                fetched_at=fetched_at,
            )
        )
    return bars


def collect_prices(config: Path, db: Path, years: int, period: str | None = None) -> None:
    import yfinance as yf  # lazy: collect extra only

    universe = load_universe(config)
    mappings = universe.symbols
    repository = PriceRepository(db)
    fetched_at = datetime.now(UTC)
    # period 지정 시 증분 수집(예 "10d") — 일일 운영용. 미지정 시 전체 이력(years).
    full_period = f"{years}y"
    period = period or full_period
    written = 0
    for index, mapping in enumerate(mappings, start=1):
        history = yf.Ticker(mapping.provider_symbol).history(
            period=period, auto_adjust=False, actions=True
        )
        if history.empty:
            print(f"[{index}/{len(mappings)}] {mapping.symbol}: no data, skipped")
            continue
        # 증분 창에서 분할이 감지되면 yfinance가 전체 이력을 재조정했다는 뜻이므로,
        # 과거 DB 행과 스케일이 어긋나기 전에 해당 종목 전체 이력을 재수집한다(H5).
        if period != full_period and (history["Stock Splits"] != 0).any():
            print(f"[{index}/{len(mappings)}] {mapping.symbol}: 분할 감지 -> 전체 재수집")
            history = yf.Ticker(mapping.provider_symbol).history(
                period=full_period, auto_adjust=False, actions=True
            )
        bars = _bars_from_history(mapping.symbol, history, fetched_at)
        written += repository.save_bars(bars)
        print(f"[{index}/{len(mappings)}] {mapping.symbol}: {len(bars)} bars")
    print(f"prices: wrote/updated {written} rows across {len(mappings)} symbols")


def collect_regime(db: Path) -> None:
    import yfinance as yf  # lazy: collect extra only

    repository = MarketContextRepository(db)
    fetched_at = datetime.now(UTC)
    for indicator, ticker in REGIME_TICKERS.items():
        history = yf.Ticker(ticker).history(period="max", auto_adjust=False)
        closes = [
            (timestamp.date(), _dec(close))
            for timestamp, close in history["Close"].dropna().items()
        ]
        written = repository.save(
            indicator=indicator, closes=closes, source=SOURCE, fetched_at=fetched_at
        )
        print(f"regime {indicator} ({ticker}): wrote/updated {written} of {len(closes)} closes")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("data/trade_flow.db"))
    parser.add_argument("--config", type=Path, default=Path("configs/universe_main.toml"))
    parser.add_argument("--years", type=int, default=10)
    parser.add_argument(
        "--period",
        default=None,
        help="증분 수집 기간(예: 10d). 미지정 시 --years 전체 이력. 일일 운영은 짧게.",
    )
    parser.add_argument("--skip-prices", action="store_true")
    parser.add_argument("--skip-regime", action="store_true")
    args = parser.parse_args(argv)

    initialize_database(args.db)
    if not args.skip_prices:
        collect_prices(args.config, args.db, args.years, period=args.period)
    if not args.skip_regime:
        collect_regime(args.db)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
