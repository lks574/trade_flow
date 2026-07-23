"""일일 계좌 점검: KIS 잔고 조회 + 손절 기준 위반 여부를 텔레그램으로 전달.

- 손절 기준 1: 평균단가 대비 -stop_loss_fraction (configs/strategy.toml, 기본 -10%)
- 손절 기준 2: 최신 목표가 예보의 ATR 손절선(price_targets) 하회 — 보유 종목이
  추천 종목일 때만 존재
- KIS API 오류는 critical 경보로 전달한다(§3.7 — API 깨짐 조기 발견).

Usage:  set -a && source .env && set +a && python scripts/daily_check.py [--telegram]
"""

from __future__ import annotations

import argparse
import sys
from decimal import Decimal
from pathlib import Path

from trade_flow.broker import KisApiError, KisBroker, KisConfigError, build_client
from trade_flow.db import PriceTargetRepository
from trade_flow.domain.config import load_config
from trade_flow.operations import Notification, TelegramNotifier


def _send(telegram: TelegramNotifier | None, subject: str, body: str, severity: str) -> None:
    print(f"[{severity}] {subject}\n{body}")
    if telegram is not None:
        result = telegram.send(Notification(subject, body, severity))
        if not result.delivered:
            print(f"텔레그램 전송 실패: {result.error_code}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/strategy.toml")
    parser.add_argument("--db", type=Path, default=Path("data/trade_flow.db"))
    parser.add_argument("--exchange-map", type=Path, default=Path("data/kis_exchange_map.json"))
    parser.add_argument("--telegram", action="store_true")
    args = parser.parse_args(argv)

    telegram = TelegramNotifier.from_env() if args.telegram else None
    if args.telegram and telegram is None:
        print("TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID 미설정.", file=sys.stderr)
        return 2

    stop_fraction = load_config(args.config).risk.stop_loss_fraction

    try:
        broker = KisBroker(build_client(), exchange_map_path=args.exchange_map)
        account = broker.account_snapshot()
    except (KisConfigError, KisApiError) as error:
        _send(
            telegram,
            "KIS API 경보",
            f"일일 계좌 점검 실패 — API 오류:\n{error}",
            "critical",
        )
        return 2

    # 최신 예보의 ATR 손절선(보유 종목이 추천 종목일 때 참조).
    atr_stops: dict[str, Decimal] = {}
    for target in PriceTargetRepository(args.db).all():
        if target.horizon_sessions == 5:  # 기준일별 동일 stop이므로 아무 horizon이나 무방
            atr_stops[target.symbol] = target.stop  # all()이 날짜 오름차순 → 최신이 남는다

    lines = [
        f"NAV ${float(account.nav):,.0f} · 현금 ${float(account.cash):,.0f}"
        f" · 보유 {len(account.positions)}종목"
    ]
    violations: list[str] = []
    for symbol, position in sorted(account.positions.items()):
        if position.quantity <= 0 or position.average_price <= 0:
            continue
        pnl = float(position.market_price / position.average_price) - 1.0
        flags = []
        if pnl <= -float(stop_fraction):
            flags.append(f"평단 대비 {pnl:+.1%} ≤ -{float(stop_fraction):.0%} 손절 기준")
        atr_stop = atr_stops.get(symbol)
        if atr_stop is not None and position.market_price < atr_stop:
            flags.append(f"ATR 손절선 ${float(atr_stop):,.2f} 하회")
        marker = " 🔴" if flags else ""
        lines.append(
            f"{symbol}: {position.quantity}주 · 평단 ${float(position.average_price):,.2f}"
            f" · 현재 ${float(position.market_price):,.2f} ({pnl:+.1%}){marker}"
        )
        violations.extend(f"{symbol}: {flag}" for flag in flags)

    if violations:
        lines.append("\n⚠️ 손절 검토 필요:")
        lines.extend(f"- {v}" for v in violations)
        _send(telegram, "손절 경보", "\n".join(lines), "critical")
    else:
        suffix = "손절 기준 위반 없음." if account.positions else "보유 종목 없음."
        lines.append(suffix)
        _send(telegram, "일일 계좌 점검", "\n".join(lines), "info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
