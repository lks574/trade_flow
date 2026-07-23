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
    PriceTargetRepository,
    RecommendationEntry,
    RecommendationRepository,
    initialize_database,
)
from trade_flow.domain.config import load_config  # noqa: E402
from trade_flow.operations import Notification, TelegramNotifier  # noqa: E402
from trade_flow.research import (  # noqa: E402
    FundamentalsFetcher,
    MarketContext,
    build_gated_selection,
    compute_price_target,
)
from trade_flow.sentiment.headline import score_headlines  # noqa: E402
from trade_flow.strategy import signal  # noqa: E402

TARGET_HORIZONS = (5, 21)  # 1주·1개월(거래일)
SECTOR_CAP = 2  # quality_gated 리스트의 동일 섹터 상한(단일 매크로 베팅 방지)


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

    # 퀄리티 게이트 리스트: 게이트(ROE·마진·부채) 통과 × 모멘텀 순 × 섹터 상한.
    # 모멘텀군과 게이트군의 사후 성과는 추적 리포트가 대조 채점한다(전향적 검증).
    fetcher = FundamentalsFetcher(Path(args.db).parent / "fundamentals_cache.json")
    gated = build_gated_selection(
        (fetcher.assess(sym, provider_of.get(sym)) for sym, _score in ranked),
        limit=args.top,
        sector_cap=SECTOR_CAP,
    )
    quality_of = {sym: fetcher.assess(sym, provider_of.get(sym)) for sym, _score in top}
    fetcher.save()
    gated_symbols = [assessment.symbol for assessment in gated]
    score_of = dict(result.scores)

    fundamentals: dict[str, dict] = {}
    if not args.no_fundamentals:
        print(f"펀더멘털 조회 중(상위 {len(top)}종목, yfinance)...")
        fundamentals = _fetch_fundamentals([sym for sym, _ in top], provider_of)

    print(f"\n주간 종목 추천 (정량 팩터) — 기준일 {end}, 적격 {len(ranked)}종목 중 상위 {args.top}")
    print("팩터 가중치: 모멘텀 0.40 / 추세 0.25 / RSI 0.15 / MACD 0.20")
    print(f"{'순위':>3} {'종목':<6} {'섹터':<22} {'총점':>5} {'모멘텀':>8} "
          f"{'PER':>6} {'시총$B':>7} {'배당%':>5} 매매 퀄리티")
    for rank, (symbol, score) in enumerate(top, start=1):
        info = fundamentals.get(symbol, {})
        star = "★" if symbol in traded else " "
        assessment = quality_of.get(symbol)
        quality_text = (
            "✅" if assessment and assessment.passed
            else "❌" + ",".join(assessment.fail_reasons) if assessment else "—"
        )
        print(
            f"{rank:>3} {symbol:<6} {_short(info.get('sector'), 22):<22} "
            f"{float(score.total):>5.3f} {float(score.momentum_return):>+8.2%} "
            f"{_num(info.get('pe')):>6} {_bil(info.get('mcap')):>7} "
            f"{_pct(info.get('div')):>5} {star}  {quality_text}"
        )

    print(f"\n퀄리티 게이트 리스트 (통과 {sum(1 for a in gated if a.passed)}종목"
          f" × 모멘텀 순 × 섹터상한 {SECTOR_CAP}) — 전향적 추적용:")
    for rank, assessment in enumerate(gated, start=1):
        score = score_of[assessment.symbol]
        print(
            f"{rank:>3} {assessment.symbol:<6} {_short(assessment.sector, 22):<22} "
            f"{float(score.total):>5.3f} {float(score.momentum_return):>+8.2%}"
        )
    print(f"\n★ = 자동매매가 이번 주 담는 상위 {config.strategy.main_count}. 나머지는 후보 순위.")
    print("펀더멘털은 현재 시점 값(리포트 기준일과 무관). 기술적 팩터 랭킹 + 참고용 펀더멘털이며,")
    print("LLM 펀더멘털·감정 계층은 미구현(docs/research 참고). 수치는 1차 자료로 재검증 후 사용.")

    if not args.no_save:
        initialize_database(args.db)  # recommendations 테이블 보장(멱등)
        repository = RecommendationRepository(args.db)
        repository.record(
            end,
            [
                RecommendationEntry(
                    rank=rank,
                    symbol=symbol,
                    total_score=score.total,
                    momentum_return=score.momentum_return,
                    traded=symbol in traded,
                    quality_pass=(
                        quality_of[symbol].passed if symbol in quality_of else None
                    ),
                    quality_fail=(
                        ",".join(quality_of[symbol].fail_reasons) or None
                        if symbol in quality_of
                        else None
                    ),
                )
                for rank, (symbol, score) in enumerate(top, start=1)
            ],
        )
        repository.record(
            end,
            [
                RecommendationEntry(
                    rank=rank,
                    symbol=assessment.symbol,
                    total_score=score_of[assessment.symbol].total,
                    momentum_return=score_of[assessment.symbol].momentum_return,
                    traded=False,
                    quality_pass=True,
                    quality_fail=None,
                )
                for rank, assessment in enumerate(gated, start=1)
            ],
            variant="quality_gated",
        )
        print(f"recommendations 저장 완료(기준일 {end}, momentum {len(top)}"
              f" + quality_gated {len(gated)}종목).")

    # --- 목표가 예보(확률 구간) --- momentum top + quality_gated 합집합에 대해 산출.
    forecast_symbols = list(dict.fromkeys([s for s, _score in top] + gated_symbols))
    context = _market_context(connection, end)
    # 백필(--as-of)은 과거 뉴스가 없어 감정을 생략한다(점수 None으로 정직하게 기록).
    sentiments = {} if args.as_of else _fetch_sentiment(forecast_symbols, provider_of)
    macro_flags: list[str] = []
    for sentiment in sentiments.values():
        for flag in sentiment.macro_flags:
            if flag not in macro_flags:
                macro_flags.append(flag)

    targets = []
    articles: dict[str, int] = {}
    for symbol in forecast_symbols:
        closes, highs, lows = _series_from_snapshot(snapshot, symbol)
        sentiment = sentiments.get(symbol)
        if sentiment is not None:
            articles[symbol] = sentiment.article_count
        for horizon in TARGET_HORIZONS:
            try:
                targets.append(
                    compute_price_target(
                        symbol,
                        as_of=end,
                        closes=closes,
                        highs=highs,
                        lows=lows,
                        horizon_sessions=horizon,
                        sentiment_score=(
                            round(sentiment.score, 4) if sentiment is not None else None
                        ),
                        context=context,
                    )
                )
            except ValueError as error:
                print(f"  {symbol} 목표가 생략({horizon}세션): {error}")

    vix_text = f"{context.vix:.1f}" if context.vix is not None else "—"
    wti_text = (
        f"{context.wti_momentum_21d:+.1%}" if context.wti_momentum_21d is not None else "—"
    )
    print(f"\n목표가 예보 — 컨텍스트: VIX {vix_text}, WTI 21일 {wti_text}"
          + (f", 뉴스 플래그: {', '.join(macro_flags)}" if macro_flags else ""))
    by_symbol: dict[str, list] = {}
    for target in targets:
        by_symbol.setdefault(target.symbol, []).append(target)
    for symbol, symbol_targets in by_symbol.items():
        info = fundamentals.get(symbol, {})
        sentiment = sentiments.get(symbol)
        senti_text = (
            f"감정 {sentiment.score:+.2f}({sentiment.article_count}건)"
            if sentiment is not None and sentiment.article_count
            else "감정 —"
        )
        analyst = info.get("analyst_target")
        analyst_text = f", 애널리스트 목표 ${analyst:,.0f}(12M)" if analyst else ""
        basis = symbol_targets[0].basis_close
        print(f"  {symbol} ${float(basis):,.2f} · {senti_text}{analyst_text}")
        for target in symbol_targets:
            label = "1주" if target.horizon_sessions == 5 else "1개월"
            print(
                f"    {label}: 기대 ${float(target.expected):,.2f}"
                f" ({target.expected_return:+.1%})"
                f" · 68% [{float(target.low_68):,.2f} ~ {float(target.high_68):,.2f}]"
                f" · 손절 ${float(target.stop):,.2f}"
            )
    print("  ※ 점 예측이 아닌 확률 예보. 구간 적중률은 추적 리포트에서 채점된다.")

    if not args.no_save and targets:
        PriceTargetRepository(args.db).record(
            targets, sentiment_articles=articles, macro_flags=tuple(macro_flags)
        )
        print(f"price_targets 저장 완료({len(targets)}건).")

    if telegram is not None:
        body = _telegram_body(
            top, traded, fundamentals, end=end, eligible=len(ranked),
            main_count=config.strategy.main_count,
            targets_by_symbol=by_symbol, sentiments=sentiments,
            context=context, macro_flags=tuple(macro_flags),
            gated=gated, score_of=score_of, quality_of=quality_of,
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
    targets_by_symbol: dict[str, list] | None = None,
    sentiments: dict[str, object] | None = None,
    context: MarketContext | None = None,
    macro_flags: tuple[str, ...] = (),
    gated: list | None = None,
    score_of: dict | None = None,
    quality_of: dict | None = None,
) -> str:
    """모바일 가독성 위주의 컴팩트 리포트(모노스페이스 표 대신 줄 단위)."""
    lines = [f"기준일 {end} · 적격 {eligible}종목 중 상위 {len(top)}"]
    if context is not None and context.vix is not None:
        wti_text = (
            f", WTI 21일 {context.wti_momentum_21d:+.1%}"
            if context.wti_momentum_21d is not None
            else ""
        )
        lines.append(f"컨텍스트: VIX {context.vix:.1f}{wti_text}")
    if macro_flags:
        lines.append(f"뉴스 플래그: {', '.join(macro_flags)}")
    lines.append("")
    targets_by_symbol = targets_by_symbol or {}
    sentiments = sentiments or {}
    quality_of = quality_of or {}
    for rank, (symbol, score) in enumerate(top, start=1):
        info = fundamentals.get(symbol, {})
        star = " ★" if symbol in traded else ""
        sector = _short(info.get("sector"), 18)
        assessment = quality_of.get(symbol)
        quality_text = (
            " ✅" if assessment and assessment.passed
            else f" ❌{','.join(assessment.fail_reasons)}" if assessment else ""
        )
        lines.append(
            f"{rank}. {symbol}{star} {float(score.total):.3f} "
            f"| 모멘텀 {float(score.momentum_return):+.1%} | {sector}{quality_text}"
        )
        symbol_targets = targets_by_symbol.get(symbol, [])
        sentiment = sentiments.get(symbol)
        for target in symbol_targets:
            label = "1주" if target.horizon_sessions == 5 else "1개월"
            lines.append(
                f"   {label} 기대 ${float(target.expected):,.2f}"
                f"({target.expected_return:+.1%})"
                f" 68%[{float(target.low_68):,.0f}~{float(target.high_68):,.0f}]"
                f" 손절 ${float(target.stop):,.2f}"
            )
        extras = []
        if sentiment is not None and getattr(sentiment, "article_count", 0):
            extras.append(f"감정 {sentiment.score:+.2f}")
        analyst = info.get("analyst_target")
        if analyst:
            extras.append(f"애널목표 ${analyst:,.0f}")
        if extras:
            lines.append(f"   {' · '.join(extras)}")
    if gated and score_of:
        lines.append("\n🛡 퀄리티 게이트 리스트 (ROE·마진·부채 통과 × 섹터상한):")
        for rank, assessment in enumerate(gated, start=1):
            score = score_of[assessment.symbol]
            lines.append(
                f"{rank}. {assessment.symbol} "
                f"모멘텀 {float(score.momentum_return):+.1%} "
                f"| {_short(assessment.sector, 16)}"
            )
    lines.append(f"\n★=자동매매 top-{main_count}, ✅/❌=퀄리티 게이트")
    lines.append(
        "기술적 팩터 랭킹 + 확률 예보(점 예측 아님). 두 리스트 성과는 주간 추적에서 대조 채점."
    )
    return "\n".join(lines)


