"""퀄리티 게이트: 모멘텀 랭킹에 재무 품질·섹터 분산 필터를 얹는다.

게이트(하드지표): ROE >= 10%, 순마진 >= 5%, D/E <= 2.0 — 결측은 fail-closed.
섹터 상한: 선정 목록에서 동일 섹터 최대 N(기본 2) — 단일 매크로 베팅 방지.

주의: 펀더멘털은 yfinance의 '현재 시점' 값이다. 과거 백테스트에 쓰면 미래참조가
되므로 라이브 라벨링·전향적 추적 전용이다. 게이트군 vs 모멘텀군의 성과 비교는
track_recommendations.py가 채점한다.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

ROE_MIN = 0.10
MARGIN_MIN = 0.05
DE_MAX = 200.0  # yfinance debtToEquity는 퍼센트(200 = 2.0x)
CACHE_TTL_SECONDS = 7 * 24 * 3600  # 주 1회 갱신이면 충분


@dataclass(frozen=True)
class QualityAssessment:
    symbol: str
    roe: float | None
    margin: float | None
    debt_to_equity: float | None  # 퍼센트 단위(yfinance 원값)
    sector: str | None
    passed: bool
    fail_reasons: tuple[str, ...]


def evaluate_fundamentals(
    roe: float | None, margin: float | None, debt_to_equity: float | None
) -> tuple[bool, tuple[str, ...]]:
    """게이트 판정(순수 함수). 결측은 fail-closed."""
    fails: list[str] = []
    if roe is None or roe < ROE_MIN:
        fails.append("ROE" if roe is not None else "ROE결측")
    if margin is None or margin < MARGIN_MIN:
        fails.append("마진" if margin is not None else "마진결측")
    if debt_to_equity is None or debt_to_equity > DE_MAX:
        fails.append("부채" if debt_to_equity is not None else "부채결측")
    return (not fails, tuple(fails))


def build_gated_selection(
    assessments: Iterable[QualityAssessment], *, limit: int, sector_cap: int = 2
) -> list[QualityAssessment]:
    """모멘텀 순 판정 스트림에서 게이트 통과 + 섹터 상한을 적용해 상위 limit 선정.

    제너레이터를 받으면 limit 충족 시점까지만 소비한다(펀더멘털 조회 지연 평가)."""
    selected: list[QualityAssessment] = []
    sector_count: dict[str, int] = {}
    for assessment in assessments:
        if not assessment.passed:
            continue
        sector = assessment.sector or "?"
        if sector_count.get(sector, 0) >= sector_cap:
            continue
        selected.append(assessment)
        sector_count[sector] = sector_count.get(sector, 0) + 1
        if len(selected) >= limit:
            break
    return selected


class FundamentalsFetcher:
    """yfinance 펀더멘털 조회 + 파일 캐시(TTL 7일). 실패는 결측(fail-closed) 처리."""

    def __init__(self, cache_path: str | Path, *, ttl_seconds: float = CACHE_TTL_SECONDS):
        self._path = Path(cache_path)
        self._ttl = ttl_seconds
        self._cache: dict[str, dict] = {}
        if self._path.exists():
            try:
                self._cache = json.loads(self._path.read_text())
            except ValueError:
                self._cache = {}

    def _fresh(self, entry: dict) -> bool:
        return time.time() - entry.get("fetched_at", 0) < self._ttl

    def assess(self, symbol: str, provider_symbol: str | None = None) -> QualityAssessment:
        entry = self._cache.get(symbol)
        if entry is None or not self._fresh(entry):
            entry = {"fetched_at": time.time()}
            try:
                import yfinance as yf  # lazy: collect extra only

                info = yf.Ticker(provider_symbol or symbol).info
                entry.update(
                    roe=info.get("returnOnEquity"),
                    margin=info.get("profitMargins"),
                    de=info.get("debtToEquity"),
                    sector=info.get("sector"),
                )
            except Exception:  # noqa: BLE001 - 조회 실패는 결측으로 fail-closed
                pass
            self._cache[symbol] = entry
        passed, fails = evaluate_fundamentals(
            entry.get("roe"), entry.get("margin"), entry.get("de")
        )
        return QualityAssessment(
            symbol=symbol,
            roe=entry.get("roe"),
            margin=entry.get("margin"),
            debt_to_equity=entry.get("de"),
            sector=entry.get("sector"),
            passed=passed,
            fail_reasons=fails,
        )

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._cache))
