# 04. 소셜 시그널 / 감정 데이터

기존 `src/trade_flow/sentiment/` 모듈을 확장하는 것을 전제로 조사했다.

## 우리 모듈 현재 상태 (조사 시 확인)

- **인터페이스**: `SentimentProvider` Protocol — `articles(symbol, session_date)`로 종목·날짜별 기사 반환 (`collector.py`)
- **데이터 모델**: `SentimentArticle(score∈[-1,1], relevance∈[0,1])` → `aggregate_sentiment`가 relevance 가중 평균으로 일별 `SentimentObservation` 생성 (`model.py`)
- **후보 선정**: 전략 스코어 상위 종목만 (`shadow_candidates`, `configs/strategy.toml`: `candidate_limit=20`)
- **검증**: `evaluate_sentiment`가 rank IC(스피어만)를 forward return 지평 `[1, 5, 20]`에 대해 계산, `minimum_observation_sessions=60` 미만이면 `insufficient_observation_period` 반환
- **현재 소스**: 감정점수는 Alpha Vantage 기반 Phase 2, 아직 미구현

즉 "섀도 팩터 + 일별 스코어 + rank IC 전방검증(60거래일)" 골격은 완성돼 있고, 필요한 것은 **(a) Provider 소스 다변화, (b) 멘션/버즈 지표 추가 정량화**다.

---

## 1. 데이터 소스별 접근성·비용

| 소스 | 무엇 | 접근/비용 | 적용 |
|---|---|---|---|
| **ApeWisdom** | Reddit(WSB 등 14개 서브레딧) 티커 멘션 카운트·랭크·upvote 집계 | 공개 REST, 인증 불필요. `apewisdom.io/api/v1.0/filter/{filter}` | **가장 현실적인 1차 소스.** buzz factor 즉시 생성 |
| **Quiver Quantitative** | WSB 멘션+랭크+sentiment, 2018.8~ 약 6,000종목 히스토리 | 유료 $10/월~, `quiverquant` PyPI | 히스토리 백필 → 60거래일 전방검증 백테스트에 유리 |
| **StockTwits** | 메시지별 유저 태그 Bullish/Bearish, 트렌딩 티커 | 공개 엔드포인트 일부 무인증, 호출당 최대 30 메시지. 최근 접근 제한 강화 추세 | 유저 태그가 곧 라벨 → 모델 없이 score 산출 |
| **뉴스 헤드라인** | 티커 태깅 뉴스 + 감정 | Alpha Vantage(무료 25콜/일, article+ticker 방향+강도), Marketaux(100req/일, 방향만), Finnhub, Tiingo(감정필드 없음) | 이미 Alpha Vantage 설계됨. 무료 25콜/일이 candidate_limit=20과 부합. Marketaux 보조 다중화 |
| **X/Twitter** | 캐시태그($TSLA) 언급 | 2026.2부터 신규는 종량제(포스트 read $0.005), 학술 트랙 폐지 | **비추천** — 비용/제약 대비 실익 낮음 |

**결론**: 무료·현실적 조합 = **ApeWisdom(멘션) + StockTwits(유저 태그 감정) + Alpha Vantage/Marketaux(뉴스 감정)**. X는 배제.

---

## 2. 정량화 방법

1. **티커 멘션 카운트(buzz)**: ApeWisdom `mentions` / `mentions_24h_ago`로 raw count·변화율. buzz 자체를 별도 팩터로.
2. **감정 스코어링**:
   - *금융 특화 모델*: **FinBERT** (HuggingFace `ProsusAI/finbert`). 텍스트를 positive/neutral/negative 3분류 → `[-1,1]` 매핑. `SentimentArticle.score` 스키마와 호환.
   - *유저 태그*: StockTwits Bullish/Bearish는 라벨 자체라 모델 불필요.
3. **버즈/모멘텀 지표**: 멘션 이동평균 대비 z-score, 24h 랭크 상승폭.
4. **이상 급증 탐지(intensity burst)**: 롤링 기준선 대비 멘션 z-score > 임계값 이벤트 플래그.

**적용 아이디어**: `SentimentObservation`에 `buzz`(멘션 z-score) 필드 추가, 기존 `score`(감정)와 **별개의 두 섀도 팩터**로 각각 rank IC를 [1,5,20]일 지평에서 평가. 감정보다 버즈(어텐션)가 단기(1~5일) IC가 더 강할 가능성.

---

## 3. 실증 근거 (공개 논문)

- **Bradley et al. "Place Your Bets?" (SSRN 3806065, 2021)**: GME 숏스퀴즈 **이전**에는 WSB 추천이 수익률을 유의하게 예측했으나 **GME 이후 예측력 완전 소멸**. → 레짐 의존성·look-ahead 시점 관리 중요.
- **Wei et al. "Intensity Bursts in WallStreetBets" (SSRN 5030887, 2024)**: WSB 제출량 급증과 거래회전율·초과수익 간 인과관계. 장중 버스트가 더 강하나 **반나절 단위 빠른 반전**. → 단기 신호, 반전 리스크.
- **Li & Li "Sentiment, Social Media, and Meme Stock" (SSRN 4947010, 2024)**: Google 검색 감정은 중기(3~7일), Bloomberg 뉴스 감정은 장기(7~14일) 예측. → 소스별 예측 지평 상이, 다지평 IC([1,5,20]) 설계와 부합.
- **Lee et al. "Abnormal Trading Volume" (SSRN 2812010)**: 이상 거래활동 예측력이 최대 5주(≈25거래일)까지 (+). → 20일 지평 합리적, 60일 관측창 타당.

**요지**: 소셜 신호는 단기(1~14일) 예측력 존재하나 빠르게 반전되고 레짐 의존적. 섀도 팩터로 IC를 먼저 검증하려는 우리 접근이 정확히 맞음.

