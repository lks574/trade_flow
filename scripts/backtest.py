"""grade-C 10년 백테스트 러너 (data/trade_flow.db 기반).

핵심 처리:
- A(데이터 하이지): OHLC 위반 바 제외. 미완료 최종 세션(꼬리의 불량 세션)은 end에서 제외.
  잔여 불량 바를 가진 심볼은 유니버스에서 제외(로깅). require_valid 통과 보장.
- C(상장일 이질성 회피): --min-listed-by 이전부터 존재하는 장수 종목만 사용해
  세션별 sub-snapshot의 missing_recent_bar 중단을 피한다.
- 레짐: provider.regime_inputs -> build_regime_states.

성능 경고: 현재 엔진은 세션마다 지표를 전체 history로 재계산(O(N^2))한다. 축소
유니버스에서만 실용적이며, 전체 유니버스는 증분 지표 리팩터(별도 작업) 후에 실행한다.

Usage:
  python scripts/backtest.py --max-symbols 12 --quick          # 단일 시나리오(빠름)
  python scripts/backtest.py --max-symbols 12 --out backtests/gradeC_12.json
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import asdict
from datetime import date
from decimal import Decimal
from pathlib import Path

from trade_flow.backtest import run_backtest
from trade_flow.data import build_market_data_snapshot, load_universe
from trade_flow.data.market import DailyBar, MarketDataSnapshot
from trade_flow.data.sqlite_provider import SqliteMarketCalendar, SqliteMarketDataProvider
from trade_flow.domain.config import load_config
from trade_flow.risk import RegimePolicy, build_regime_states
from trade_flow.validation.metrics import calculate_metrics
from trade_flow.validation.report import evaluate_scenarios


def _ohlc_ok(bar: DailyBar) -> bool:
    return (
        bar.open > 0
        and bar.high > 0
        and bar.low > 0
        and bar.close > 0
        and bar.high >= max(bar.open, bar.low, bar.close)
        and bar.low <= min(bar.open, bar.high, bar.close)
        and bar.split_adjusted_high
        >= max(bar.split_adjusted_open, bar.split_adjusted_low, bar.split_adjusted_close)
        and bar.split_adjusted_low
        <= min(bar.split_adjusted_open, bar.split_adjusted_high, bar.split_adjusted_close)
    )


def _long_lived(db: Path, listed_by: date) -> list[str]:
    with sqlite3.connect(db) as connection:
        rows = connection.execute(
            "SELECT symbol FROM prices GROUP BY symbol "
            "HAVING MIN(session_date) <= ? ORDER BY symbol",
            [listed_by.isoformat()],
        ).fetchall()
    return [row[0] for row in rows]


def _build_clean_snapshot(
    provider: SqliteMarketDataProvider,
    calendar: SqliteMarketCalendar,
    symbols: list[str],
    *,
    start: date,
    raw_end: date,
    cap_final: bool = True,
) -> tuple[MarketDataSnapshot, list[str], date, list[str]]:
    """유효한 top-level 스냅샷을 만든다. 불량 바를 가진 심볼을 드롭한 뒤 재시도한다.

    cap_final=True: 불량 최종 세션을 end에서 제외(종목 최대 보존, 최신일 손실).
    cap_final=False: end를 유지하고 불량 최종 바를 가진 종목을 드롭(최신일 보존).
    evaluate_scenarios는 minimum_backtest_years 때문에 최신일 보존이 필요하다.
    """
    notes: list[str] = []
    loaded: dict[str, list[DailyBar]] = {}
    for symbol in symbols:
        loaded[symbol] = list(provider.daily_bars(symbol, start, raw_end))

    end = raw_end
    if cap_final:
        # 꼬리의 불량 세션(미완료 최종 세션 등)을 end에서 제외.
        bad_dates = {
            bar.session_date
            for bars in loaded.values()
            for bar in bars
            if not _ohlc_ok(bar)
        }
        calendar_sessions = [s for s in calendar.sessions(start, raw_end)]
        while calendar_sessions and end in bad_dates:
            calendar_sessions.pop()
            end = calendar_sessions[-1] if calendar_sessions else start
        if end != raw_end:
            notes.append(f"end capped {raw_end} -> {end} (미완료/불량 최종 세션 제외)")

    surviving = list(symbols)
    for _ in range(len(symbols) + 1):
        sessions = [s for s in calendar.sessions(start, end)]
        session_set = set(sessions)
        bars: list[DailyBar] = []
        dropped_bad: set[str] = set()
        for symbol in surviving:
            for bar in loaded[symbol]:
                if bar.session_date not in session_set:
                    continue
                if not _ohlc_ok(bar):
                    dropped_bad.add(symbol)
                    continue
                bars.append(bar)
        surviving = [s for s in surviving if s not in dropped_bad]
        if dropped_bad:
            notes.append(f"불량 바 보유로 심볼 제외: {sorted(dropped_bad)}")
            continue
        snapshot = build_market_data_snapshot(
            bars, as_of=sessions[-1], expected_sessions=sessions, expected_symbols=set(surviving)
        )
        if snapshot.quality_report.is_valid:
            return snapshot, surviving, end, notes
        # 잔여 이슈(대개 missing_recent_bar)의 원인 심볼을 드롭하고 재시도.
        offenders = {
            issue.symbol
            for issue in snapshot.quality_report.issues
            if issue.symbol is not None
        }
        if not offenders:
            snapshot.quality_report.require_valid()  # 원인 불명 -> 명확히 실패
        notes.append(
            f"품질 이슈로 심볼 제외: {sorted(offenders)} "
            f"({sorted({i.code for i in snapshot.quality_report.issues})})"
        )
        surviving = [s for s in surviving if s not in offenders]
    raise RuntimeError("clean snapshot을 구성하지 못했습니다")


def _summary(report_obj) -> str:
    lines = ["scenario(cost/policy): total_ret  cagr  mdd  sharpe  calmar  turnover  trades"]
    for sc in report_obj.scenarios:
        m = sc.metrics
        lines.append(
            f"  {sc.transaction_cost_bps:>2}bp/{sc.regime_policy:<9}: "
            f"{m.total_return:+.3f}  {m.cagr:+.3f}  {m.maximum_drawdown:+.3f}  "
            f"{m.sharpe:+.2f}  {m.calmar:+.2f}  {m.turnover:.2f}  {m.trade_count}"
        )
    lines.append("benchmarks:")
    for b in report_obj.benchmarks:
        m = b.metrics
        lines.append(
            f"  {b.name}({b.transaction_cost_bps}bp): "
            f"cagr={m.cagr:+.3f} mdd={m.maximum_drawdown:+.3f}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("data/trade_flow.db"))
    parser.add_argument("--config", type=Path, default=Path("configs/strategy.toml"))
    parser.add_argument("--universe", type=Path, default=Path("configs/universe_main.toml"))
    parser.add_argument(
        "--high-vol", type=Path, default=Path("configs/universe_high_volatility.toml")
    )
    parser.add_argument("--max-symbols", type=int, default=12)
    parser.add_argument("--symbols", type=str, default=None, help="쉼표 구분 심볼(직접 지정)")
    parser.add_argument("--min-listed-by", type=str, default="2016-07-25")
    parser.add_argument("--start", type=str, default="2016-01-01")
    parser.add_argument("--end", type=str, default=None, help="기본: DB 최신 세션")
    parser.add_argument("--initial-cash", type=str, default="20000000")
    parser.add_argument("--quick", action="store_true", help="단일 시나리오(15bp/BUY_BLOCK)만")
    parser.add_argument(
        "--rebalance-band",
        type=str,
        default="0",
        help="리서치 토글(quick 모드): 비중 드리프트가 이 값 이내면 재조정 생략",
    )
    parser.add_argument(
        "--hysteresis",
        type=int,
        default=0,
        help="리서치 토글(quick 모드): 보유 종목을 top-(N+이값) 이내면 유지(선정 로테이션 감소)",
    )
    parser.add_argument(
        "--rebalance-every",
        type=int,
        default=1,
        help="리서치 토글(quick 모드): 신호 적격 세션 k개마다 리밸런스(1=일일, 5≈주간, 21≈월간)",
    )
    parser.add_argument("--cost-bps", type=int, default=15, help="quick 모드 편도 비용(bp)")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    config = load_config(str(args.config))
    provider = SqliteMarketDataProvider(args.db)
    calendar = SqliteMarketCalendar(args.db)
    start = date.fromisoformat(args.start)
    listed_by = date.fromisoformat(args.min_listed_by)
    with sqlite3.connect(args.db) as connection:
        raw_end = date.fromisoformat(
            connection.execute("SELECT MAX(session_date) FROM prices").fetchone()[0]
        )
    if args.end:
        raw_end = date.fromisoformat(args.end)

    long_lived = set(_long_lived(args.db, listed_by))
    main_universe = load_universe(args.universe)
    high_universe = load_universe(args.high_vol)
    main_candidates = [m.symbol for m in main_universe.symbols if m.symbol in long_lived]
    high_candidates = [m.symbol for m in high_universe.symbols if m.symbol in long_lived]

    if args.symbols:
        selected_main = [s.strip().upper() for s in args.symbols.split(",")]
    else:
        selected_main = main_candidates[: args.max_symbols]
    # high-vol 슬리브도 장수 종목이면 포함(스냅샷에 로드되어야 스코어링 가능).
    selected = list(dict.fromkeys([*selected_main, *high_candidates]))

    snapshot, surviving, end, notes = _build_clean_snapshot(
        provider, calendar, selected, start=start, raw_end=raw_end, cap_final=args.quick
    )
    surviving_set = set(surviving)
    main_symbols = {s for s in selected_main if s in surviving_set}
    high_symbols = {s for s in high_candidates if s in surviving_set} - main_symbols

    regime_inputs = provider.regime_inputs(start, end)
    regime_states = build_regime_states(regime_inputs, config.risk)

    print(f"기간: {start} ~ {end}")
    print(f"세션수: {len({b.session_date for b in snapshot.prices})}, bars: {len(snapshot.prices)}")
    print(f"main 심볼({len(main_symbols)}): {sorted(main_symbols)}")
    print(f"high-vol 심볼({len(high_symbols)}): {sorted(high_symbols)}")
    print(f"regime states: {len(regime_states)}, data_hash: {snapshot.data_hash[:12]}")
    for note in notes:
        print(f"  note: {note}")

    initial_cash = Decimal(args.initial_cash)

    if args.quick:
        result = run_backtest(
            snapshot,
            config,
            main_symbols=main_symbols,
            high_volatility_symbols=high_symbols,
            initial_cash=initial_cash,
            transaction_cost_bps=args.cost_bps,
            regime_states=regime_states,
            regime_policy=RegimePolicy.BUY_BLOCK,
            rebalance_band=Decimal(args.rebalance_band),
            selection_hysteresis=args.hysteresis,
            rebalance_every=args.rebalance_every,
        )
        metrics = calculate_metrics(result)
        print(f"\n[quick {args.cost_bps}bp/BUY_BLOCK/every={args.rebalance_every}]")
        for key, value in asdict(metrics).items():
            print(f"  {key}: {value}")
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(asdict(metrics), indent=2, default=str))
            print(f"\n저장: {args.out}")
        return 0

    report = evaluate_scenarios(
        snapshot,
        config,
        main_symbols=main_symbols,
        high_volatility_symbols=high_symbols,
        initial_cash=initial_cash,
        regime_states=regime_states,
    )
    print("\n" + _summary(report))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report.to_json())
        print(f"\n저장: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
