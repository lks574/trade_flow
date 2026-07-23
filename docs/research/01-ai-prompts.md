# 01. LLM 종목분석 프롬프트 템플릿 (공개 자료)

공유되는 미국 주식 분석 프롬프트는 대부분 **"역할 부여(You are a senior equity analyst) → 입력값([TICKER]) → 구조화된 항목 리스트 → 출력 포맷(테이블/불릿) 지정"** 패턴을 따른다. verbatim 원문은 CFI, GitHub `awesome-prompts`, AI Academy에서 확보했고, Basis Report/Nexxant 등은 앞부분만 공개되어 `[…이하 공개]`로 표시했다.

> ⚠️ 공통 한계: (1) LLM이 재무 수치를 **환각**할 수 있음, (2) 학습 컷오프로 인한 **데이터 최신성** 문제. 대부분 출처가 "숫자는 1차 자료(10-K/10-Q)로 재검증"을 명시. 우리 시스템에서는 [03 FinRobot 원칙] "수치는 코드, 서술은 LLM"과 결합해 사용할 것.

---

## 1. 재무분석 (Financial Statement Analysis)

### 1-1. 사업모델·매출 세그먼트 분해 (CFI)
```
You are a fundamental equity research analyst. For [Company Name] ([Ticker]), a [Sector] company, provide: (1) a breakdown of revenue segments and their approximate percentage of total revenue over the last three fiscal years; (2) major cost drivers and key sources of operating leverage; (3) an explanation of the pricing model and primary distribution channels. Present as a structured table followed by a brief narrative summary.
```
목적: 매출 구성/원가 동인/가격 모델. 코멘트: 모범 구조. 세그먼트 %는 10-K 주석과 대조 필수.

### 1-2. 매출 성장·마진 추세 (CFI)
```
You are a fundamental equity analyst reviewing [Company Name] ([Ticker]). Summarize: (1) annual revenue growth rates over the last three to five fiscal years; (2) gross margin, operating margin, and net margin trends over the same period, noting any material shifts; (3) the primary drivers of margin change, such as pricing, product mix, or cost structure. Present revenue and margin data in a table, followed by a narrative explanation of key drivers.
```
목적: 3~5년 매출/마진 추세와 변화 동인. 과거 수치 재확인 필요.

### 1-3. 현금흐름·레버리지 (CFI)
```
For [Company Name] ([Ticker]), evaluate: (1) free cash flow generation over the last three fiscal years, including FCF conversion from net income; (2) major uses of cash, including capex, acquisitions, dividends, and buybacks; (3) current leverage ratios, including net debt to EBITDA and interest coverage; and (4) balance sheet flexibility and refinancing risk. Present as a structured summary followed by a brief risk assessment.
```
목적: FCF 창출력·자본배분·레버리지·리파이낸싱 리스크. FCF 전환율·Net Debt/EBITDA 실무 지표 명시.

### 1-4. 10-K 사업개요·리스크 파싱 (CFI) — 권장
```
I will paste the Business Overview and Risk Factors sections from [Company Name]'s ([Ticker]) most recent 10-K. Please: (1) summarize the business description in no more than 100 words; (2) identify and rank the top five risk factors by potential financial impact; and (3) flag any risk disclosures that are new or materially changed from what would be typical for this sector.
```
목적: 10-K 원문 붙여넣기 → 요약·리스크 랭킹·신규 리스크. **원문 직접 입력이라 환각 위험 감소.**

### 1-5. 다분기 어닝콜 트렌드/톤 (CFI)
```
I am going to paste the transcripts from [Company Name]'s ([Ticker]) last four earnings calls. For each call: (1) summarize key messages and any changes to revenue, margin, or capital allocation guidance; (2) identify tone shifts, noting whether management became more optimistic or cautious and why; (3) flag any analyst questions management consistently deflected. Organize by call date in chronological order.
```
목적: 최근 4분기 가이던스 변화·경영진 톤·회피성 답변. 톤 판단은 주관적, 참고용.

