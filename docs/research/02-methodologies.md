# 02. 투자/분석 방법론 (알고리즘 인코딩용)

대상: 미국 일봉 스윙 자동매매, S&P500 유니버스, 종목 추천/분석 모듈. 각 규칙은 가능한 한 정량식으로 정리하고, 우리 시스템에 신호/필터로 인코딩할 아이디어를 병기했다.

---

## 1. 워런 버핏 / 가치투자 체크리스트

버핏 원칙을 정량화한 대표 버전은 Validea의 "Buffett-Hagstrom" 모델이다. 정성 개념(경제적 해자)을 정량 프록시로 치환한다.

| 항목 | 정량 규칙 (임계값) |
|---|---|
| 이익 예측가능성 | 최근 10년 중 8년 이상 EPS 증가, 10년간 음(-) 실적 연도 없음, 10년 EPS 총성장 (+) |
| ROE | 10년 평균 ROE ≥ 15% (매년 15% 초과가 이상적) |
| ROTC(총자본이익률) | 10년 평균 ROTC ≥ 12% |
| 부채 | 장기부채 ≤ 연이익의 5배 (가급적 2배 미만) |
| FCF | 최근 3~5년 FCF (+), 증가 추세 선호 |
| 유보이익 재투자수익 | 유보이익 대비 수익률 ≥ 12% (15%+ 선호) |
| 밸류에이션(안전마진) | 기대수익률 ≥ 15%(최소 12%), 이익수익률(E/P) > 10년물 국채금리 |

- **경제적 해자 프록시**: 다년간 안정/상승하는 총·영업마진, ROIC ≥ 15% 지속 → 가격결정력·해자 신호.
- **Owner earnings(주주이익)** = 순이익 + 감가상각/상각 − 유지보수 capex (±운전자본). FCF 전환율(FCF/순이익) ≥ 90%면 이익의 현금 신뢰성 높음.

**적용 아이디어**: S&P500은 대부분 이익 예측가능성/유동성 요건을 통과하므로, 이 체크리스트는 스윙 진입의 **펀더멘털 게이트 필터**로 사용. `ROE_10y_avg ≥ 15 AND ROTC_10y_avg ≥ 12 AND LT_debt/earnings ≤ 5 AND FCF>0` 통과 종목만 스윙 후보군에 포함(정성적 해자는 마진 추세 스코어로 근사). 재무 데이터는 분기 갱신, 기술적 트리거와 AND 결합.

