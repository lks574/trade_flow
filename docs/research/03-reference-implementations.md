# 03. AI 트레이딩 오픈소스 / 논문 레퍼런스

우리 프로젝트(Python · 일봉 스윙 · S&P500 · sentiment 모듈 보유) 기준 코드/아키텍처 참고용. 모든 repo/논문은 WebFetch로 존재 확인. star 수는 조사 시점(2026-07-22) **대략치**이며 적합도 판단은 리서치 판단으로 투자 조언이 아니다.

---

## 1. TradingAgents (TauricResearch)

- **URL**: https://github.com/TauricResearch/TradingAgents · 논문 https://arxiv.org/abs/2412.20138
- **Star / 언어**: ~94k · Python · Apache-2.0
- **무엇**: 실제 트레이딩 회사 조직을 모방한 LLM 멀티에이전트 프레임워크. 애널리스트 → 리서처 토론 → 트레이더 → 리스크팀 → 포트폴리오 매니저 순으로 매매 결정. 이 분야 사실상 표준 레퍼런스.
- **아키텍처**: Analyst 4종(Fundamentals/Sentiment/News/Technical) → Bull vs Bear 연구원 구조화 토론 → Trader 종합 → Risk Management + Portfolio Manager 승인/거절. LangGraph 기반, 멀티 프로바이더(OpenAI/Anthropic/Google/DeepSeek/Ollama), deep-thinking/quick 모델 역할별 분리, 체크포인트·의사결정 로그 영속화. 데이터: Yahoo/Alpha Vantage/FRED/StockTwits·Reddit/뉴스.
- **차용점**: 기존 sentiment 모듈을 Sentiment Analyst 노드로 흡수. Bull/Bear 토론으로 단일 LLM 편향 완화. 역할별 모델 분리로 비용 최적화. 일봉 스윙이면 debate round 1~2로 축소.
- **한계**: 비결정적 샘플링으로 재현성 낮음. 백테스트 성과는 참고용(투자조언 아님). 종목·일자마다 LLM 토론 비용 누적.

---

## 2. ai-hedge-fund (virattt)

- **URL**: https://github.com/virattt/ai-hedge-fund
- **Star / 언어**: ~62k · Python / TypeScript
- **무엇**: 전설적 투자자 14명의 철학을 각각 LLM persona로 구현한 "AI 헤지펀드 팀" 시뮬레이션. 교육/연구 목적, 실주문 미실행.
- **아키텍처**: persona 에이전트(Buffett·Graham·Burry·Cathie Wood·Fisher·Ackman·Taleb·Druckenmiller·Damodaran 등) + 인프라 에이전트(Valuation/Sentiment/Fundamentals/Technical) + Risk Manager(포지션 한도) + Portfolio Manager(최종 결정). 멀티 프로바이더, Financial Datasets API, backtesting 내장.
- **차용점**: "각 persona = pluggable/backtestable alpha model" 재설계 방향. **Risk Manager가 한도 강제 → Portfolio Manager 최종 승인의 2단 게이트**가 리스크 정합성에 좋은 참고.
- **한계**: persona가 실제 성과를 재현한다는 검증 없음. 실거래 미연결. look-ahead 방지는 데이터 API의 as-of 정확도에 의존.

---

## 3. FinRobot (AI4Finance-Foundation)

- **URL**: https://github.com/AI4Finance-Foundation/FinRobot
- **Star / 언어**: ~7.6k · Jupyter/Python
- **무엇**: LLM 기반 금융 분석 에이전트 플랫폼. 애널리스트급 equity research 리포트 자동 생성(DCF/DDM/LBO/WACC/Monte Carlo).
- **아키텍처**: Lead 에이전트가 5개 파이프라인(data/analysis/modeling/synthesis/reporting) + 3개 토론(bull/bear/judge) 조율. 4계층 구조. **핵심 원칙: "Numbers are code-calculated. Narratives are LLM-assisted"** — 재무 수치는 순수 Python 연산, LLM은 추론·서술만. 데이터 7개 소스 + failover.
- **차용점**: ⭐ **"수치는 코드, 서술은 LLM" 원칙이 이 리서치의 최우선 차용 포인트.** 환각 숫자 원천 차단. 데이터 소스 failover 패턴도 유용.
- **한계**: 데스크톱 버전 Apple Silicon 전용. 노트북 형태 코드 다수라 프로덕션 이식 시 리팩터 필요.