### 1-6. 가이던스 실행 스코어카드 (CFI)
```
Using the earnings transcripts I will provide for [Company Name] ([Ticker]), create a guidance scorecard covering the last four quarters. For each quarter, track: (1) guidance provided for revenue, margins, and other explicitly guided metrics; (2) actual outcomes versus that guidance; and (3) a 'met, missed, or exceeded' designation for each commitment. Summarize management's overall execution track record at the end.
```
목적: 가이던스 대비 실제치 "달성/미달/초과" 스코어링. 경영진 실행력 정량화.

### 1-7. 이익의 질 레드플래그 스캐너 (Basis Report, 앞부분만 공개)
```
Analyze [TICKER]'s most recent 10-K filing for earnings quality red flags. [...이익 조작 경고 신호 스캔 항목만 공개]
```
목적: 매출 인식/발생액 등 조작 경고. Beneish M-Score(8변수) 계산은 LLM이 틀리기 쉬움 → 재검증.

### 1-8. 3대 재무제표 추출 4종 (Nexxant, 앞부분만 공개)
```
What are the key financial indicators for the stock [TICKER]...
Provide a comprehensive overview of the balance sheet for... (3-year)
Retrieve the latest Income Statement (Profit & Loss) data... (YoY)
What are the main components of the cash flow statement... (3-year)
```
목적: 재무제표 3년 시계열. 데이터 수집형 — LLM 단독으론 최신·정확 보장 불가, 웹검색/파일 병행.

---

## 2. 밸류에이션 (Valuation)

### 2-1. 종합 펀더멘털 + 강세/약세 결론 (AI Academy) — 만능형
```
Analyze [ticker] fundamentals. Include: business model + revenue segments, revenue growth 3yr/5yr, profit margins trend, debt/equity, free cash flow, P/E vs industry, moat + competitive advantages, management track record, major risks, bull case / bear case / verdict.
```
목적: 원스톱 펀더멘털 + 강세/약세/결론. 항목 압축적이라 각 답이 얕아질 수 있음.

### 2-2. 배수 기반 상대가치 (CFI)
```
For [Company Name] ([Ticker]), compare current valuation multiples, including P/E, EV/EBITDA, EV/FCF, and P/B where relevant, to: (1) the peer group consisting of [Peer 1], [Peer 2], and [Peer 3]; and (2) the company's own five-year historical average. For each multiple, indicate whether the stock trades at a premium, discount, or in-line, and explain whether any premium or discount appears justified based on fundamentals.
```
목적: 동종/자체 5년 평균 대비 프리미엄·디스카운트. 배수 시점/출처 검증.

### 2-3. DCF 시나리오 프레임워크 (CFI) — 권장
```
Discuss the key assumptions a DCF analysis of [Company Name] ([Ticker]) would need to address. Without building a full model, describe: (1) the revenue growth trajectory and key drivers for a base, bull, and bear case; (2) margin assumptions and where they could diverge from consensus; (3) the terminal growth rate range you'd consider reasonable; and (4) the key sensitivities that would most affect intrinsic value. Frame as a scenario narrative rather than a numerical model.
```
목적: 숫자 모델 대신 DCF **가정**을 시나리오로. 숫자 환각 회피 설계.

### 2-4. 10년 DCF 모델 빌더 (Basis Report, 앞부분만 공개)
```
Build a 10-year DCF model for [TICKER]. Use these assumptions: Revenue growth: [X]% declining to [Y]% by year 10... [출력: 연도별 매출/FCF/할인가치 → 내재주가 vs 현재가]
```
목적: 명시 가정으로 10년 DCF. 사용자 가정 입력으로 환각 통제. LLM 산술 오류 가능 → 스프레드시트 교차검증.

### 2-5. 역DCF (Reverse DCF) (Basis Report, 앞부분만 공개)
```
Run a reverse DCF analysis for [TICKER] at the current price of $[X]. [현재 FCF·WACC·영구성장률 → 시장 반영 내재 성장률 역산 → 현실성 판단]
```
목적: 주가에 내포된 성장률 역산. 개념 프레임 훌륭, 산술 검증 필요.

### 2-6. Graham Number / SOTP / Comparable (Basis Report, 앞부분만 공개)
```
Calculate the Graham Number for [TICKER] using the formula: sqrt(22.5 × EPS × Book Value Per Share).
Perform a sum-of-the-parts (SOTP) valuation for [TICKER].
Create a comparable company analysis for [TICKER]. Include these 5 peers...
```
목적: 그레이엄 내재가치 / 사업부 합산 / 피어 배수. Graham Number는 공식 명시라 재현성 높음(입력 정확성 의존).

