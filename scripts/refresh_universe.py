"""Refresh the trading universe from the Wikipedia S&P 500 constituents table.

Writes a grade-C universe config: the *current* constituent list applied to all
history, which is survivorship-biased by construction (grade C = bootstrap only).
Point-in-time membership (grade A/B) is a separate, later concern.

Usage:  python scripts/refresh_universe.py [--out configs/universe_main.toml]
Requires the `collect` extra:  pip install -e '.[collect]'
"""

from __future__ import annotations

import argparse
from datetime import date
from io import StringIO
from pathlib import Path
from urllib.request import Request, urlopen

WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
SOURCE = "wikipedia-sp500"


def fetch_symbols() -> list[str]:
    import pandas as pd  # lazy: collect extra only

    request = Request(WIKI_URL, headers={"User-Agent": "trade-flow/0.1 (universe refresh)"})
    with urlopen(request, timeout=30) as response:  # noqa: S310 - fixed trusted URL
        html = response.read().decode("utf-8")
    table = pd.read_html(StringIO(html), attrs={"id": "constituents"})[0]
    return sorted({str(symbol).strip().upper() for symbol in table["Symbol"]})


def render_toml(symbols: list[str]) -> str:
    lines = [
        'grade = "C"',
        f'description = "S&P 500 constituents from Wikipedia (current snapshot, '
        f'survivorship-biased); refreshed {date.today().isoformat()}"',
        "",
    ]
    for symbol in symbols:
        # yfinance uses '-' where Wikipedia/canonical uses '.' (e.g. BRK.B -> BRK-B).
        provider = symbol.replace(".", "-")
        lines += [
            "[[symbols]]",
            f'symbol = "{symbol}"',
            f'provider_symbol = "{provider}"',
            f'source = "{SOURCE}"',
            "",
        ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("configs/universe_main.toml"))
    args = parser.parse_args(argv)

    symbols = fetch_symbols()
    if not symbols:
        raise SystemExit("no symbols parsed from Wikipedia; aborting")
    args.out.write_text(render_toml(symbols), encoding="utf-8")
    print(f"wrote {len(symbols)} symbols to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