def _market_context(connection: sqlite3.Connection, as_of: date) -> MarketContext:
    """as_of 기준 VIX 최근 종가와 WTI 21세션 모멘텀(지정학·매크로의 정량 그림자)."""

    def _closes(indicator: str, limit: int) -> list[float]:
        rows = connection.execute(
            "SELECT close FROM market_context WHERE indicator=? AND session_date<=? "
            "ORDER BY session_date DESC LIMIT ?",
            (indicator, as_of.isoformat(), limit),
        ).fetchall()
        return [float(r[0]) for r in rows]

    vix_rows = _closes("VIX", 1)
    wti_rows = _closes("WTI", 22)
    vix = vix_rows[0] if vix_rows else None
    wti_momentum = (
        wti_rows[0] / wti_rows[-1] - 1.0 if len(wti_rows) >= 22 and wti_rows[-1] > 0 else None
    )
    return MarketContext(vix=vix, wti_momentum_21d=wti_momentum)


def _fetch_sentiment(symbols: list[str], provider_of: dict[str, str]) -> dict[str, object]:
    """종목별 최신 뉴스 헤드라인 감정점수(yfinance). 실패는 중립 처리."""
    try:
        import yfinance as yf  # lazy: collect extra only
    except ImportError:
        return {}
    out: dict[str, object] = {}
    for symbol in symbols:
        try:
            news = yf.Ticker(provider_of.get(symbol, symbol)).news or []
            titles = []
            for item in news:
                content = item.get("content", item)
                title = content.get("title")
                if title:
                    titles.append(str(title))
            out[symbol] = score_headlines(titles)
        except Exception:  # noqa: BLE001 - 감정은 보조 입력, 실패는 중립
            continue
    return out


def _series_from_snapshot(snapshot, symbol: str):
    bars = sorted(
        (b for b in snapshot.prices if b.symbol == symbol), key=lambda b: b.session_date
    )
    closes = [b.split_adjusted_close for b in bars]
    highs = [b.split_adjusted_high for b in bars]
    lows = [b.split_adjusted_low for b in bars]
    return closes, highs, lows


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
                "analyst_target": info.get("targetMeanPrice"),
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
