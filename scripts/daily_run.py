"""일일 리밸런스 오케스트레이터 (Phase 2c).

파이프라인: DB 시장데이터 -> 스냅샷 -> signal(보유종목 반영 hysteresis) -> 위험정책 ->
주문계획(no-trade band). 기본은 DRY-RUN(주문 제출 안 함): 라이브 KIS 계좌 상태를 읽어
'오늘 어떤 주문을 낼지'만 계산·출력한다.

  KIS_ENV=mock 로 .env를 설정한 뒤:
    set -a && source .env && set +a && python scripts/daily_run.py [--max-symbols N]

--execute(라이브 제출)는 미국 정규장 개장 + SafetyContext/저장소 연동이 필요하며 별도
확인 후 사용한다(현재 스크립트는 dry-run만).
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, "scripts")
import backtest as R  # noqa: E402

from trade_flow.broker import KisApiError, KisBroker, KisConfigError, build_client  # noqa: E402
from trade_flow.data.sqlite_provider import (  # noqa: E402
    SqliteMarketCalendar,
    SqliteMarketDataProvider,
)
from trade_flow.domain.config import load_config  # noqa: E402
from trade_flow.execution.planner import plan_orders  # noqa: E402
from trade_flow.risk import RegimePolicy, apply_risk_policy, build_regime_states  # noqa: E402
from trade_flow.strategy import signal  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/strategy.toml")
    parser.add_argument("--db", type=Path, default=Path("data/trade_flow.db"))
    parser.add_argument("--universe", default="configs/universe_main.toml")
    parser.add_argument("--start", default="2016-01-01")
    parser.add_argument("--max-symbols", type=int, default=600)
    parser.add_argument("--policy", choices=["buy_block", "equity_cap"], default="buy_block")
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

    print("스냅샷 구성 중...")
    snapshot, surviving, end, notes = R._build_clean_snapshot(
        provider, calendar, universe, start=start, raw_end=raw_end, cap_final=True
    )
    for note in notes:
        print("  note:", note)
    print(f"유니버스 {len(surviving)}종목, 최종 세션 {end}")

    try:
        broker = KisBroker(build_client())
        account = broker.account_snapshot()
    except (KisConfigError, KisApiError) as error:
        print(f"[KIS 오류] {error}", file=sys.stderr)
        return 2

    held = frozenset(account.positions)
    print(
        f"계좌: NAV ${float(account.nav):,.0f}, 현금 ${float(account.cash):,.0f}, "
        f"보유 {len(held)}종목"
    )
    print(f"selection_hysteresis={config.strategy.selection_hysteresis}, "
          f"rebalance_band={config.execution.rebalance_band}")

    strategy_result = signal(
        snapshot,
        config.strategy,
        main_symbols=set(surviving),
        held_symbols=held,
    )
    regime_states = build_regime_states(provider.regime_inputs(start, end), config.risk)
    state = regime_states.get(end)
    if state is None:
        print("경고: 최종 세션 레짐 상태 없음 -> 매수 차단(fail-closed)")
    policy = RegimePolicy(args.policy)
    daily_return = Decimal(0)  # dry-run: 전일 대비 수익률 미적용
    risk_target = apply_risk_policy(
        strategy_result, account,
        state or _missing_regime(end),
        config.risk, regime_policy=policy, daily_return=daily_return,
    )

    targets = {s: w for s, w in risk_target.target_weights.items() if w > 0}
    selected = ", ".join(f"{s}={float(w):.1%}" for s, w in sorted(targets.items()))
    print(f"\n선정 {len(targets)}종목: {selected}")

    print("시세 조회 중(선정+보유)...")
    symbols = sorted(set(targets) | set(held))
    quotes = {}
    for sym in symbols:
        try:
            quotes[sym] = broker.quote(sym)
        except KisApiError as error:
            print(f"  {sym} 시세 실패: {error}")

    strategy_weights = strategy_result.target_weights
    risk_reduced = frozenset(
        s for s, w in risk_target.target_weights.items()
        if w < strategy_weights.get(s, Decimal(0))
    )
    plan = plan_orders(
        account, risk_target.target_weights, quotes,
        trading_date=end, strategy_version=config.strategy_version,
        cash_buffer_fraction=config.strategy.cash_buffer_weight, config=config.execution,
        risk_reduced_symbols=risk_reduced,
    )
    print("\n=== DRY-RUN 주문계획 (제출 안 함) ===")
    if not plan.intents:
        print("  (주문 없음)")
    for intent in plan.intents:
        print(f"  {intent.side.upper()} {intent.symbol} x{intent.quantity} @ {intent.limit_price}")
    if plan.drift:
        print("  drift:", dict(plan.drift))
    print("\n라이브 제출(execute_rebalance)은 미국 정규장 개장 + 별도 확인 후 진행합니다.")
    return 0


def _missing_regime(session_date):
    from trade_flow.risk import RegimeState

    return RegimeState(session_date, True, False, 0, ("regime_missing",))


if __name__ == "__main__":
    raise SystemExit(main())
