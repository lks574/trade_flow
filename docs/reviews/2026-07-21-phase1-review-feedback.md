# Phase 1 구현 리뷰 피드백

날짜: 2026-07-21
대상: 커밋 30055f0..c10d5bc (Phase 1~6 구현)
기준 문서: `docs/superpowers/specs/2026-07-21-trade-flow-tech-spec.md`
리뷰 방법: 전 테스트·린트 실행 + 코어 직접 검토 + 3축 병렬 대조(주문 실행 / 리스크·안전 / 스펙 커버리지)

## 총평

구현 품질 높음. 테스트 전부 통과, ruff 클린. 구현된 로직은 스펙과 정확히 일치하고,
모든 실패 경로가 중복 주문·과지출 대신 중단(`ExecutionUncertain`/`SafetyBlocked`) 쪽으로
설계됨. 단, **라이브러리는 완성이나 시스템은 미조립** 상태다. 아래 순서로 보완 요청.

## 검증 통과 항목 (수정 불필요)

| 영역 | 확인 내용 |
|---|---|
| 백테스터 | 종가 신호 → 익일 시가 체결, look-ahead 없음, 매도 우선, 배당 이중 반영 없음, 손절 "신호일 종가 판정 → 익일 집행" (`backtest/engine.py`) |
| 전략 | SMA200 적격, percentile 모멘텀, 동점 처리(모멘텀→거래대금→심볼), 슬리브 상한 88/25/10/5%, 설정값 §0.2 전부 일치 (`strategy/signal.py`, `configs/strategy.toml`) |
| 레짐 | 진입·해제(3거래일 연속 거짓) 정확, 데이터 무효 시 fail-safe 매수금지 (`risk/regime.py:34-85`) |
| 주문 멱등성 | 의도 ID §0.1 형식·결정적, **submit 전 DB 저장** (`execution/executor.py:37`), 타임아웃 시 재주문 없이 브로커 조회 (`executor.py:51-52`), 과매도·공매도 불가 |
| 감정 격리 | 전략·주문 경로에서 감정점수 참조 0건, 결측을 0점으로 저장하지 않음 (`sentiment/model.py:38-70`) |
| 안전 게이트 | production = allow_real_orders + release_approved + allowlist 3중 확인 (`safety/gate.py:81-86`) |

## 수정 요청 (중요도 순)

### P1. Phase 1 승인 블로커 — 실데이터 부재

- `configs/universe_main.toml`이 빈 등급 C bootstrap. 실제 10년 백테스트가 실행된 적 없음.
- 필요 작업:
  1. `MarketDataProvider` 계약 선언(스펙 §6.2 — 현재 Protocol 자체가 없음) + 실데이터
     어댑터 1개 (yfinance 등; split-adjusted OHLC + cash_dividend canonical 변환)
  2. 미국 시장 캘린더 도입 (`expected_sessions` 수동 전달 제거, 사용 라이브러리·버전을
     manifest에 기록 — 스펙 §10)
  3. 유니버스 등급 B 근사 구성 (공개 편입·제외 이력, 출처·누락 기록)
  4. §7.1 승인 기준 실제 평가 실행: holdout MDD < SPY, 30bp 최악 비용에서 현금 초과
     수익, 인접 파라미터 강건성, 이벤트 스터디. 결과·해시를 manifest로 보존
- `validation/`의 리포트 코드는 이미 준비되어 있으므로 데이터 연결이 전부다.

### P2. 일일 실행 오케스트레이터 부재 (Phase 2 착수 시 최우선)

- 스펙 §3.1의 12단계 흐름을 잇는 모듈이 없음. `plan_orders`/`execute_plan`을 호출하는
  코드가 `__init__.py` re-export 외에 0곳. 락 파일, 실행 허용 지연 검사, 휴장일 분기 등
  §3.1 예외 흐름 전부 미구현.
- README가 이 사실을 명시하지 않아 오해 소지 있음 → README/IMPLEMENTATION_NOTES에
  "오케스트레이터 미구현" 명시 요청 (지금 바로).

### P3. `apply_risk_policy` 계약 미구현 — 리스크가 라이브 경로에 닿지 않음

- 손절·레짐·일일손실 로직이 전부 `backtest/engine.py:232-263`에 인라인. 라이브 경로
  `execution/planner.py:40`은 리스크 적용 없이 전략 출력을 직접 소비.
- 스펙 §3.4의 `apply_risk_policy(strategy_result, account, regime, config) -> RiskAdjustedTarget`
  를 별도 모듈로 추출하고, 백테스터와 (향후) 오케스트레이터가 동일 함수를 호출하도록
  변경. "백테스트와 라이브가 같은 코드"라는 핵심 원칙이 리스크 레이어에도 적용돼야 함.

### P4. 매도 체결 후 실제 현금 기반 매수 재계산 미구현

- `rebalance_sequence` 훅(`planner.py:49`)만 있고 2차 패스를 도는 코드 없음. 매수가
  매도 전 현금 안에서만 계산되어 목표 비중 만성 미달 (돈을 잃는 버그는 아님).
- 스펙 §3.1 step 9-10, 불변식 "매도를 먼저 처리한다" 후반부 충족 필요. 오케스트레이터
  구현 시 함께 해결 권장.

### P5. 사소한 수정

1. `db/execution.py:106-112` — `OrderRepository.update`가 `error_code = NULL`로
   덮어씀. `unknown` 이력이 소실됨. 스펙 §5 "상태와 조정 기록을 추가한다" 위반 →
   이력 보존 방식으로 변경.
2. `safety/gate.py:76-88` — 일일손실 발동 + 매수 포함 플랜이면 전체 차단되어 보호
   매도까지 막힘. P3 해결로 상류에서 매수가 제거되면 완화되지만, 게이트가 매수
   의도만 선별 차단하거나 매도-only 재플랜을 허용하는 쪽이 스펙 §3.4와 정합.
3. `risk/regime.py:102-108` — 실험용 EQUITY_CAP 정책이 `current_weights`를 참조하지
   않아 비중 증가(신규 매수)가 가능. 실주문 도달 전 가드 추가.
4. `fills`/`snapshots` 테이블 writer 미구현 (스키마만 존재).
5. 운영 항목(락 파일, DB 백업·무결성 검사, `.env`·토큰·DB 파일 권한 0600, 로그
   보존)은 Phase 2 몫으로 정리된 것 타당 — IMPLEMENTATION_NOTES 유지.

## 진행 제안

1. P1 완료 → Phase 1 승인 평가 (스펙 §7.1) → 사용자 승인
2. Phase 2 착수 시: P2 → P3 → P4 순서로 조립 후 KIS adapter (미결 #1, #2 확인 포함)
3. P5는 P2~P4 작업에 편승

## 스펙 준수 확인 절차 리마인드

- 변경이 수익률·회전율·MDD에 영향 → Phase 1 재검증 표시 (README §3.2)
- 주문 수량·체결·멱등성 영향 → Phase 2 재검증 표시 (README §3.3)
- 사용자 승인 필수 목록(README §4) 항목은 자동 확정 금지
