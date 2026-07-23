"""주간 종목 추천 리포트 (정량 팩터 기반).

trade_flow 전략 엔진의 팩터 점수(모멘텀 percentile·추세·RSI·MACD, 유동성 타이브레이크)로
유니버스를 랭킹해 상위 N을 근거와 함께 출력한다. 자동매매용 top-N 선정과 같은 엔진이며,
여기서는 '추천 리포트'로 순위·점수를 펼친다.

주간 실행 예:  python scripts/recommend.py [--top 15] [--max-symbols 600]

주의: 이것은 기술적 팩터 기반 정량 추천이다. docs/research/의 LLM 펀더멘털·감정 분석
계층은 아직 미구현(향후 추가). 수치는 백테스트/1차 자료로 재검증 후 사용한다.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, "scripts")
import backtest as R  # noqa: E402

from trade_flow.data.sqlite_provider import (  # noqa: E402
    SqliteMarketCalendar,
    SqliteMarketDataProvider,
)
from trade_flow.domain.config import load_config  # noqa: E402
from trade_flow.strategy import signal  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/strategy.toml")
    parser.add_argument("--db", type=Path, default=Path("data/trade_flow.db"))
    parser.add_argument("--universe", default="configs/universe_main.toml")
    parser.add_argument("--start", default="2016-01-01")
    parser.add_argument("--max-symbols", type=int, default=600)
    parser.add_argument("--top", type=int, default=15)
    args = parser.parse_args(argv)

    config = load_config(args.config)
    provider = SqliteMarketDataProvider(args.db)
    calendar = SqliteMarketCalendar(args.db)
    connection = sqlite3.connect(args.db)
    raw_end = date.fromisoformat(
        connection.execute("SELECT MAX(session_date) FROM prices").fetchone()[0]
    )
    start = date.fromisoformat(args.start)
    universe = [m.symbol for m in R.load_universe(args.universe).symbols][: args.max_symbols]

    snapshot, surviving, end, _notes = R._build_clean_snapshot(
        provider, calendar, universe, start=start, raw_end=raw_end, cap_final=True
    )
    result = signal(snapshot, config.strategy, main_symbols=set(surviving))

    ranked = sorted(
        result.scores.items(),
        key=lambda item: (-item[1].total, -item[1].momentum_return, item[0]),
    )
    traded = set(result.target_weights)  # 자동매매가 실제로 담는 상위 N

    print(f"주간 종목 추천 (정량 팩터) — 기준일 {end}, 적격 {len(ranked)}종목 중 상위 {args.top}")
    print("가중치:", dict(config.strategy.factor_weights.__dict__)
          if hasattr(config.strategy.factor_weights, "__dict__") else "")
    print(f"{'순위':>3} {'종목':<7} {'총점':>6} {'모멘텀%':>7} {'모멘텀':>8} "
          f"{'추세':>4} {'RSI':>4} {'MACD':>4} {'일평균거래대금($M)':>14}  매매")
    for rank, (symbol, score) in enumerate(ranked[: args.top], start=1):
        star = "★담음" if symbol in traded else ""
        print(
            f"{rank:>3} {symbol:<7} {float(score.total):>6.3f} "
            f"{float(score.momentum_percentile):>7.2f} {float(score.momentum_return):>+8.2%} "
            f"{int(score.trend):>4} {int(score.rsi):>4} {int(score.macd):>4} "
            f"{float(score.average_dollar_volume) / 1e6:>14,.1f}  {star}"
        )
    print("\n★ = 자동매매 전략이 이번 주 실제로 담는 종목(상위 "
          f"{config.strategy.main_count}). 나머지는 후보 순위.")
    print("주의: 기술적 팩터 기반. 펀더멘털/감정 계층은 미구현(docs/research 참고).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