---

## 4. FinGPT (AI4Finance-Foundation)

- **URL**: https://github.com/AI4Finance-Foundation/FinGPT
- **Star / 언어**: ~20.9k · Jupyter/Python
- **무엇**: 금융 특화 오픈소스 LLM 모음. Llama-2/Falcon/ChatGLM2/Qwen을 LoRA 파인튜닝, 금융 감정분석에서 GPT-4급 SOTA.
- **아키텍처**: 감정분석 v3.3 FPB F1 0.882 / FiQA-SA 0.903. RTX 3090 한 대 ~$17 학습(저비용 파인튜닝). FinGPT-RAG로 context-enriched 감정예측. LoRA+RLHF(전체 파인튜닝 ~$300 vs BloombergGPT $3M).
- **차용점**: sentiment 모듈을 상용 API 대신 **자체 파인튜닝 소형 모델**로 대체 시 참고(비용·레이턴시 절감). LoRA 레시피·금융 감정 데이터셋 재사용.
- **한계**: 실투자 권고 아님. 감정 라벨 데이터셋 시점·도메인 편향. 주기적 재학습 유지보수 부담.

---

## 5. FinGPT-Forecaster (AI4Finance-Foundation)

- **URL**: https://github.com/AI4Finance-Foundation/FinGPT/tree/master/fingpt/FinGPT_Forecaster (데모: HF Spaces `FinGPT/FinGPT-Forecaster`)
- **Star / 언어**: FinGPT 서브 프로젝트 · Python
- **무엇**: 최근 수 주 뉴스 + 기본 재무 → 긍정 요인/우려 정리 + 다음 주 주가 방향·근거 요약 출력하는 경량 robo-advisor.
- **아키텍처**: Llama-2-7b-chat을 1년 DOW30 데이터로 LoRA 파인튜닝. 단일 모델 프롬프트 파이프라인. 출력 4블록(긍정/우려/방향/요약).
- **차용점**: "뉴스+재무 → 방향성 + 근거"의 최소 파이프라인. next-week 지평이 우리 일봉 스윙(주 단위 홀딩)과 부합. 4블록 프롬프트를 리포트 템플릿으로 활용.
- **한계**: 저자 스스로 "데모일 뿐, 무작위 뉴스 선택 시 강한 편향" 명시. 백테스트 미검증. 뉴스 선택이 look-ahead·survivorship 원천.

---

## 6. FinMem (pipiku915)

- **URL**: https://github.com/pipiku915/FinMem-LLM-StockTrading · 논문 https://arxiv.org/abs/2311.13743 (AAAI 2024)
- **Star / 언어**: ~0.93k · Python · MIT
- **무엇**: 계층적 메모리 + 캐릭터(성향) 설계를 갖춘 LLM 트레이딩 에이전트. 인간 트레이더 인지구조 모방.
- **아키텍처**: Profiling(성향·리스크) + Memory(단/중/장기 계층, cognitive span 조절) + Decision-making. **Training 모드(과거로 메모리 채움) / Testing 모드(신규 데이터 매매) 분리.**
- **차용점**: 계층적 메모리로 "최근 뉴스(단기) vs 실적 추세(장기)" 구분 반영. **Train/Test 모드 분리는 백테스트 look-ahead를 구조적으로 막는 좋은 패턴.**
- **한계**: 성과·리스크 관리 상세 부족. 메모리 검색 토큰 비용. 단일 종목 중심 → S&P500 스케일링 별도 작업.

---

## 7. FinCon (논문)

- **URL**: https://arxiv.org/abs/2407.06567 (NeurIPS 2024)
- **Star / 언어**: 논문 기반(공식 재현 코드 제한적)
- **무엇**: Conceptual Verbal Reinforcement를 도입한 LLM 멀티에이전트. 매니저-애널리스트 계층 구조.
- **아키텍처**: Manager-Analyst 계층 + Risk-control 컴포넌트가 에피소드마다 self-critique로 "투자 신념" 갱신. 개념화된 신념이 언어적 강화(verbal RL)로 작동, 선택적 전파.
- **차용점**: 손실/실패 후 self-critique로 **프롬프트 수준 학습**(파인튜닝 없이 저비용 개선). 백테스트 루프에 "실패 사례 → 신념 업데이트" 회고 단계 추가.
- **한계**: 논문상 누적수익 23~400%는 특정 기간·종목 결과로 과최적화·체리피킹 우려. 공식 오픈소스 repo 제한적.

