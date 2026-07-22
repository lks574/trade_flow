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


def _adjust(value: Decimal, divisor: Decimal) -> Decimal:
    return (value / divisor).quantize(_CENTS)


def _bars_from_history(symbol: str, history, fetched_at: datetime) -> list[DailyBar]:
    ratios = [_dec(value) if value else Decimal(1) for value in history["Stock Splits"]]
    divisors = split_adjustment_divisors(ratios)
    bars: list[DailyBar] = []
    for (timestamp, row), divisor in zip(history.iterrows(), divisors, strict=True):
        raw_open, raw_high = _dec(row["Open"]), _dec(row["High"])
        raw_low, raw_close = _dec(row["Low"]), _dec(row["Close"])
        bars.append(
            DailyBar(
                symbol=symbol,
                session_date=timestamp.date(),
                open=raw_open,
                high=raw_high,
                low=raw_low,
                close=raw_close,
                split_adjusted_open=_adjust(raw_open, divisor),
                split_adjusted_high=_adjust(raw_high, divisor),
                split_adjusted_low=_adjust(raw_low, divisor),
                split_adjusted_close=_adjust(raw_close, divisor),
                volume=int(row["Volume"]),
                cash_dividend=_dec(row.get("Dividends", 0) or 0),
                source=SOURCE,
                fetched_at=fetched_at,
            )
        )
    return bars


def collect_prices(config: Path, db: Path, years: int) -> None:
    import yfinance as yf  # lazy: collect extra only

    universe = load_universe(config)
    mappings = universe.symbols
    repository = PriceRepository(db)
    fetched_at = datetime.now(UTC)
    period = f"{years}y"
    written = 0
    for index, mapping in enumerate(mappings, start=1):
        history = yf.Ticker(mapping.provider_symbol).history(
            period=period, auto_adjust=False, actions=True
        )
        if history.empty:
            print(f"[{index}/{len(mappings)}] {mapping.symbol}: no data, skipped")
            continue
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
    parser.add_argument("--skip-prices", action="store_true")
    parser.add_argument("--skip-regime", action="store_true")
    args = parser.parse_args(argv)

    initialize_database(args.db)
    if not args.skip_prices:
        collect_prices(args.config, args.db, args.years)
    if not args.skip_regime:
        collect_regime(args.db)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