### 2-7. ROIC vs WACC 가치창출 진단 (CFI)
```
Discuss whether [Company Name] ([Ticker]) is currently creating or destroying shareholder value based on ROIC vs. WACC. Using available information: (1) describe the company's approximate ROIC range and trend over the last three to five years; (2) identify the primary drivers of ROIC; and (3) outline what would need to change to meaningfully alter the ROIC trajectory.
```
목적: ROIC-WACC 스프레드로 가치 창출/파괴. "approximate range"로 환각 다소 통제.

---

## 3. 기술적분석 (Technical Analysis)

> ⚠️ **가장 위험한 카테고리.** LLM은 실시간 가격/차트 접근이 없어 지지·저항·손절 레벨을 지어낼 수 있음. 실제 차트 데이터/스크린샷 없이는 신뢰 불가. 우리 시스템에서는 지표를 코드로 계산([02 §3])하고 LLM엔 해석만 맡길 것.

### 3-1. 차트 패턴 인식 (AI Academy)
```
Analyze [ticker] chart patterns. Timeframe: [describe]. Include: current trend, support/resistance levels, key moving averages (50/200 day), volume patterns, bullish/bearish patterns identified, entry/exit levels, stop loss placement.
```

### 3-2. 진입/청산 계획 (AI Academy)
```
Plan entry/exit for [ticker]. Thesis: [describe]. Include: target entry price (current, on dip, scaled-in), position size (% of portfolio), stop loss level, profit targets (multiple levels), fundamental trigger for exit beyond price.
```
가격 외 "펀더멘털 청산 트리거" 요구가 좋음. 가격 레벨은 실데이터 기반 검증.

### 3-3. 기술지표 해설형 (LearnPrompt) — 교육용
```
Explain the [Specific Technical Indicator, e.g., 'Relative Strength Index (RSI)'] ... how to combine indicators like MACD and Bollinger Bands for more robust signals ... interpret [Head and Shoulders] chart pattern ...
```
개념 설명엔 유용. 매매 신호 생성엔 부적합.

---

## 4. 스크리닝 (Screening / Idea Generation)

### 4-1. 스크리닝 기준 생성 (CFI) — 매우 실용적
```
Suggest screening criteria to identify [quality / value / growth] stocks in the [Sector] sector in [Region] markets. For each criterion, include: (1) the financial metric or qualitative filter; (2) the threshold or characteristic to screen for; and (3) a brief rationale for why it's relevant to the stated strategy. Present as a numbered filter list I can translate into a screening tool.
```
목적: 전략별 스크리너 필터 조건. **LLM이 종목을 고르는 게 아니라 조건을 만들게 해 환각 우회.** → [02 §4] 룰셋과 직결.

### 4-2. 섹터 특화 스크리닝 (CFI)
```
What financial and qualitative criteria would you use to screen for high-quality software companies in [Region] with at least [X]% three-year revenue CAGR, improving operating leverage, and evidence of durable competitive advantage?
```
조건 도출용으로 안전. 종목 리스트 직접 요구 시 오래된/틀린 종목 위험.

### 4-3. 섹터 투자테마 (AI Academy)
```
Analyze [sector] investment thesis. Include: growth drivers [...leaders, disruptors, valuations 항목]
```
톱다운 아이디어 발굴. 특정 기업/수치 재검증.

---

## 5. 뉴스·감정 분석 (News & Sentiment)

### 5-1. 감정 아비트리지 스캐너 (MarketScreener/Barchart, 요약) — ⚠️ 홍보성
```
Sentiment Arbitrage Scanner — 리테일 감정(Reddit/Twitter/StockTwits 언급량·톤)과 기관 포지셔닝(13F 변화/옵션 플로우) 비교 → 괴리(divergence)·감정 극단 탐지.
```
**주의: "$50M 수익" 등 검증 불가 홍보 콘텐츠(Chatronix 광고).** 프레임(리테일-기관 괴리)만 참고. LLM은 실시간 13F/옵션/StockTwits 직접 접근 불가.