---

## 4. 함정

- **봇/펌핑(pump & dump)**: 소형주 대상 조작 성행, 봇넷이 감정 점수 인위 부풀림. → 게시자 다양성/신규계정 비율 필터, 극단 급증 시 downweight. (arXiv 2301.11403)
- **소형주 편향**: 시총 $2B 미만은 노이즈·조작 취약. → 우리 유니버스가 **S&P500(대형주)**로 이미 확정돼 이 리스크는 크게 완화. 확장 시 주의.
- **생존편향**: 생존종목만 백테스트 시 연수익 최대 +4.94%p 과대평가. → 백테스트 유니버스를 point-in-time으로 구성.
- **Look-ahead 편향**: 일봉 스윙이므로 관측일 종가 이후 데이터 누출 금지. `SentimentArticle.published_at`이 tz-aware 강제인 점이 좋음 → 세션 마감(ET 16:00) 이전 published_at만 귀속. ApeWisdom 24h 집계는 **경계 시점 정의** 명확화 필요.
- **소셜 데이터 노이즈**: 대부분 종목·날짜는 무시그널. relevance 가중 + 최소 기사수 임계 필요(`no_relevant_articles`/`no_articles` 처리 이미 있음).
- **레짐 의존성**: 한 기간 IC가 좋아도 지속 안 될 수 있음. → 섀도 기간 롤링 재평가.

---

## 5. 기존 도구·데이터셋 (무료 우선)

- **ApeWisdom API** — Reddit 멘션 집계, 무인증. https://apewisdom.io/api/
- **Arctic Shift** — Pushshift 후속, 2005~2026 히스토리, 서브레딧 단위 검색. 대량 백필용.
- **PullPush.io** — Pushshift 스키마 호환, ~1,000 req/hour, 간헐 장애.
- **Academic Torrents (u/Watchful1)** — 3.97TB, 4만 서브레딧 2005~2025 덤프, 월 갱신.
- **Quiver Quantitative** `quiverquant` PyPI — 유료지만 멘션+감정 히스토리 백필 최적.
- **데이터셋**: **FinancialPhraseBank** (Malo et al. 2014, 4,846문장) — FinBERT 파인튜닝/검증 표준 라벨셋. **WSB Reddit Posts Dataset** (Kaggle).
- **모델**: **FinBERT** (HuggingFace, 로컬 추론 가능).
- 참고: Pushshift는 2023.5 접근 차단, 무료 완전 대체 도구는 없음.

---

## 종합 권고 (모듈 확장 로드맵)

1. **멀티 Provider 구현**: `SentimentProvider`를 소스별로 — `AlphaVantageProvider`(뉴스), `ApeWisdomProvider`(멘션→buzz), `StockTwitsProvider`(유저 태그). `source` 필드로 구분해 rank IC 소스별 비교.
2. **buzz 팩터 신설**: 감정 score와 별개로 멘션 z-score를 `SentimentObservation`에 추가, [1,5,20]일 IC 각각 측정.
3. **텍스트→score는 FinBERT 로컬 추론** + FinancialPhraseBank로 검증.
4. **look-ahead 가드**: ApeWisdom 24h 집계의 세션 귀속 경계 명시(ET 16:00 컷), tz-aware 검증 활용.
5. **S&P500 유니버스 유지**로 소형주·조작 리스크 최소화. 섀도 60거래일 IC가 안정적으로 양(+)일 때만 실팩터 승격.
> ⚠️ 감정점수 반영(가중치 결정)은 README §4 승인 필수 항목. 60거래일 전방검증 후 사용자 승인으로 확정.

---

## 출처

- [ApeWisdom API](https://apewisdom.io/api/) · [quiverquant PyPI](https://pypi.org/project/quiverquant/0.1.32/)
- [Adanos - Stock Sentiment APIs 2026](https://adanos.org/insights/blog/best-stock-sentiment-apis-2026/) · [Reddit Sentiment Trackers](https://adanos.org/insights/blog/best-reddit-stock-sentiment-trackers-2026/)
- [Marketaux](https://freeapihub.com/apis/marketaux) · [Alpha Vantage Guide](https://alphalog.ai/blog/alphavantage-api-complete-guide) · [StockTwits Data API](https://articles.dailytickers.com/series/finance-apis/part3-sentiment/)
- [X API Cost 2026](https://twitterapi.io/blog/x-api-cost-breakdown-2026)
- [Pushshift Alternatives 2026](https://www.redditapis.com/blogs/best-pushshift-alternatives-2026)
- FinBERT: [W&B FinBERT on Headlines](https://wandb.ai/ivangoncharov/FinBERT_Sentiment_Analysis_Project/reports/Financial-Sentiment-Analysis-on-Stock-Market-Headlines-With-FinBERT-Hugging-Face--VmlldzoxMDQ4NjM0) · [FinBERT fine-tune](https://github.com/LikithMeruvu/FinBert-Finetuning-for-Stock-Sentiment)
- 실증: [Place Your Bets? (SSRN 3806065)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3806065) · [Intensity Bursts (SSRN 5030887)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5030887) · [Meme Stock (SSRN 4947010)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4947010) · [Abnormal Trading Volume (SSRN 2812010)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2812010)
- 함정: [Pump&Dump Detection (arXiv 2301.11403)](https://arxiv.org/abs/2301.11403)
- 데이터셋: [FinancialPhraseBank (Kaggle)](https://www.kaggle.com/datasets/ankurzing/sentiment-analysis-for-financial-news) · [WSB Reddit Posts (Kaggle)](https://www.kaggle.com/datasets/shivd24coder/wallstreetbets-reddit-posts-dataset)