---

## 8. RD-Agent + Qlib (Microsoft)

- **URL**: https://github.com/microsoft/RD-Agent · https://github.com/microsoft/qlib · 논문 https://arxiv.org/abs/2505.15155 (NeurIPS 2025)
- **Star / 언어**: RD-Agent ~14k, Qlib 다수 · Python
- **무엇**: RD-Agent(Q)는 quant 전략 R&D 전체(팩터 발굴 + 모델 최적화) 자동화 멀티에이전트. Qlib은 데이터→학습→백테스트 전 파이프라인의 검증된 AI 퀀트 플랫폼.
- **아키텍처**: RD-Agent가 팩터·모델 교대 최적화(alternating co-optimization) 반복 제안·검증, LLM은 리서치 종합에 사용(LiteLLM). 벤치마크 대비 ~2배 ARR을 팩터 70% 적게 사용, 비용 <$10. Qlib은 알파탐색·리스크모델링·포트폴리오최적화·주문실행 + 검증된 백테스트 엔진.
- **차용점**: ⭐ **Qlib의 백테스트/데이터 핸들러**는 우리 일봉 S&P500 파이프라인에 붙일 수 있는 검증된 인프라(point-in-time으로 look-ahead 방지). LLM으로 팩터 아이디어 생성 → Qlib 엄격 검증하는 "생성-검증 분리"가 이상적 모델.
- **한계**: RD-Agent는 Linux + Docker 전용. 자동 팩터 탐색은 과최적화 위험 → out-of-sample·walk-forward 필수. Qlib 학습곡선 가파름.

---

## 9. Financial Research Analyst Agent (gsaini)

- **URL**: https://github.com/gsaini/financial-research-analyst-agent
- **Star / 언어**: ~41 · Python
- **무엇**: 11개 전문 에이전트 + 20여 분석 도구 + RAG + 멀티 프로바이더 데이터층의 계층형 종합 분석 시스템(Streamlit/REST/CLI).
- **아키텍처**: 11 에이전트(Data Collector/Technical/Fundamental(DCF·SEC RAG)/Sentiment(FinBERT·VADER)/Risk(VaR·CVaR·Monte Carlo)/Thematic/Disruption/Earnings/Performance/Report/Orchestrator). **RAG: SEC 10-K/10-Q/8-K·어닝콜 → 시맨틱 청킹 → Sentence Transformer 임베딩 → ChromaDB → cross-encoder 재랭킹.** 데이터 YFinance/FMP/Alpha Vantage failover, Redis 캐시, PostgreSQL. LLM 기본 Ollama 로컬.
- **차용점**: ⭐ **RAG로 SEC 공시·어닝콜을 검색해 fundamental 분석에 주입하는 구성**이 우리 목표와 가장 직접 일치. ChromaDB + cross-encoder 재랭킹 스택, 멀티 프로바이더 failover + 캐시, 에이전트별 confidence score 참고.
- **한계**: 커뮤니티 소규모(별 41, 검증 부족). Monte Carlo·백테스트 무겁고 인프라 의존. 데이터 품질이 업스트림 종속.

---

## 10. LLM Stock Team Analyzer (jason8745)

- **URL**: https://github.com/jason8745/llm-stock-team-analyzer
- **Star / 언어**: ~32 · Python
- **무엇**: LangGraph 기반 5개 에이전트로 기술적분석·뉴스감정·추천을 종합하는 경량 멀티에이전트(TradingAgents 슬림 버전).
- **아키텍처**: Market Analyst(지표 지능 선택)/News Analyst(Google News)/Bull·Bear Researcher(토론)/Trader. 지표 지능 선택: MA/MACD/RSI/Bollinger/KDJ/ATR/OBV/ADX 중 시장 상황에 맞춰 2~3개만. Azure OpenAI.
- **차용점**: TradingAgents가 무거우면 최소 구현 레퍼런스로 이식 쉬움. **"시장 상황에 따라 지표 2~3개만 동적 선택"** 아이디어가 일봉 스윙 노이즈 감소에 유용. rate limit/retry 방어 코드 참고.
- **한계**: Azure OpenAI 종속, 소규모/초기. Google News 쿼리 제약. 백테스트 미검증.