### 5-2. 티커/섹터 감정 요약 (fintwit.ai)
```
Analyze sentiment for [Stock Ticker] from recent news and social media. Provide an overview of whether it's predominantly bullish, bearish, or neutral. What are the main drivers of this sentiment, and how has it shifted compared to previous periods?
Search the web for recent headlines about [stock/sector], then analyze the current market sentiment (bullish/bearish/neutral) and why.
```
**웹검색 켜진 모델**에서만 유의미. 감정 판단은 표본 편향·최신성 이슈. → [04] 소셜 소스와 결합.

### 5-3. 어닝 리포트 해석 (AI Academy)
```
Break down [company] earnings. Beat/miss EPS: [describe]. [...핵심 지표·질·주가 시사점 항목]
```
실적 수치를 사용자 입력하므로 상대적으로 안전.

---

## 6. 포트폴리오·리스크 (Portfolio & Risk)

### 6-1. 리스크 식별·매핑 (CFI) — 추천
```
For [Company Name] ([Ticker]), identify the top five business and investment risks by category: demand risk, pricing power risk, input cost risk, regulatory risk, and competitive disruption. For each risk: (1) estimate likelihood (low, moderate, or high) and potential financial impact (limited, material, or severe); (2) identify one or two early-warning indicators that would suggest the risk is materializing.
```
"조기경보 지표"까지 요구해 모니터링에 실용적.

### 6-2. 투자논리 스트레스 테스트 (CFI) — 확증편향 방지 탁월
```
Articulate the core investment thesis for [Company Name] ([Ticker]) in no more than four sentences. Then identify: (1) the three to five scenarios that would most directly invalidate this thesis; (2) the key assumptions most vulnerable to being wrong; and (3) any base rate evidence or historical analogies suggesting this type of thesis has failed before in similar circumstances.
```
"base rate/역사적 유사사례" 요구가 핵심 강점.

### 6-3. 강세/기본/약세 시나리오 + 기대값 (Basis Report, 앞부분만 공개)
```
Build a bull case, base case, and bear case for [TICKER]. [각 시나리오: 핵심 가정, 계산 과정을 보인 3년 목표주가, 확률 가중치, 촉매/리스크 → 확률가중 기대값 vs 현재가]
```
"show the math"가 검증에 유리. 확률 가중치는 자의적.

### 6-4. 리스크 매트릭스 / 촉매 타임라인 / 사이징 (Basis Report, 앞부분만 공개)
```
Build a risk matrix for an investment in [TICKER].
Build a catalyst timeline for [TICKER] covering the next 12 months.
Help me determine the right position size for [TICKER] in my portfolio.
```
촉매 타임라인은 미래 이벤트라 LLM이 날짜 지어낼 수 있음(실적일정 확인).

### 6-5. 포트폴리오 리밸런싱 (AI Academy)
```
Rebalance my portfolio. Current: [holdings and %]. Target: [describe]. Include: drift analysis, which positions to trim, which to add, tax implications (taxable account), timing (calendar vs threshold), specific trade list.
```
보유내역 입력이라 실용적. 세금 규칙은 관할별 검증.

### 6-6. 자산배분 포트폴리오 (AI Academy)
```
Build stock portfolio. Amount: [$]. Age: [X]...
Build 3-fund Boglehead portfolio. Amount: [$]...
Build dividend income portfolio. Target income: $[amount]/month...
```
자산배분 개념 학습·초안용. "금융조언 아님" 원문 명시.

### 6-7. 투자 메모 작성 (Basis Report, 앞부분만 공개)
```
Write a concise investment memo for [TICKER] in the style of a hedge fund analyst. [회사 개요, 투자논리, 핵심지표 테이블, 촉매, 리스크, 2가지 방법 밸류에이션, 진입가·비중 → 최종 결론]
```
여러 분석 종합 마무리용. 포함 수치는 앞 단계에서 검증된 값만.

---

## 부록: 세션 프라이밍 / 환각 방지 프롬프트

### A. 프라이밍 (CFI)
```
For this session, act as a senior equity research analyst with a fundamental, long-term investment orientation. Prioritize durable business quality, financial statement rigor, and intrinsic value. Avoid commentary on intraday price movements, technical indicators, or market sentiment. Focus on [Company Name] ([Ticker]), a [Sector] company. Confirm that you understand this role before we begin.
```

