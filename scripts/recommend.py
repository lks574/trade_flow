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
from trade_flow.db import (  # noqa: E402
    RecommendationEntry,
    RecommendationRepository,
    initialize_database,
)
from trade_flow.domain.config import load_config  # noqa: E402
from trade_flow.operations import Notification, TelegramNotifier  # noqa: E402
from trade_flow.strategy import signal  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/strategy.toml")
    parser.add_argument("--db", type=Path, default=Path("data/trade_flow.db"))
    parser.add_argument("--universe", default="configs/universe_main.toml")
    parser.add_argument("--start", default="2016-01-01")
    parser.add_argument("--max-symbols", type=int, default=600)
    parser.add_argument("--top", type=int, default=15)
    parser.add_argument(
        "--no-fundamentals",
        action="store_true",
        help="섹터·펀더멘털(yfinance) 조회 생략(순수 정량, 빠름).",
    )
    parser.add_argument(
        "--telegram",
        action="store_true",
        help="리포트를 텔레그램으로 발송(.env의 TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID 필요).",
    )
    parser.add_argument(
        "--as-of",
        default=None,
        help="기준일 지정(YYYY-MM-DD, 과거 백필용). 생략 시 DB 최신 세션.",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="추천 결과를 recommendations 테이블에 저장하지 않음(실험 실행용).",
    )
    args = parser.parse_args(argv)

    telegram = None
    if args.telegram:
        telegram = TelegramNotifier.from_env()
        if telegram is None:
            print(
                "오류: --telegram 지정됐지만 TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID가 없다. "
                "set -a && source .env && set +a 후 재실행.",
                file=sys.stderr,
            )
            return 2

    config = load_config(args.config)
    provider = SqliteMarketDataProvider(args.db)
    calendar = SqliteMarketCalendar(args.db)
    connection = sqlite3.connect(args.db)
    if args.as_of:
        # 백필: 지정일 이하의 마지막 세션을 기준일로 쓴다(휴장일 지정 허용).
        row = connection.execute(
            "SELECT MAX(session_date) FROM prices WHERE session_date <= ?", (args.as_of,)
        ).fetchone()
        if row[0] is None:
            print(f"오류: {args.as_of} 이전 가격 데이터가 없다.", file=sys.stderr)
            return 2
        raw_end = date.fromisoformat(row[0])
    else:
        raw_end = date.fromisoformat(
            connection.execute("SELECT MAX(session_date) FROM prices").fetchone()[0]
        )
    start = date.fromisoformat(args.start)
    universe_spec = R.load_universe(args.universe)
    provider_of = {m.symbol: m.provider_symbol for m in universe_spec.symbols}
    universe = [m.symbol for m in universe_spec.symbols][: args.max_symbols]

    snapshot, surviving, end, _notes = R._build_clean_snapshot(
        provider, calendar, universe, start=start, raw_end=raw_end, cap_final=True
    )
    result = signal(snapshot, config.strategy, main_symbols=set(surviving))

    ranked = sorted(
        result.scores.items(),
        key=lambda item: (-item[1].total, -item[1].momentum_return, item[0]),
    )
    traded = set(result.target_weights)  # 자동매매가 실제로 담는 상위 N
    top = ranked[: args.top]

    fundamentals: dict[str, dict] = {}
    if not args.no_fundamentals:
        print(f"펀더멘털 조회 중(상위 {len(top)}종목, yfinance)...")
        fundamentals = _fetch_fundamentals([sym for sym, _ in top], provider_of)

    print(f"\n주간 종목 추천 (정량 팩터) — 기준일 {end}, 적격 {len(ranked)}종목 중 상위 {args.top}")
    print("팩터 가중치: 모멘텀 0.40 / 추세 0.25 / RSI 0.15 / MACD 0.20")
    print(f"{'순위':>3} {'종목':<6} {'섹터':<22} {'총점':>5} {'모멘텀':>8} "
          f"{'PER':>6} {'시총$B':>7} {'배당%':>5} 매매")
    for rank, (symbol, score) in enumerate(top, start=1):
        info = fundamentals.get(symbol, {})
        star = "★" if symbol in traded else ""
        print(
            f"{rank:>3} {symbol:<6} {_short(info.get('sector'), 22):<22} "
            f"{float(score.total):>5.3f} {float(score.momentum_return):>+8.2%} "
            f"{_num(info.get('pe')):>6} {_bil(info.get('mcap')):>7} "
            f"{_pct(info.get('div')):>5} {star}"
        )
    print(f"\n★ = 자동매매가 이번 주 담는 상위 {config.strategy.main_count}. 나머지는 후보 순위.")
    print("펀더멘털은 현재 시점 값(리포트 기준일과 무관). 기술적 팩터 랭킹 + 참고용 펀더멘털이며,")
    print("LLM 펀더멘털·감정 계층은 미구현(docs/research 참고). 수치는 1차 자료로 재검증 후 사용.")

    if not args.no_save:
        initialize_database(args.db)  # recommendations 테이블 보장(멱등)
        RecommendationRepository(args.db).record(
            end,
            [
                RecommendationEntry(
                    rank=rank,
                    symbol=symbol,
                    total_score=score.total,
                    momentum_return=score.momentum_return,
                    traded=symbol in traded,
                )
                for rank, (symbol, score) in enumerate(top, start=1)
            ],
        )
        print(f"recommendations 테이블 저장 완료(기준일 {end}, {len(top)}종목).")

    if telegram is not None:
        body = _telegram_body(
            top, traded, fundamentals, end=end, eligible=len(ranked),
            main_count=config.strategy.main_count,
        )
        delivery = telegram.send(Notification("주간 종목 추천", body, "info"))
        if not delivery.delivered:
            print(f"텔레그램 발송 실패: {delivery.error_code}", file=sys.stderr)
            return 2
        print("텔레그램 발송 완료.")
    return 0