**출처**: [Validea - Building a Quantitative Strategy Based on Buffett](https://blog.validea.com/building-a-quantitative-strategy-based-on-warren-buffetts-approach/) · [Validea - Quantifying Warren Buffett](https://blog.validea.com/quantifying-warren-buffett/) · [heygotrade - Quality Metrics Buffett Uses](https://www.heygotrade.com/en/blog/quality-investing-buffett-stock-metrics/)

---

## 2. 팩터 투자 (모멘텀 / 퀄리티 / 밸류 / 로우볼 / 사이즈)

### 2.1 모멘텀
- **12-1 모멘텀**: 최근 12개월 수익률에서 직전 1개월 제외(단기 반전 노이즈 제거). 데실 상위 매수. 원전 Jegadeesh & Titman(1993).
- 출처: [Jegadeesh & Titman (SSRN)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1919226) · [Quantpedia - Momentum](https://quantpedia.com/strategies/momentum-factor-effect-in-stocks) · [GuruFocus 12-1](https://www.gurufocus.com/term/pchange-12-1m)

### 2.2 퀄리티
- **Gross Profitability (Novy-Marx 2012)** = 매출총이익 / 총자산. 발생액·감가상각에 덜 오염된 "가장 깨끗한" 수익성 지표.
- **QMJ (Asness et al. 2014)** = Profitability + Growth + Safety + Payout 4축 평균.
- 출처: [Alpha Architect - Value and Quality](https://alphaarchitect.com/value-and-quality-stocks/) · [NBIM - The Quality Factor](https://www.nbim.no/contentassets/0660d8c611f94980ab0d33930cb2534e/nbim_discussionnotes_3-15.pdf)

### 2.3 밸류
- **Magic Formula (Greenblatt)**: 두 지표 랭킹 합산.
  - Return on Capital = EBIT / (순운전자본 + 순고정자산)
  - Earnings Yield = EBIT / 기업가치(EV)
  - 각 지표 1~N 랭킹 → 합산 최소값 매수. 20~30 종목, 연 1회 리밸런싱, 최소 시총 $50M.
- **O'Shaughnessy Value Composite**: P/FCF, P/E, P/S, EV/EBITDA, 주주수익률 5개 결합 랭킹 → 단일 지표보다 우수.
- **Acquirer's Multiple** = EV / 영업이익.
- 출처: [AAII - Magic Formula](https://www.aaii.com/stockideas/article/99688-greenblatts-magic-formula-for-beating-the-market) · [Wikipedia - Magic formula](https://en.wikipedia.org/wiki/Magic_formula_investing) · [AAII - What Works on Wall Street](https://www.aaii.com/journal/article/10366-revisiting-the-what-works-on-wall-street-screen)

### 2.4 퀄리티+밸류 결합: Piotroski F-Score (0~9)
값주 중 재무 개선 종목 선별. 각 조건 충족 시 +1.
- 수익성: (1) ROA>0, (2) 영업현금흐름>0, (3) ROA 전년比 개선, (4) 영업CF > 순이익
- 재무건전성: (5) 장기부채/총자산 하락, (6) 유동비율 상승, (7) 신주 발행 없음
- 효율성: (8) 총마진 상승, (9) 자산회전율 상승
- **컷오프: 8~9 매수, 7 이상 필터, 0~2 회피.** 저평가 종목을 먼저 뽑은 뒤 품질 필터로 사용.
- 출처: [Quant-Investing - Piotroski F-Score Guide](https://www.quant-investing.com/blog/piotroski-f-score-complete-guide)

### 2.5 로우볼 / Conservative Formula
- **Conservative Formula**: 저변동성 + 높은 net-payout yield + 강한 가격모멘텀 3조건으로 100종목 선정.
- 출처: [Factor investing (Wikipedia)](https://en.wikipedia.org/wiki/Factor_investing) · [Alpha Architect - Formulaic Investing](https://alphaarchitect.com/formulaic-investing/)

**적용 아이디어**: S&P500 전 종목을 매 리밸런싱 시 **멀티팩터 복합 랭킹**(모멘텀 12-1 + GP/Assets 퀄리티 + Magic Formula 밸류 + 저변동성)으로 점수화, 상위 N%를 스윙 후보 풀로. F-Score ≥ 7을 하드 필터로. 각 팩터는 크로스섹션 z-score 표준화 후 가중합 → 단일 "종목 추천 스코어".

---

## 3. 스윙/모멘텀 기술적 기준

### 3.1 미너비니 Trend Template (Stage 2 확인 8조건 — 하나라도 실패 시 탈락)
1. 현재가 > 150일·200일 이동평균
2. 150일 MA > 200일 MA
3. 200일 MA 최소 1개월(가급적 4~5개월) 상승 추세
4. 50일 MA > 150일 MA & 200일 MA
5. 현재가 > 50일 MA
6. 현재가 ≥ 52주 저점 대비 +30% 이상
7. 현재가 ≤ 52주 고점 대비 −25% 이내(고점의 75% 이상)
8. RS(상대강도) 랭킹 ≥ 70(이상적으로 80+)

SEPA = 트렌드템플릿(추세) + 펀더멘털(강한 EPS/매출 성장) + VCP(변동성 수축 패턴) 돌파 진입.
- 출처: [ChartMill - Minervini Strategy](https://www.chartmill.com/documentation/stock-screener/fundamental-analysis-investing-strategies/464-Mark-Minervini-Strategy-Think-and-Trade-Like-a-Champion-Part-1) · [QuantStrategy.io - SEPA](https://quantstrategy.io/blog/sepa-strategy-explained-mastering-trend-following-with-mark/)

### 3.2 오닐 CANSLIM
- **C** (당분기 EPS): 전년 동분기比 +25% 이상(승자주 다수 +70%+). 매출 동반 성장.
- **A** (연간 EPS): 최근 3년 연 +25% 이상, 높은 ROE.
- **N**: 신제품/신경영/신고가 돌파.
- **S** (수급): 상승 시 평균 대비 높은 거래량(돌파 시 통상 +40~50%). 유통주식수 적을수록 유리.
- **L** (주도주): RS 레이팅 80~90대(상위 20% 성과).
- **I** (기관): 기관 보유 증가.
- **M** (시장): 상승장에서만 매수, follow-through day 확인.
- 진입: 컵앤핸들 등 베이스 형성 후 피봇 포인트 돌파 시 대량 거래 동반.
- 출처: [TrendSpider - CANSLIM](https://trendspider.com/learning-center/canslim-method-by-william-oneil/) · [CFI - CAN SLIM](https://corporatefinanceinstitute.com/resources/equities/can-slim/) · [Deepvue - CANSLIM](https://deepvue.com/fundamentals/canslim-strategy/)

**적용 아이디어**: Trend Template 8조건을 불리언 필터로 코드화(전부 통과해야 후보). RS 레이팅은 S&P500 내 12개월(또는 63/126/252일 가중) 수익률 백분위로 자체 계산(≥70/80 컷). 진입 트리거 = "N주 베이스 고점(피봇) 상향 돌파 + 당일 거래량 ≥ 20일 평균 × 1.4~1.5". C/A는 분기 실적 필터로 결합.

---

## 4. 스크리닝 룰 예시 (Finviz / AAII / Zacks 스타일)

- **오닐형 성장 스크린(AAII Growth Market Leaders)**: 분기 EPS 성장 ≥ 25%, 연 EPS 성장 ≥ 25%, RS 상위, 신고가 근접, 기관 보유.
- **O'Shaughnessy Cornerstone Value**: 대형주 유니버스 + Value Composite 상위 + 높은 주주수익률.
- **O'Shaughnessy Cornerstone Growth**: 전 종목 + P/S 낮음 + 6개월 가격모멘텀 상위.
- **AAII A+ Stock Grades**: Value / Growth / Momentum / Earnings Estimate Revisions / Quality 5팩터 각 A~F 등급 → 복합 등급.
- **Finviz 스타일 모멘텀 스크린**: Price > MA50 > MA200, 52주 고점 −10% 이내, 20일 평균거래량 필터, RSI/성과 필터.
- 출처: [AAII - A+ Power Rankings](https://www.aaii.com/stockideas/powerrankings) · [AAII - O'Shaughnessy Value Screen](https://www.aaii.com/stocks/screens/60) · [AAII - Growth Market Leaders](https://www.aaii.com/stocks/screens/2)

**적용 아이디어**: 위 규칙들을 **선언적 룰셋(YAML/JSON)**으로 정의해 스크리너 엔진에 주입. 예) `momentum_leader = {price>sma50, sma50>sma200, dist_from_52w_high<=0.10, rs_rank>=80, vol20>threshold}`. 여러 스크린을 프리셋으로 두고 추천 모듈이 프리셋별 통과 종목 + 통과 사유를 함께 반환.

---

## 5. 리스크 / 포지션 사이징

- **고정 프랙셔널(1~2% 룰)**: 거래당 계좌자본의 1~2%만 리스크. 주식수 = (자본 × 리스크%) / (진입가 − 손절가).
- **ATR 기반 손절/사이징**: 손절폭 = k × ATR(스윙 통상 k=2~3, 14일 ATR). 변동성 높을수록 사이즈 자동 축소 → 종목 간 리스크 균등화.
- **변동성 타깃팅**: 포지션/포트폴리오를 목표 변동성(예: 연 10~15%)에 맞춰 스케일.
- **켈리 기준**: f* = 승률·손익비 기반 최적 베팅비율. 실무는 하프/쿼터 켈리로 축소. 신뢰엔 50~100 거래 이상 표본 필요, 하드 손절 병용.
- **분산**: 종목 수 분산 + 섹터 상관 고려. 하이브리드 실무: 2% 고정 상한과 ATR 기반 사이즈 중 더 작은 값 채택.
- 출처: [Medium - Position Sizing Frameworks](https://medium.com/@ildiveliu/risk-before-returns-position-sizing-frameworks-fixed-fractional-atr-based-kelly-lite-4513f770a82a) · [Deriv - Kelly Criterion](https://experts.deriv.com/insights/kelly-criterion-position-sizing) · [Trends and Breakouts](https://trendsandbreakouts.com/position-sizing-methods)

**적용 아이디어**: 주문 사이징을 `min(고정 2% 룰, ATR 기반 사이즈)`로 결정. 손절가 = 진입가 − 2×ATR(14). 포트폴리오 단은 목표 변동성 + 섹터/종목 상한(종목 ≤ 10%, 섹터 ≤ 30%). 켈리는 백테스트 추정치에 쿼터 켈리 상한으로 보조 스케일러로만 사용.
> ⚠️ 자본 상한·손절/손실 한도·레짐 주문 정책은 README §4 "사용자 승인 필수 변경 목록"이다. 백테스트 결과나 구현 편의로 자동 확정 금지.

---

## 종합 인코딩 파이프라인 제안

1. **유니버스**: S&P500 (유동성/규모 필터 내장).
2. **펀더멘털 게이트**(분기 갱신): Buffett 필터(ROE/ROTC/부채/FCF) + Piotroski F ≥ 7 + CANSLIM C/A(EPS 성장 ≥ 25%).
3. **멀티팩터 랭킹**: 12-1 모멘텀 + GP/Assets 퀄리티 + Magic Formula 밸류 + 저변동성 → z-score 가중합.
4. **기술적 트리거**(일봉): 미너비니 8조건 전부 통과 + 베이스 피봇 돌파 + 거래량 ≥ 20일평균 ×1.4.
5. **리스크/사이징**: 2×ATR 손절, min(2% 고정, ATR 사이즈), 쿼터 켈리 상한, 섹터/종목 비중 상한.

**구현 관점 주의**: (1) 대부분 컷오프는 원저자 값(ROE 15%, F 7, RS 70/80, EPS 25%, 2% 리스크, 2-ATR)을 그대로 인코딩 가능. (2) "경제적 해자", CANSLIM N/L 같은 정성 항목은 프록시 근사임을 명시. (3) 팩터·스크린은 선언적 룰셋으로 분리해 우리 S&P500 유니버스에 맞게 백테스트로 재보정 권장.