### B. 환각 방지 출처 추적 (CFI) — ⭐ 매우 중요
```
Review your previous response about [Company Name] ([Ticker]) and list every specific numerical figure you cited. For each number, identify: (1) the source document or filing it came from; (2) the specific section or line item where it appears; and (3) whether it is a directly reported figure, a calculated metric, or an estimate. Flag any numbers that you cannot trace to a primary source.
```
LLM 재무분석의 최대 약점(수치 환각)을 직접 겨냥한 검증 프롬프트. 모든 분석 세션 마지막에 실행 권장.

### C. 투자 리서치 애널리스트 시스템 프롬프트 (GitHub awesome-prompts)
```
You are a senior equity research analyst with 15+ years at a top-tier investment bank and asset management firm ...
[5단계: 1) Business Model(Porter's Five Forces) 2) Financial Health 3) Competitive Positioning/moat 4) Valuation(EV/EBITDA, P/E, DCF 2~3개) 5) Investment Thesis(bull/bear + catalysts). 출력: 500~800단어 구조화 노트 + 방향성 추천]
```
커뮤니티 표준형. "부정적 증거도 인정하라"는 품질 기준 포함이 장점.

---

## 종합 코멘트 (실무 시사점)

- **가장 안전·유용한 패턴**: 사용자가 원문(10-K, 트랜스크립트, 보유내역)이나 가정을 **직접 입력**하고, LLM은 요약·구조화·시나리오·검증을 맡는 프롬프트(1-4, 1-5, 2-3, 4-1). 반대로 종목/수치/차트 레벨을 LLM이 **생성**하는 프롬프트(3-1, 5-1, 6-4)는 환각·최신성 위험 큼.
- **기술적·감정 분석은 실시간 데이터 연동(웹검색/API/차트 첨부) 없이는 신뢰 불가.** 개념 설명·프레임 제공용으로만.
- **거의 모든 신뢰 출처가 공통 경고**: 금융 조언 아님, 숫자는 1차 자료 재검증, 가격 예측 금지, 컷오프 인지.
- **홍보성/과장 출처 주의**: MarketScreener/Barchart "$50M 프롬프트" 계열은 수익 주장이 검증 불가한 광고성. 프레임만 참고.
- Reddit/X verbatim 원문은 대부분 Gumroad 유료 팩·블로그 요약으로 리다이렉트되어 확보 어려웠으나, 커뮤니티 복붙 형태는 위 CFI/AI Academy/awesome-prompts 구조와 사실상 동일.

---

## 출처 목록

1. Corporate Finance Institute — https://corporatefinanceinstitute.com/resources/artificial-intelligence-ai/best-ai-prompts-for-stock-analysis/
2. GitHub ai-boost/awesome-prompts — https://github.com/ai-boost/awesome-prompts/blob/main/prompts/investment_research_analyst.txt
3. AI Academy / Techpresso — https://academy.techpresso.co/prompts/chatgpt-prompts-stock-market
4. Basis Report — https://www.basisreport.com/resources/stock-analysis-prompts
5. Nexxant — https://www.nexxant.com.br/en/post/20-chatgpt-prompts-to-supercharge-fundamental-analysis-stocks-crypto
6. fintwit.ai — https://fintwit.ai/blog/how-to-use-chatgpt-for-stock-research
7. LearnPrompt — https://learnprompt.org/chatgpt-prompts-for-stock-trading/
8. MarginLab — https://margin-lab.com/blog/ai-trading-prompts
9. MarketScreener (홍보성) — https://www.marketscreener.com/news/wall-street-s-hidden-chatgpt-strategy-3-prompts-worth-50m-in-trades-ce7d5bdcdd81f223
10. Barchart (동일 보도) — https://www.barchart.com/story/news/35225103/
11. WallStreetZen — https://www.wallstreetzen.com/blog/how-to-use-chatgpt-for-stock-picks/
12. Prospero.ai — https://www.prospero.ai/resources-blog/5-chatgpt-prompts-for-stock-picking
13. AI Agents Kit — https://aiagentskit.com/blog/chatgpt-prompts-for-financial-analysts/
