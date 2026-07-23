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
from trade_flow.db import OrderRepository, RunRepository, initialize_database  # noqa: E402
from trade_flow.domain.config import load_config  # noqa: E402
from trade_flow.execution import execute_rebalance  # noqa: E402
from trade_flow.execution.planner import plan_orders  # noqa: E402
from trade_flow.operations import (  # noqa: E402
    FanoutNotifier,
    LogNotifier,
    NavHistory,
    Notification,
    Notifier,
    TelegramNotifier,
    within_us_market_hours,
)
from trade_flow.risk import RegimePolicy, apply_risk_policy, build_regime_states  # noqa: E402
from trade_flow.safety import (  # noqa: E402
    SafetyContext,
    kill_switch_active,
    load_runtime_config,
)
from trade_flow.strategy import signal  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/strategy.toml")
    parser.add_argument("--db", type=Path, default=Path("data/trade_flow.db"))
    parser.add_argument("--universe", default="configs/universe_main.toml")
    parser.add_argument("--start", default="2016-01-01")
    parser.add_argument("--max-symbols", type=int, default=600)
    parser.add_argument("--policy", choices=["buy_block", "equity_cap"], default="buy_block")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="라이브 주문 제출(모의 계좌). 미국 정규장 개장 필요. 미지정 시 dry-run.",
    )
    parser.add_argument("--ops-db", type=Path, default=Path("data/live_orders.db"))
    parser.add_argument("--run-suffix", default="", help="run_id 고유화용 접미사")
    parser.add_argument(
        "--refresh-data",
        action="store_true",
        help="실행 전 최신 바(가격 --period 10d)+VIX/WTI를 수집해 DB 갱신(collect extra 필요).",
    )
    parser.add_argument("--runtime", type=Path, default=Path("configs/runtime.toml"))
    parser.add_argument("--notify-log", type=Path, default=Path("data/daily_run.log"))
    parser.add_argument("--nav-history", type=Path, default=Path("data/nav_history.json"))
    parser.add_argument("--exchange-map", type=Path, default=Path("data/exchange_map.json"))
    parser.add_argument(
        "--max-staleness-days",
        type=int,
        default=4,
        help="최종 세션이 오늘로부터 이 일수 이내면 데이터 신선(주말/휴장 고려 기본 4).",
    )
    args = parser.parse_args(argv)

    config = load_config(args.config)
    if args.refresh_data:
        _refresh_data(args)
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
    staleness = (date.today() - end).days  # noqa: DTZ011 - 로컬 날짜 기준 신선도
    data_fresh = staleness <= args.max_staleness_days
    print(f"유니버스 {len(surviving)}종목, 최종 세션 {end} (staleness {staleness}일, "
          f"fresh={data_fresh})")
    if not data_fresh:
        print(f"  경고: 데이터가 {staleness}일 지남 -> --refresh-data 권장. 라이브 매수 차단됨.")

    try:
        broker = KisBroker(build_client(), exchange_map_path=args.exchange_map)
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
    nav_history = NavHistory(args.nav_history)
    daily_return = nav_history.daily_return(account.nav, on=end)
    nav_history.record(end, account.nav)
    print(f"daily_return={float(daily_return):+.4f} (전 거래일 확정 NAV 대비, 손실한도 "
          f"-{float(config.risk.daily_loss_limit_fraction):.0%})")
    risk_target = apply_risk_policy(
        strategy_result, account,
        state or _missing_regime(end),
        config.risk, regime_policy=policy, daily_return=daily_return,
    )

    targets = {s: w for s, w in risk_target.target_weights.items() if w > 0}
    selected = ", ".join(f"{s}={float(w):.1%}" for s, w in sorted(targets.items()))
    print(f"\n선정 {len(targets)}종목: {selected}")

    from datetime import UTC, datetime

    within_window = within_us_market_hours(datetime.now(UTC))
    print(f"실행창(미국 정규장 개장): {within_window}")

    if args.execute:
        return _execute_live(
            config, broker, strategy_result, state or _missing_regime(end),
            policy, daily_return, account, end, args,
            data_fresh=data_fresh, within_window=within_window,
        )

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


def _reconcile_open_orders(broker):
    """시작 시 브로커 미체결 주문을 조회·취소한다(이월 방지, §3.5). 반환: (reconciled, 메시지)."""
    try:
        opens = broker.open_orders()
    except KisApiError as error:
        return False, f"미체결 조회 실패: {error}"
    if not opens:
        return True, "미체결 없음"
    cancelled, failed = 0, []
    for order in opens:
        try:
            broker.cancel_open(order)
            cancelled += 1
        except KisApiError as error:
            failed.append((order.get("odno"), str(error)))
    if failed:
        return False, (
            f"이전 미체결 {len(opens)}건 중 {cancelled} 취소, {len(failed)} 실패: {failed}"
        )
    return True, f"이전 미체결 {cancelled}건 취소(이월 방지)"


