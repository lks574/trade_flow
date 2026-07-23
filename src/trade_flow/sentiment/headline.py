"""뉴스 헤드라인 규칙 기반 감정점수(-1~1) + 매크로/지정학 키워드 플래그.

LLM 감정 계층(docs/research) 구현 전의 근사치다. 단어 사전 매칭이므로 반어·문맥은
못 읽는다 — 점수는 목표가 drift를 ±30% 이내로 기울이는 보조 입력으로만 쓰고,
사후 캘리브레이션 채점으로 유효성을 검증한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_POSITIVE = {
    "beat", "beats", "upgrade", "upgraded", "surge", "surges", "rally", "rallies",
    "record", "outperform", "outperforms", "strong", "growth", "profit", "profits",
    "buy", "bullish", "raise", "raises", "raised", "top", "tops", "jump", "jumps",
    "gain", "gains", "soar", "soars", "win", "wins", "boost", "boosts", "dividend",
    "buyback", "expansion", "breakthrough", "approval", "approved",
}
_NEGATIVE = {
    "miss", "misses", "downgrade", "downgraded", "plunge", "plunges", "fall",
    "falls", "drop", "drops", "weak", "loss", "losses", "sell", "bearish", "cut",
    "cuts", "lawsuit", "probe", "investigation", "recall", "bankruptcy", "fraud",
    "warning", "warns", "layoff", "layoffs", "slump", "slumps", "crash", "sink",
    "sinks", "decline", "declines", "tumble", "tumbles", "risk", "risks",
}
# 지정학·매크로 플래그: 점수와 별개로 컨텍스트 경고 표시에 쓴다.
_MACRO_FLAGS = {
    "war": "전쟁", "iran": "이란", "israel": "이스라엘", "hormuz": "호르무즈",
    "opec": "OPEC", "sanction": "제재", "sanctions": "제재", "fed": "연준",
    "tariff": "관세", "tariffs": "관세", "recession": "침체", "inflation": "인플레",
    "strait": "해협", "missile": "미사일", "strike": "공습", "strikes": "공습",
}

_WORD = re.compile(r"[a-z']+")


@dataclass(frozen=True)
class HeadlineSentiment:
    score: float  # -1(악재)~+1(호재), 헤드라인 평균
    article_count: int
    macro_flags: tuple[str, ...]  # 발견된 지정학·매크로 키워드(한글 라벨, 중복 제거)


def score_headline(title: str) -> float:
    """단일 헤드라인 점수: (긍정어-부정어)/(긍정어+부정어), 매칭 없으면 0."""
    words = set(_WORD.findall(title.lower()))
    positive = len(words & _POSITIVE)
    negative = len(words & _NEGATIVE)
    if positive + negative == 0:
        return 0.0
    return (positive - negative) / (positive + negative)


def score_headlines(titles: list[str]) -> HeadlineSentiment:
    """헤드라인 묶음의 평균 점수와 매크로 플래그. 빈 입력이면 중립(0, 0건)."""
    if not titles:
        return HeadlineSentiment(score=0.0, article_count=0, macro_flags=())
    scores = [score_headline(t) for t in titles]
    flags: list[str] = []
    for title in titles:
        words = set(_WORD.findall(title.lower()))
        for keyword, label in _MACRO_FLAGS.items():
            if keyword in words and label not in flags:
                flags.append(label)
    return HeadlineSentiment(
        score=sum(scores) / len(scores),
        article_count=len(titles),
        macro_flags=tuple(flags),
    )
