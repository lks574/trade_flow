"""추천 사후 추적 리포트 생성.

recommendations 테이블의 과거 추천을 prices 테이블과 조인해 +1/+3/+5 거래일
수익률(수정종가 기준)을 계산하고, 적중 여부를 누적 문서로 남긴다. 문서는 DB에서
매번 전체 재생성되므로 멱등이다(주간 실행 권장 — recommend.py 직후).

실행 예:
  python scripts/track_recommendations.py [--telegram]

판정 기준(문서에도 명시):
  - 적중(✅): +5 거래일 수익률 > 0
  - 상대 우위: 같은 구간 유니버스(전 종목) 중앙값 대비 초과수익
  - 5거래일이 아직 안 지난 추천은 ⏳(미확정)로 표시하고 적중률 집계에서 제외
"""

from __future__ import annotations

import argparse
import sqlite3
import statistics
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from trade_flow.db import (
    PriceTargetRepository,
    RecommendationRepository,
    StoredPriceTarget,
    StoredRecommendation,
    initialize_database,
)
from trade_flow.operations import Notification, TelegramNotifier

HORIZONS = (1, 3, 5)


@dataclass(frozen=True)
class TrackedRow:
    rec: StoredRecommendation
    returns: dict[int, float | None]  # horizon -> 수익률(미래 세션 부족 시 None)
    median_5d: float | None  # 유니버스 +5일 중앙값(비교 기준)


def _forward_closes(
    connection: sqlite3.Connection, symbol: str, as_of: date, max_horizon: int
) -> tuple[float | None, list[float]]:
    """기준일 수정종가와 이후 max_horizon개 세션의 수정종가."""
    base = connection.execute(
        "SELECT split_adjusted_close FROM prices WHERE symbol=? AND session_date=?",
        (symbol, as_of.isoformat()),
    ).fetchone()
    rows = connection.execute(
        """
        SELECT split_adjusted_close FROM prices
        WHERE symbol=? AND session_date>? ORDER BY session_date LIMIT ?
        """,
        (symbol, as_of.isoformat(), max_horizon),
    ).fetchall()
    return (float(base[0]) if base else None), [float(r[0]) for r in rows]


def _universe_median_5d(connection: sqlite3.Connection, as_of: date) -> float | None:
    """기준일 대비 5번째 후속 세션의 전 종목 수익률 중앙값(같은 리스크 환경 벤치마크)."""
    sessions = [
        r[0]
        for r in connection.execute(
            "SELECT DISTINCT session_date FROM prices WHERE session_date>? "
            "ORDER BY session_date LIMIT 5",
            (as_of.isoformat(),),
        ).fetchall()
    ]
    if len(sessions) < 5:
        return None
    target = sessions[4]
    rows = connection.execute(
        """
        SELECT b.split_adjusted_close, f.split_adjusted_close
        FROM prices b JOIN prices f ON f.symbol = b.symbol
        WHERE b.session_date=? AND f.session_date=?
        """,
        (as_of.isoformat(), target),
    ).fetchall()
    returns = [
        float(f) / float(b) - 1.0 for b, f in rows if b is not None and float(b) > 0
    ]
    return statistics.median(returns) if returns else None


def track(database: Path) -> list[TrackedRow]:
    recommendations = RecommendationRepository(database).all()
    tracked: list[TrackedRow] = []
    with sqlite3.connect(database) as connection:
        median_cache: dict[date, float | None] = {}
        for rec in recommendations:
            base, forwards = _forward_closes(connection, rec.symbol, rec.as_of_date, max(HORIZONS))
            returns: dict[int, float | None] = {}
            for horizon in HORIZONS:
                if base is None or base <= 0 or len(forwards) < horizon:
                    returns[horizon] = None
                else:
                    returns[horizon] = forwards[horizon - 1] / base - 1.0
            if rec.as_of_date not in median_cache:
                median_cache[rec.as_of_date] = _universe_median_5d(connection, rec.as_of_date)
            tracked.append(TrackedRow(rec, returns, median_cache[rec.as_of_date]))
    return tracked


@dataclass(frozen=True)
class TargetOutcome:
    target: StoredPriceTarget
    realized: float | None  # horizon 세션 후 수정종가(미경과 시 None)

    @property
    def in_band(self) -> bool | None:
        if self.realized is None:
            return None
        return float(self.target.low_68) <= self.realized <= float(self.target.high_68)

    @property
    def direction_hit(self) -> bool | None:
        """기대 방향(기대가 vs 기준가) 적중 여부. drift≈0(VIX 억제)이면 채점 제외."""
        if self.realized is None or abs(self.target.drift_daily) < 1e-12:
            return None
        expected_up = float(self.target.expected) > float(self.target.basis_close)
        realized_up = self.realized > float(self.target.basis_close)
        return expected_up == realized_up