def _refresh_data(args) -> None:
    """실행 전 최신 바(단기)+VIX/WTI 수집(collect extra). 실패해도 기존 DB로 진행."""
    print("데이터 갱신 중(최근 바 + VIX/WTI)...")
    try:
        import collect as C  # scripts/collect.py (sys.path에 scripts 포함)

        C.collect_prices(Path(args.universe), args.db, years=10, period="10d")
        C.collect_regime(args.db)
    except Exception as error:  # noqa: BLE001 - 갱신 실패는 치명적이지 않음(기존 DB 사용)
        print(f"  경고: 데이터 갱신 실패({error}). 기존 DB로 진행.")


def _execute_live(
    config, broker, strategy_result, state, policy, daily_return, account, end, args,
    *, data_fresh, within_window,
):
    """라이브 주문 제출(모의). execute_rebalance가 시세·계획·안전게이트·제출을 처리한다."""
    print("\n=== LIVE 제출 (execute_rebalance) ===")
    print("  ⚠️ 실제 (모의) 주문을 제출합니다. 미국 정규장이 닫혀 있으면 '장종료'로 거부됩니다.")
    from datetime import datetime

    # §3.5 재실행 복구: 시작 시 이전 미체결 주문을 조회·취소(이월 방지). 취소 실패 시
    # open_orders_reconciled=False로 후속 매수 차단(fail-closed).
    open_orders_reconciled, recon_msg = _reconcile_open_orders(broker)
    print(f"  정합성(미체결): {recon_msg}")

    database = initialize_database(args.ops_db)
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")  # noqa: DTZ005 - run_id 고유화용
    run_id = f"daily-{end.isoformat()}-{stamp}{args.run_suffix}"
    RunRepository(database).start(
        run_id=run_id,
        environment="paper",
        account_hash=account.account_hash,
        trading_date=end,
        signal_date=end,
        data_hash="live",
        config_hash="live",
        universe_hash="live",
    )
    # 런타임 안전설정(환경/게이트/킬스위치)을 코드가 아닌 configs/runtime.toml에서 로드.
    runtime = load_runtime_config(args.runtime)
    kill = kill_switch_active(runtime, project_root=Path.cwd())
    notifier: Notifier = LogNotifier(args.notify_log)
    telegram = TelegramNotifier.from_env()
    if telegram is not None:
        notifier = FanoutNotifier(notifier, telegram)
        print("  텔레그램 알림 활성")

    def notify(subject: str, body: str, severity: str) -> None:
        delivery = notifier.send(Notification(subject, body, severity))
        if not delivery.delivered:
            print(f"  알림 전송 실패({subject}): {delivery.error_code}", file=sys.stderr)

    if kill:
        notify("kill_switch_active", f"KILL_SWITCH 존재 -> 중단 ({run_id})", "critical")
    safety = SafetyContext(
        environment=runtime.environment,
        dry_run=runtime.dry_run,
        allow_real_orders=runtime.allow_real_orders,
        release_approved=runtime.release_approved,
        account_hash=account.account_hash,
        allowed_account_hashes=runtime.allowed_account_hashes,
        kill_switch_active=kill,
        data_fresh=data_fresh,
        account_reconciled=True,
        open_orders_reconciled=open_orders_reconciled,
        within_execution_window=within_window,
        daily_return=daily_return,
        daily_loss_limit=config.risk.daily_loss_limit_fraction,
    )
    from trade_flow.safety import SafetyBlocked

    try:
        result = execute_rebalance(
            strategy_result, state, config, broker, OrderRepository(database),
            run_id=run_id, trading_date=end, safety_context=safety,
            daily_return=daily_return, regime_policy=policy,
        )
    except SafetyBlocked as blocked:
        notify("execution_blocked", f"{run_id} 차단: {blocked.reasons}", "warning")
        print(f"  안전 게이트 차단: {blocked.reasons}")
        return 3
    except KisApiError as error:
        notify("submit_error", f"{run_id} 제출 오류: {error}", "error")
        print(f"  KIS 제출 오류(장종료 등): {error}")
        return 3
    nav = float(result.final_account.nav)
    summary = f"{run_id}: 제출 {len(result.broker_orders)}건, 최종 NAV ${nav:,.0f}"
    notify("rebalance_complete", summary, "info")
    print(f"  run_id: {run_id}")
    print(f"  제출된 주문 {len(result.broker_orders)}건:")
    for order in result.broker_orders:
        print(f"    {order.broker_order_id} intent={order.intent_id[:8]} "
              f"status={order.status} filled={order.filled_quantity}/{order.remaining_quantity}")
    print(f"  최종 계좌 NAV ${float(result.final_account.nav):,.0f}")
    return 0


def _missing_regime(session_date):
    from trade_flow.risk import RegimeState

    return RegimeState(session_date, True, False, 0, ("regime_missing",))


if __name__ == "__main__":
    raise SystemExit(main())