---

## 11. TradingGoose

- **URL**: https://github.com/TradingGoose/TradingGoose.github.io
- **Star / 언어**: ~74 · TypeScript · AGPL-3.0
- **무엇**: 개별 종목 분석 + 포트폴리오 관리를 함께 다루는 멀티에이전트 플랫폼. 실제 브로커(Alpaca) 연동 포함.
- **아키텍처**: Coordinator + Market/Fundamentals/News/Social Analyst + **Risk Analyst Squad(보수/중립/공격 3관점)** + Portfolio Manager. 3단계: ①6에이전트 병렬 분석 → ②conviction score 종합 → ③Portfolio Manager가 제약 검증 후 Alpaca 주문. 자동 리밸런싱(일/주/월).
- **차용점**: 리스크를 단일 값이 아닌 **보수/중립/공격 3관점 병렬 평가하는 squad 패턴**. Portfolio Manager가 사이징·제약을 강제하고 권고를 오버라이드하는 execution discipline. conviction score 기반 랭킹은 스윙 선별에 응용.
- **한계**: TypeScript라 우리 Python 스택과 언어 불일치(개념만 차용). Perplefina 별도 배포. 실거래 연동은 검증·규제 리스크 큼.

---

## 우리 프로젝트 종합 결론 5가지

1. **"수치는 코드, 서술은 LLM" 원칙 채택 (FinRobot)** — 지표·시그널·밸류에이션은 결정론적 Python으로, LLM은 근거 서술·종합·리포트에만. 환각 숫자 원천 차단.
2. **백테스트 인프라는 Qlib 참고 (Microsoft)** — point-in-time 처리로 look-ahead 구조적 방지. LLM 아이디어 생성 → Qlib 엄격 검증의 "생성-검증 분리". (단, 현 canonical 소스는 `data/trade_flow.db`이며 도입 여부는 tech spec·승인 절차 준수.)
3. **에이전트 구조는 TradingAgents / ai-hedge-fund 참고, 일봉 스윙에 맞게 축소** — debate round·에이전트 수 축소로 비용 절감. 기존 sentiment 모듈은 Sentiment Analyst 노드로 편입. RAG 재무·공시 검색은 gsaini 구성(ChromaDB + 재랭킹) 참고.
4. **안전한 개선 루프 조합** — 리스크 2단 게이트(Risk Manager → Portfolio Manager) + FinMem Train/Test 모드 분리(look-ahead 차단) + FinCon self-critique 회고 루프(파인튜닝 없이 프롬프트 개선)를 결합하면 과최적화 없이 개선 가능.
5. **공통 한계를 전제로 검증 강제** — 대부분 프로젝트가 (1) 백테스트 미검증/체리피킹, (2) LLM 비결정성으로 재현성 낮음, (3) 뉴스·감정의 look-ahead·survivorship 편향, (4) 실투자 조언 아님을 안고 있음. 성과 수치(예: FinCon 23~400%)를 그대로 신뢰하지 말고 out-of-sample·walk-forward로 자체 검증.

---

## 출처 목록

- TradingAgents — https://github.com/TauricResearch/TradingAgents · https://arxiv.org/abs/2412.20138
- ai-hedge-fund — https://github.com/virattt/ai-hedge-fund
- FinRobot — https://github.com/AI4Finance-Foundation/FinRobot
- FinGPT — https://github.com/AI4Finance-Foundation/FinGPT
- FinGPT-Forecaster — https://github.com/AI4Finance-Foundation/FinGPT/tree/master/fingpt/FinGPT_Forecaster
- FinMem — https://github.com/pipiku915/FinMem-LLM-StockTrading · https://arxiv.org/abs/2311.13743
- FinCon (논문) — https://arxiv.org/abs/2407.06567
- RD-Agent — https://github.com/microsoft/RD-Agent · https://arxiv.org/abs/2505.15155
- Qlib — https://github.com/microsoft/qlib
- Financial Research Analyst Agent — https://github.com/gsaini/financial-research-analyst-agent
- LLM Stock Team Analyzer — https://github.com/jason8745/llm-stock-team-analyzer
- TradingGoose — https://github.com/TradingGoose/TradingGoose.github.io
- awesome-ai-in-finance (큐레이션) — https://github.com/georgezouq/awesome-ai-in-finance