def score_targets(database: Path) -> list[TargetOutcome]:
    outcomes: list[TargetOutcome] = []
    with sqlite3.connect(database) as connection:
        for target in PriceTargetRepository(database).all():
            rows = connection.execute(
                """
                SELECT split_adjusted_close FROM prices
                WHERE symbol=? AND session_date>? ORDER BY session_date LIMIT ?
                """,
                (target.symbol, target.as_of_date.isoformat(), target.horizon_sessions),
            ).fetchall()
            realized = (
                float(rows[target.horizon_sessions - 1][0])
                if len(rows) >= target.horizon_sessions
                else None
            )
            outcomes.append(TargetOutcome(target, realized))
    return outcomes


def _calibration_lines(outcomes: list[TargetOutcome]) -> list[str]:
    lines = [
        "## 목표가 예보 캘리브레이션",
        "",
        "- 채점 기준: 실현 종가가 68% 구간 안이면 적중 — **명목 68%에 근접해야 예보가 정직한 것**",
        "- 방향 적중은 drift가 0이 아닌 예보만 채점(VIX 억제 시 방향 예측을 포기하므로)",
        "",
    ]
    for horizon, label in ((5, "1주(+5)"), (21, "1개월(+21)")):
        rows = [o for o in outcomes if o.target.horizon_sessions == horizon]
        settled = [o for o in rows if o.realized is not None]
        pending = len(rows) - len(settled)
        if not settled:
            lines.append(f"- {label}: 확정 0건 (미경과 {pending}건)")
            continue
        in_band = [o for o in settled if o.in_band]
        directions = [o for o in settled if o.direction_hit is not None]
        direction_hits = [o for o in directions if o.direction_hit]
        direction_text = (
            f", 방향 적중 {len(direction_hits)}/{len(directions)}"
            f" ({len(direction_hits) / len(directions):.0%})"
            if directions
            else ""
        )
        lines.append(
            f"- {label}: 구간 적중 **{len(in_band)}/{len(settled)}"
            f" ({len(in_band) / len(settled):.0%})** vs 명목 68%"
            f"{direction_text} (미경과 {pending}건)"
        )
    lines.append("")
    return lines


def _fmt(value: float | None) -> str:
    return "⏳" if value is None else f"{value:+.2%}"


def _verdict(row: TrackedRow) -> str:
    r5 = row.returns[5]
    if r5 is None:
        return "⏳"
    return "✅" if r5 > 0 else "❌"