def _telegram_body(
    top, traded: set[str], fundamentals: dict[str, dict], *,
    end: date, eligible: int, main_count: int,
) -> str:
    """모바일 가독성 위주의 컴팩트 리포트(모노스페이스 표 대신 줄 단위)."""
    lines = [f"기준일 {end} · 적격 {eligible}종목 중 상위 {len(top)}"]
    for rank, (symbol, score) in enumerate(top, start=1):
        info = fundamentals.get(symbol, {})
        star = " ★" if symbol in traded else ""
        sector = _short(info.get("sector"), 18)
        lines.append(
            f"{rank}. {symbol}{star} {float(score.total):.3f} "
            f"| 모멘텀 {float(score.momentum_return):+.1%} | {sector}"
        )
    lines.append(f"\n★=자동매매 top-{main_count}")
    lines.append("기술적 팩터 랭킹(모멘텀0.40·추세0.25·RSI0.15·MACD0.20). 재검증 후 사용.")
    return "\n".join(lines)


def _fetch_fundamentals(symbols: list[str], provider_of: dict[str, str]) -> dict[str, dict]:
    try:
        import yfinance as yf  # lazy: collect extra only
    except ImportError:
        print("  yfinance 미설치 -> 펀더멘털 생략(--no-fundamentals와 동일)")
        return {}
    out: dict[str, dict] = {}
    for symbol in symbols:
        try:
            info = yf.Ticker(provider_of.get(symbol, symbol)).info
            out[symbol] = {
                "sector": info.get("sector"),
                "pe": info.get("trailingPE"),
                "mcap": info.get("marketCap"),
                "div": info.get("dividendYield"),
            }
        except Exception:  # noqa: BLE001 - 개별 종목 실패는 무시(— 표시)
            out[symbol] = {}
    return out


def _short(value, width: int) -> str:
    if not value:
        return "—"
    text = str(value)
    return text if len(text) <= width else text[: width - 1] + "…"


def _num(value) -> str:
    try:
        return f"{float(value):.1f}"
    except (TypeError, ValueError):
        return "—"


def _bil(value) -> str:
    try:
        return f"{float(value) / 1e9:,.0f}"
    except (TypeError, ValueError):
        return "—"


def _pct(value) -> str:
    try:
        pct = float(value)
    except (TypeError, ValueError):
        return "—"
    # yfinance 버전에 따라 소수(0.015) 또는 퍼센트(1.5)로 옴 -> 정규화.
    if pct > 1:
        return f"{pct:.1f}"
    return f"{pct * 100:.1f}"


if __name__ == "__main__":
    raise SystemExit(main())