def render_markdown(
    tracked: list[TrackedRow],
    *,
    generated_at: str,
    target_outcomes: list[TargetOutcome] | None = None,
) -> str:
    settled = [t for t in tracked if t.returns[5] is not None]
    hits = [t for t in settled if t.returns[5] > 0]
    beat_median = [
        t for t in settled if t.median_5d is not None and t.returns[5] > t.median_5d
    ]
    lines = [
        "# 추천 사후 추적 리포트",
        "",
        f"- 갱신: {generated_at} (scripts/track_recommendations.py 자동 생성 — 수동 편집 금지)",
        "- 수익률: 기준일 수정종가 → +N 거래일 수정종가 (배당 미반영)",
        "- 판정: +5 거래일 수익률 > 0 → ✅. 5거래일 미경과 → ⏳(집계 제외)",
        "- 주의: 추천 엔진은 grade-C 유니버스(현재 S&P 500 구성 종목) 기반 기술적 팩터"
        " 랭킹이며, 이 추적은 사후 검증용이다.",
        "",
        "## 요약 (확정 건 기준)",
        "",
    ]
    if settled:
        avg5 = statistics.mean(t.returns[5] for t in settled)
        lines += [
            f"- 확정 추천: {len(settled)}건 / 미확정 {len(tracked) - len(settled)}건",
            f"- **+5일 적중률(수익>0): {len(hits)}/{len(settled)}"
            f" ({len(hits) / len(settled):.0%})**",
            f"- +5일 평균 수익률: {avg5:+.2%}",
            f"- 유니버스 중앙값 상회: {len(beat_median)}/{len(settled)}"
            f" ({len(beat_median) / len(settled):.0%})",
        ]
    else:
        lines.append("- 확정된 추천이 아직 없다(모두 5거래일 미경과).")
    lines.append("")

    # 모멘텀군 vs 퀄리티게이트군 대조 채점 (게이트 승격 여부의 판단 근거).
    variants = sorted({t.rec.variant for t in tracked})
    if len(variants) > 1:
        lines += ["## 리스트 대조 (momentum vs quality_gated)", ""]
        labels = {"momentum": "모멘텀", "quality_gated": "퀄리티 게이트"}
        for variant in variants:
            cohort = [t for t in tracked if t.rec.variant == variant]
            cohort_settled = [t for t in cohort if t.returns[5] is not None]
            if not cohort_settled:
                lines.append(f"- {labels.get(variant, variant)}: 확정 0건"
                             f" (미경과 {len(cohort)}건)")
                continue
            cohort_hits = sum(1 for t in cohort_settled if t.returns[5] > 0)
            cohort_avg = statistics.mean(t.returns[5] for t in cohort_settled)
            lines.append(
                f"- {labels.get(variant, variant)}: 적중"
                f" {cohort_hits}/{len(cohort_settled)}"
                f" ({cohort_hits / len(cohort_settled):.0%}),"
                f" +5일 평균 {cohort_avg:+.2%}"
                f" (미경과 {len(cohort) - len(cohort_settled)}건)"
            )
        lines.append("")

    if target_outcomes:
        lines += _calibration_lines(target_outcomes)

    by_group: dict[tuple[date, str], list[TrackedRow]] = {}
    for row in tracked:
        by_group.setdefault((row.rec.as_of_date, row.rec.variant), []).append(row)
    variant_labels = {"momentum": "모멘텀", "quality_gated": "퀄리티 게이트"}
    for as_of, variant in sorted(by_group, key=lambda k: (k[0], k[1]), reverse=True):
        rows = sorted(by_group[(as_of, variant)], key=lambda r: r.rec.rank)
        median_5d = rows[0].median_5d
        median_text = "⏳" if median_5d is None else f"{median_5d:+.2%}"
        lines += [
            f"## 기준일 {as_of} — {variant_labels.get(variant, variant)}"
            f" (유니버스 +5일 중앙값 {median_text})",
            "",
            "| 순위 | 종목 | ★ | 점수 | 모멘텀 | +1일 | +3일 | +5일 | 판정 |",
            "|---:|---|:-:|---:|---:|---:|---:|---:|:-:|",
        ]
        for row in rows:
            rec = row.rec
            lines.append(
                f"| {rec.rank} | {rec.symbol} | {'★' if rec.traded else ''} "
                f"| {float(rec.total_score):.3f} | {float(rec.momentum_return):+.1%} "
                f"| {_fmt(row.returns[1])} | {_fmt(row.returns[3])} "
                f"| {_fmt(row.returns[5])} | {_verdict(row)} |"
            )
        lines.append("")
    return "\n".join(lines)


def _telegram_summary(tracked: list[TrackedRow]) -> str:
    settled = [t for t in tracked if t.returns[5] is not None]
    if not settled:
        return "확정된 추천 없음(모두 5거래일 미경과)."
    hits = [t for t in settled if t.returns[5] > 0]
    avg5 = statistics.mean(t.returns[5] for t in settled)
    latest = max(t.rec.as_of_date for t in tracked)
    return (
        f"확정 {len(settled)}건: 적중률 {len(hits)}/{len(settled)}"
        f" ({len(hits) / len(settled):.0%}), +5일 평균 {avg5:+.2%}\n"
        f"최신 기준일 {latest} — 상세는 docs/reports/recommendation-tracking.md"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("data/trade_flow.db"))
    parser.add_argument(
        "--out", type=Path, default=Path("docs/reports/recommendation-tracking.md")
    )
    parser.add_argument("--telegram", action="store_true", help="요약을 텔레그램으로 발송.")
    args = parser.parse_args(argv)

    initialize_database(args.db)
    tracked = track(args.db)
    if not tracked:
        print(
            "recommendations 테이블이 비어 있다. scripts/recommend.py 먼저 실행.",
            file=sys.stderr,
        )
        return 1

    generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    target_outcomes = score_targets(args.db)
    document = render_markdown(
        tracked, generated_at=generated_at, target_outcomes=target_outcomes
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(document, encoding="utf-8")
    settled = sum(1 for t in tracked if t.returns[5] is not None)
    print(f"{args.out} 갱신 완료 — 추천 {len(tracked)}건(확정 {settled}건).")

    if args.telegram:
        notifier = TelegramNotifier.from_env()
        if notifier is None:
            print("TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID 미설정 — 발송 생략.", file=sys.stderr)
            return 2
        delivery = notifier.send(
            Notification("추천 사후 추적", _telegram_summary(tracked), "info")
        )
        if not delivery.delivered:
            print(f"텔레그램 발송 실패: {delivery.error_code}", file=sys.stderr)
            return 2
        print("텔레그램 발송 완료.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
