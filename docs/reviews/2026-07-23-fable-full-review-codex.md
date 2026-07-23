# trade_flow 전체 파이프라인 교차검증 리뷰 (Codex)

- 리뷰일: 2026-07-23
- 대상: `main` @ `205b201`
- 기준: `docs/superpowers/specs/2026-07-21-trade-flow-tech-spec.md` v1.3
- 방법: 최근 커밋 이력, 실행 스크립트·도메인·KIS 어댑터·SQLite 저장소·테스트 직접 검토, 전체 단위 테스트와 Ruff 재실행, 기존 백테스트 및 리뷰 산출물 교차검증
- 검증 결과: `.venv/bin/python -m pytest -q` **96 passed**, `.venv/bin/ruff check .` **통과**
- 변경 범위: 이 리뷰 문서만 생성했으며 코드는 수정하지 않았다.

## 1. 요약

### 종합 판정: **실계좌 운용 불가 (NO-GO), 모의투자도 복구성 보완 전 제한적 사용**

전략 계산, 공통 리스크 정책, 매도 후 계좌 재조회와 매수 재계획, no-trade band 우선순위, 기본 BUY_BLOCK 레짐은 단위 수준에서 비교적 잘 연결돼 있다. 그러나 현재 `daily_run.py --execute`는 Tech Spec §3.1의 완성된 일일 오케스트레이터가 아니라 여러 컴포넌트를 직접 이어 붙인 실행 스크립트다. 프로세스 락, 정확한 거래일/신호일 분리, 실행 허용 지연, 브로커 원장 기반 체결 조정, 프로세스 간 주문 복구, 실행 종료 상태, 스냅샷·체결 저장, 외부 알림/dead-man이 닫힌 루프를 이루지 않는다.

가장 중요한 결론은 다음과 같다.

1. **실전 자격증명 우회 위험이 있다.** KIS 환경(`mock`/`real`)과 런타임 환경(`paper`/`production`)을 대조하지 않는다. `KIS_ENV=real`, `runtime.environment=paper`, `dry_run=false`, `--execute` 조합이면 production에서만 적용되는 `allow_real_orders`, `release_approved`, account allowlist 검사를 건너뛰고 실주문 어댑터를 호출할 수 있다.
2. **계좌 상태가 주문 가능한 실제 상태를 나타내지 않는다.** 보유 종목은 NASDAQ 잔고 한 번만 조회하고, 현금은 실제 USD 주문가능금액이 아니라 `총자산(KRW)/환율 - 조회된 보유평가액`으로 추정한다. NYSE/AMEX 보유 누락, 원화자산의 현금 오인, 자동환전 가정으로 과매수·잘못된 청산 계획이 가능하다.
3. **주간 추천은 자동매매 입력이 아니다.** `recommend.py`는 화면 출력만 하고 선정 결과를 저장하지 않는다. `daily_run.py`는 매일 전체 신호를 다시 계산한다. 따라서 “주간 추천 → 리밸런스”라는 단계 간 상태 전달은 없으며, 실제 구현은 기본값상 매일 top-5를 재선정·재조정한다.
4. **주문/체결 복구는 브로커 원장 수준이 아니다.** KIS intent 매핑은 프로세스 메모리에만 있고, 미체결 목록에서 사라진 주문을 체결내역 확인 없이 전량 체결로 간주한다. 부분체결 후 취소는 체결수량을 잃으며 fills 테이블에도 기록되지 않는다.
5. **수익성은 현재 기본 설정에서 매우 취약하다.** grade-C 전체기간 BUY_BLOCK 결과는 편도 5/15/30bp에서 CAGR `33.0% / 17.8% / -2.2%`, turnover 약 `1113~1142×`다. KIS 공식 일반 온라인 수수료 25bp/side만으로도 15bp 가정보다 불리하며, 스프레드·슬리피지·체결 지연을 더하면 기본 시나리오는 30bp 이상이 된다. 생존편향까지 감안하면 현재 코드·기본 설정의 실계좌 기대수익은 기본 시나리오에서 음수로 보는 것이 타당하다.

좋은 부분도 분명하다.

- `signal()`과 `apply_risk_policy()`를 백테스트와 라이브 재조정이 공유한다.
- 매도 계획을 먼저 실행한 후 계좌를 재조회하고 실제 현금으로 매수를 다시 계획한다.
- 레짐 데이터 부재는 BUY_BLOCK으로 fail-closed되고, 일일손실 한도는 보호 매도를 남긴 채 매수만 막는다.
- 결정적 intent ID와 DB 선예약은 동일 프로세스의 정상 경로 및 일부 재실행에서 중복 주문 가능성을 낮춘다.
- 기본 `selection_hysteresis=0`, `rebalance_band=0`, `regime_exit_vix_threshold=30`은 연구 파라미터를 임의로 활성화하지 않는다.

다만 이 장점들은 아래 Critical/High 이슈를 상쇄하지 못한다. 현 상태는 “전략 연구와 dry-run용”으로 보는 것이 정확하며, README와 `IMPLEMENTATION_NOTES.md`의 “전체 시스템 조립 중”이라는 진술이 실제 상태에 더 가깝다.

## 2. 흐름 검증 결과 및 발견 이슈

### 2.1 단계별 연결성

| 단계 | 구현 상태 | 검증 결과 |
|---|---|---|
| 일일 데이터 수집 | 부분 구현 | yfinance 증분 upsert는 멱등적이다. 하지만 수집 실패를 삼키고 기존 DB로 계속하며, 공식 거래소 캘린더가 없다. 실패 종목을 유니버스에서 제거해 유효한 스냅샷을 만드는 방식은 라이브 fail-closed 요구와 다르다. |
| `daily_return` | 부분 구현 | 가격 일수익률 테이블이 아니라 별도 JSON의 이전 NAV 대비 수익률이다. 손상·읽기 실패·최초 실행은 0으로 fail-open하며, 신호일 `end` 키로 주문 전에 기록한다. |
| 주간 추천 | 표시 전용 | 동일 전략 점수를 사용하지만 콘솔 출력만 한다. 실행 주기, 추천 manifest, 승인/고정된 selection ID, 리밸런서 입력 연결이 없다. |
| 전략·레짐·리스크 | 대체로 연결 | 공통 함수 사용, 손절/레짐/일손실 반영은 양호하다. 단 `--policy equity_cap`을 paper/production에서 별도 승인 없이 선택할 수 있고, 레짐 streak의 거래 캘린더가 공식 캘린더가 아니다. |
| 주문 계획 | 부분 구현 | 정수 수량, 현금 buffer, fee 추정, 매도 우선, band 우선순위는 구현됐다. 그러나 계좌 현금·보유와 quote가 부정확하면 계획 전체가 잘못된다. |
| KIS 제출·취소·상태 | 실험 수준 | 정규장 주문은 연결됐지만 bid/ask 대신 last, 고정 tick, 체결내역 미조회, process-local intent 매핑이다. daytime API는 하위 client에만 있고 실제 broker 경로에서는 사용하지 않는다. |
| 재실행·미체결 정합성 | 불충분 | 시작 시 미체결 전량 취소는 있으나 로컬 intent와 연결하지 않고 수동 주문까지 취소한다. 프로세스 간 broker 대조와 부분체결 복구가 없다. |
| 킬스위치·런타임 설정 | 결함 있음 | kill switch와 permit은 있으나 credential/runtime 환경 불일치가 핵심 우회 경로다. account reconciliation은 실제 검증 없이 `True`로 설정한다. |
| 감사·알림 | 미완성 | run 시작만 저장하고 finish하지 않는다. 실제 fill/snapshot/data/config/universe hash가 없고, 알림은 로컬 stdout/file뿐이며 전송 실패 반환값을 무시한다. |

### 2.2 Critical

#### C-1. 실전 KIS 자격증명이 `paper` 안전 게이트를 통해 주문될 수 있다

**근거**

- 브로커는 환경변수의 `KIS_ENV`로 `mock` 또는 `real` client를 만든다: `scripts/daily_run.py:107-109`, `src/trade_flow/broker/kis.py:349-356`.
- SafetyContext의 환경은 별도 `runtime.toml`에서 읽는다: `scripts/daily_run.py:252-273`.
- real credential과 runtime의 일치 검사가 없다.
- `allow_real_orders`, `release_approved`, allowlist는 `ExecutionEnvironment.PRODUCTION`일 때만 검사한다: `src/trade_flow/safety/gate.py:99-105`.
- 현재 커밋된 `configs/runtime.toml`은 `environment="paper"`, `dry_run=false`다.

**영향**

`KIS_ENV=real` 상태에서 `python scripts/daily_run.py --execute`를 실행하면 runtime이 paper인 한 production 3중 게이트가 적용되지 않는다. kill switch, stale data 등의 다른 조건이 통과하면 실제 KIS 주문 endpoint가 호출될 수 있다. 이는 Spec의 “실계좌는 명시적으로 활성화” 불변식을 직접 위반한다.

**필수 조치**

- broker가 노출하는 credential environment와 runtime environment를 강제 매핑한다(`mock ↔ paper`, `real ↔ production`). 불일치는 어떤 side도 주문하지 않고 치명 오류로 종료한다.
- real credential이면 runtime label과 무관하게 production 3중 게이트를 강제하는 이중 방어를 둔다.
- 이 조합을 실제 `daily_run --execute` 진입점 통합 테스트로 고정한다.

#### C-2. 계좌 스냅샷이 전체 보유와 실제 주문가능 USD를 나타내지 않는다

**근거**

- 보유 조회는 `inquire_balance_raw(exchange="NASDAQ")` 한 번뿐이다: `src/trade_flow/broker/kis_broker.py:111-145`.
- NAV는 총자산 KRW를 USD 환율로 나누고, cash는 그 값에서 조회된 보유 평가액을 뺀 추정치다.
- daily runner는 별도 reconciliation 없이 `account_reconciled=True`를 넣는다: `scripts/daily_run.py:269`.
- Tech Spec은 자동환전을 비목표로 하고 달러 주문가능금액 부족 시 매수를 축소하도록 요구한다.

**영향**

NYSE/AMEX 보유가 빠지면 해당 종목을 미보유로 보고 중복 매수하거나 NAV 차액을 현금으로 오인할 수 있다. 원화 예수금·기타자산이 총자산에 포함되면 실제 주문가능 USD보다 큰 cash로 매수 계획을 세울 수 있다. 반대로 조회 필드 의미가 계좌 유형마다 다르면 정상 보유도 잘못 청산할 수 있다.

**필수 조치**

- 모든 지원 거래소의 보유를 병합하거나 KIS의 전체 해외주식 잔고 계약을 공식 fixture로 확정한다.
- cash는 `주문가능 외화금액` endpoint의 USD 값을 사용하고 통합증거금/자동환전 사용 여부를 명시적 설정과 승인으로 분리한다.
- 전체 보유가 브로커 조회와 일치할 때만 `account_reconciled=True`가 되도록 한다.

### 2.3 High

#### H-1. “주간 추천 → 리밸런스” 상태 전달이 없고 실제로는 일일 top-5 전략이다

`recommend.py`는 같은 `signal()`을 호출해 출력할 뿐 결과를 DB나 manifest에 저장하지 않는다(`scripts/recommend.py:59-91`). `daily_run.py`는 실행할 때마다 최신 snapshot과 현재 보유로 `signal()`을 다시 호출한다(`scripts/daily_run.py:122-127`). 따라서 주간 추천 결과를 일주일 동안 고정하거나 승인된 추천을 주문에 사용하는 계약이 없다.

기본 `selection_hysteresis=0`, `rebalance_band=0`이므로 매일 순위 경계가 바뀔 때 회전한다. 기존 분석에서 거래대금의 97.7%가 선정 로테이션이고 전체기간 turnover가 약 1120×였다는 사실과 정확히 연결된다. 주간 운용을 의도했다면 현재 백테스트와 라이브 실행 주기가 모두 목적과 다르다.

#### H-2. 브로커 주문 상태가 원장이 아니며 부분체결·취소를 정확히 표현하지 못한다

- `find_by_intent()`는 메모리의 `_intent_index`만 조회하므로 새 프로세스에서 기존 주문을 찾지 못한다: `src/trade_flow/broker/kis_broker.py:188-195`.
- `_status()`는 미체결 목록에 주문이 없으면 체결내역(TR_CCNL)을 확인하지 않고 전량 `filled`로 간주한다.
- 취소는 원주문 수량으로 요청하고 즉시 `cancelled, filled_quantity=0, remaining_quantity=원수량`을 반환해 이미 부분체결된 수량을 잃는다.
- `FillRepository`는 구현돼 있지만 live path에서 호출되지 않는다.

주문이 거절·취소·부분체결됐는데 미체결 목록에서 사라진 경우 전량 체결로 오판할 수 있다. 매도 실패 후에도 별도 현금이 있으면 새 종목 매수가 진행돼 의도한 총노출을 초과할 수 있고, 최종 감사 로그는 실제 계좌와 달라진다.

#### H-3. 주문 응답 유실 복구 계약이 KIS HTTP 경로와 연결되지 않는다

executor는 `SubmissionStatusUnknown`만 특별 처리한다(`src/trade_flow/execution/executor.py:49-57`). 그러나 KIS `_post()`의 network timeout/JSON 오류는 이 예외로 변환되지 않고, 주문 endpoint도 rate-limit 응답에 대해 공통 재호출 루프를 사용한다. 새 프로세스의 `find_by_intent()`는 broker 조회가 아니라 메모리 조회이므로 “응답 유실 → broker 원장 대조”가 실제로 성립하지 않는다.

현재 DB 선예약 덕분에 재실행이 무조건 재주문하기보다는 `unknown`으로 멈추는 경향은 안전 측이다. 하지만 정상 복구가 불가능하고 운영자가 broker 주문과 local intent를 수동 연결해야 하므로 Spec의 자동 복구 기준을 충족하지 않는다.

#### H-4. 시작 시 계좌의 모든 미체결을 취소하며 전략 주문인지 확인하지 않는다

`_reconcile_open_orders()`는 세 거래소의 미체결 전부를 순회해 취소한다(`scripts/daily_run.py:191-210`). 주문일, local intent, broker order ID, 전략 버전, 수동 주문 여부를 구분하지 않는다. 같은 계좌에서 사람이 낸 주문이나 다른 전략의 주문까지 취소할 수 있다. 또한 취소 API 성공 응답 뒤 상태 재조회 없이 reconciled로 간주한다.

#### H-5. 거래일·신호일·신선도·실행창의 의미가 Spec과 다르다

- 캘린더는 공식 미국 거래소 캘린더가 아니라 DB 가격일자의 합집합이다.
- 신선도는 Asia/Seoul의 `date.today()`와 latest bar 날짜의 단순 달력일 차이가 4 이하인지로 판정한다: `scripts/daily_run.py:100-105`.
- latest data date `end`를 signal date와 trading date 양쪽에 저장하고 intent ID에도 사용한다: `scripts/daily_run.py:241-250, 278-281`.
- 실행창은 평일 09:30~16:00 ET이며, 휴일·조기폐장·기본 09:31·15분 허용 지연을 반영하지 않는다.

월요일에 금요일 데이터는 허용되는 반면, 장기 휴장·부분 수집·당일 미완료 봉 여부는 정확히 판별하지 못한다. 휴장일에도 미체결 취소와 run 시작까지 진행한 뒤 KIS 거부에 의존한다. trading date가 D가 아니라 signal date가 되어 intent 멱등성·감사 의미도 틀어진다.

#### H-6. 데이터 품질 오류를 가진 종목을 제거하고 거래를 계속한다

`_build_clean_snapshot()`은 불량 OHLC, 최근 결측, interior gap이 있는 종목을 `surviving`에서 제외한 뒤 유효해질 때까지 재시도한다(`scripts/backtest.py:63-135`). 이는 연구용으로는 유용할 수 있지만 live path도 그대로 재사용한다. Spec의 “데이터가 누락되거나 오래되면 신규 주문과 축소 매도를 모두 중단”과 다르며, 장애 종목이 순위에서 빠져 대체 종목 매수를 유발한다. `--refresh-data` 실패도 예외를 삼키고 기존 DB로 진행하므로 이 동작과 결합된다.

#### H-7. 실행 감사 상태가 시작에서 끝나지 않는다

live path는 `RunRepository.start()`만 호출하고 `finish()`를 호출하지 않는다. environment는 runtime과 무관하게 `paper`, data/config/universe hash는 모두 `live`, signal/trading date는 동일 값이다. `SnapshotRepository`와 `FillRepository`도 호출하지 않는다. 그 결과 모든 실행이 DB에서 `started`로 남고 completed/blocked/failed/needs_review, 실제 입력 해시, 시작·종료 계좌, 체결·수수료를 재구성할 수 없다.

#### H-8. 실제 호가·호가단위 대신 last와 고정 1센트를 사용한다

KIS quote adapter는 bid/ask를 제공하지 않는 현재가 endpoint의 `last`를 양쪽 호가로 복제한다(`src/trade_flow/broker/kis_broker.py:148-155`). planner는 여기에 ±0.30%와 모든 종목 공통 `$0.01` tick을 적용한다. quote age 검증도 없다. 이는 Spec의 “주문 직전 유효한 최우선 호가” 및 거래소 호가단위 요구를 충족하지 않으며, 체결률·슬리피지·취소량을 백테스트보다 악화시킨다.

### 2.4 Medium

#### M-1. NAV history가 손상·최초 실행에서 일일손실 한도를 fail-open한다

`NavHistory._load()`는 읽기/JSON 오류를 빈 이력으로 바꾸고, prior가 없으면 return 0을 반환한다. 주문 전에 current NAV를 signal date 키로 기록하며 원자적 쓰기·파일 락도 없다. 파일 삭제·손상·동시 실행 시 -3% 한도가 비활성화될 수 있다. 브로커의 전 거래일 확정 NAV 또는 DB snapshot을 원장으로 써야 한다.

#### M-2. 선택 가능한 `equity_cap`이 승인 관문과 연결되지 않는다

CLI에서 `--policy equity_cap`을 선택할 수 있고 safety gate는 정책 승인 여부를 보지 않는다. Tech Spec은 노출 축소 정책을 실험 정책으로 두고 승인 전 paper/production 주문에 적용하지 말라고 한다. 기본값은 BUY_BLOCK이지만 오입력 방어가 없다.

#### M-3. daytime(미국 주간거래) 지원은 실제 주문 경로에 배선되지 않았다

KIS client는 `session="daytime"` endpoint를 지원하지만 `KisBroker.submit/cancel`은 session을 받거나 전달하지 않는다. 실행창도 정규장만 허용한다. 따라서 현재 실전 수익 추정에는 주간거래 체결을 포함시키면 안 된다. 향후 배선한다면 정규장보다 넓은 spread·얕은 depth·세션별 취소/상태 TR을 별도로 검증해야 한다.

#### M-4. 알림은 로컬 로그이며 실패가 실행 상태에 반영되지 않는다

현재 notifier는 stdout과 파일 append뿐이다. Telegram 구현과 외부 dead-man이 없고 `DeliveryResult.delivered=False`도 caller가 무시한다. 일반 예외, `ExecutionUncertain`, DB 오류는 `SafetyBlocked`/`KisApiError` catch 밖이라 실행 실패 알림도 보장되지 않는다.

#### M-5. 프로세스 락·stale lock 복구·동시 실행 테스트가 없다

intent unique 제약은 최종 방어 일부일 뿐 프로세스 락을 대체하지 않는다. 두 실행이 동시에 시작하면 서로의 미체결을 취소하거나 한 실행이 다른 실행의 local intent를 `unknown`으로 바꿀 수 있다. Spec §3.1과 §4의 락·stale lock 장애주입 기준은 미구현이다.

#### M-6. 운영 파일 권한이 Spec보다 느슨하다

검토 시점의 `data/kis_token.json`과 `data/trade_flow.db`는 `-rw-r--r--`였다. 코드도 token/DB/cache 생성 후 `0600`을 강제하지 않는다. 토큰 캐시·SQLite·백업을 실행 사용자만 읽고 쓰게 하라는 비기능 요구사항에 어긋난다.

### 2.5 엣지케이스 판정

| 엣지케이스 | 현재 동작 | 판정 |
|---|---|---|
| 미국 휴장일 | 평일이면 execution window 통과 가능, stale 4일 이내면 fresh, KIS 주문 거부에 의존 | 불충분 |
| 조기폐장 | 16:00 ET까지 열렸다고 판단 | 위험 |
| 부분체결 후 timeout | 미체결 수량은 잠시 보지만 취소 결과가 부분체결을 잃고 fills 미저장 | 실패 |
| 주문 응답 유실 | 실제 KIS 예외가 recovery 예외로 변환되지 않으며 process 간 broker search 없음 | 실패 |
| 중복 실행 | 프로세스 락 없음; intent unique는 일부 중복 제출만 억제 | 불충분 |
| 데이터 공급자 일부 실패 | 실패 종목 제거 후 대체 종목 거래 가능 | Spec 위반 |
| 레짐 데이터 누락 | missing state로 BUY_BLOCK | 양호 |
| 레짐 해제/재진입 | 기본 30/3 유지, look-ahead 없음; 단 캘린더가 DB context 날짜 기반 | 조건부 양호 |
| 일일 -3% 손실 | prior NAV JSON이 정상일 때 매수 차단·매도 허용 | 조건부 양호 |
| 매도 미체결 | timeout 후 취소 시도, 취소 불확실이면 중단하는 core 계약은 양호; KIS 상태 구현이 이를 약화 | 불충분 |
| 계좌 내 수동 주문 | 다음 실행이 모두 취소 | 위험 |
| NYSE/AMEX 보유 | 계좌 snapshot에서 누락 가능 | 치명적 |
| 알림 파일 쓰기 실패 | DeliveryResult 실패를 무시하고 성공 반환 가능 | 실패 |

## 3. 수익 추정

### 3.1 근거 데이터와 한계

가장 넓은 산출물인 `backtests/gradeC_full_evaluate.json`의 BUY_BLOCK 전체기간 결과는 다음과 같다.

| 편도 비용 가정 | CAGR | MDD | Sharpe | turnover | 거래수 |
|---:|---:|---:|---:|---:|---:|
| 5bp | +33.0% | -43.3% | 0.64 | 1112.9× | 13,538 |
| 15bp | +17.8% | -55.0% | 0.45 | 1121.4× | 13,512 |
| 30bp | **-2.2%** | -78.7% | 0.16 | 1142.1× | 13,498 |

최신 2년 holdout의 30bp CAGR은 +14.8%지만 이를 실전 기대값으로 쓰면 안 된다. 유니버스가 2026년 현재 S&P 500 구성 종목을 과거 전체에 적용한 grade-C이고, holdout에도 2026년에 살아남은 종목 정보가 들어가므로 진정한 out-of-sample PIT holdout이 아니다. 2023~2026 강세 구간 의존도도 크고 2021-07~2022-07 walk-forward는 비용 15bp에서도 CAGR -35.3%였다.

turnover 약 1121×는 약 10.5년 동안 누적 체결금액/평균 NAV다. 단순화하면 연간 약 106×이며, 편도 비용 1bp 증가는 연 NAV의 약 1.06%를 직접 소모한다. 실제 결과에서도 5→15bp가 CAGR 15.3%p, 15→30bp가 20.0%p를 낮췄다. 이 전략에서는 수수료 5~10bp 차이가 일반적인 오차가 아니라 수익/손실을 바꾸는 핵심 변수다.

### 3.2 실전 비용 항목

| 항목 | 현재 백테스트/코드 | 실전 반영 가정 |
|---|---|---|
| 증권사 수수료 | 백테스트 총비용 5/15/30bp에 포괄적으로 포함 | KIS 공식 일반 온라인 미국주식 수수료는 거래대금의 **0.25%(25bp)/side**다. 계좌별 이벤트 우대가 있다면 실제 적용률을 API/명세서로 확인해야 한다. |
| 미국 제세금 | 별도 세분화 없음 | KIS 안내 기준 매도 SEC fee 0.00206%=0.206bp로 수수료 대비 작지만 매도마다 추가된다. |
| bid/ask·시장충격 | 익일 시가 + 고정 편도 비용 | 정규장 대형주는 2~5bp, 체결 지연/순위 변경·limit miss까지 5~15bp를 기본 범위로 둔다. current code가 last를 quote로 써 불확실성이 더 크다. |
| daytime 유동성 | 미모델링, live 미배선 | 배선 시 정규장보다 넓은 spread를 전제로 10~30bp 이상의 별도 민감도가 필요하다. 현재 기대수익에는 daytime 체결을 포함하지 않는다. |
| 환전 | 미모델링 | USD를 최초 1회 조달하고 유지하면 연 환전 drag는 작다. 원화 통합증거금/빈번한 자동환전이면 환전 스프레드가 반복돼 연 0.5~2%p 이상 추가될 수 있다. 현재 cash 모델은 이를 통제하지 못한다. |
| 미체결·부분체결·지연 | 미모델링 | 기회비용 연 1~5%p 범위를 둔다. 현재 상태 오판·취소 결함이 있는 동안에는 상단도 보장할 수 없다. |
| 한국 양도소득세 | 미포함 | 해외주식 연간 순양도차익에서 기본공제 250만원을 뺀 과세표준에 지방세 포함 22%. 잦은 실현으로 과세가 매년 앞당겨져 복리효과가 감소한다. |

공식 참고: [한국투자증권 시장별 매매수수료](https://securities.koreainvestment.com/main/bond/research/_static/TF03ca050000.jsp), [한국투자증권 미국시장 안내](https://securities.koreainvestment.com/main/bond/research/_static/TF03ce010000.jsp), [한국투자증권 해외주식 양도소득세 안내](https://securities.koreainvestment.com/main/bond/research/_static/TF03ca030100.jsp). 수수료 우대·환전 우대는 계좌별로 달라질 수 있으므로 주문 전 실제 계좌 조건을 별도 확인해야 한다.

### 3.3 시나리오별 기대수익

아래 범위는 **현재 daily top-5, hysteresis 0, band 0** 동작을 전제로 한다. 아직 실계좌 운용 가능한 구현이 아니므로 투자 예측이 아니라 출시 판단용 보수적 추정이다. “백테스트 환산”은 비용 민감도 곡선의 보간/외삽이고, “실전 세전”은 grade-C 생존편향·데이터/체결 괴리·운영 기회비용을 추가 차감한 범위다.

| 시나리오 | 편도 all-in 비용 | 전제 | 백테스트 환산 CAGR | 실전 세전 기대 CAGR | 세후 방향성 |
|---|---:|---|---:|---:|---|
| 낙관 | 10~15bp | 계좌별 저율 수수료가 실제 적용되고 정규장 대형주만 거래, USD 사전 보유, 복구 결함 수정 | 약 +18~25% | **+8~15%** | 과세이익이 공제 초과 시 대략 +6~12% 범위. 자본 규모와 실현손익에 따라 달라짐 |
| 기본 | 25~30bp | KIS 일반 수수료 25bp + SEC fee + 낮은 한 자릿수 bp 체결비용, 정규장 | 약 -2~+4% | **-10~-1%** | 손실이면 양도세 없음. 작은 이익도 운영/모델 오차에 쉽게 소멸 |
| 보수 | 35~45bp | 일반 수수료 + 넓은 spread/limit miss/부분체결, 일부 환전·지연 비용 또는 daytime 유동성 | 약 -22~-9% | **-25~-12%** | 세금보다 원금 손실·MDD가 지배 |

낙관 시나리오도 grade-B PIT 데이터, 실제 수수료 확인, 최소 80거래일 paper 검증(grade-C 보완 포함), 실체결 TCA가 전제다. 현재 코드 그대로라면 C-1/C-2/H-2 때문에 기대수익 범위보다 운영 손실의 꼬리가 더 크므로 **기본 또는 보수 시나리오를 사용해야 한다**.

주간 리밸런싱이 진짜 목표라면 위 표를 그대로 사용하면 안 된다. 주간 selection을 고정하면 turnover와 신호 타이밍이 동시에 바뀐다. 기존 hysteresis top-10 연구는 turnover를 1124×→693×로 약 38% 줄였지만 grade-C에서 CAGR이 비단조로 움직였고, 이는 주간 전략 검증이 아니다. 주간 전용 백테스트를 별도로 실행하기 전에는 “주간이라 비용이 1/5”이라고 단순 환산할 수 없다.

### 3.4 세금 예시

세전 연간 실현 순이익을 `G`원이라 하면 대략적인 양도소득세는 `max(0, G - 2,500,000) × 22%`다(다른 과세대상 주식 손익과 합산 가능성은 개인별 확인 필요). 예를 들어 운용자금 1억원에서 세전 실현수익 10%인 1,000만원이면 단순 세액은 약 165만원, 세후 수익은 약 835만원이다. 백테스트는 세금을 차감하지 않으므로 높은 회전율 전략의 세후 복리수익을 과대평가한다.

## 4. 권고사항

### P0 — 어떤 실주문보다 먼저

1. **credential/runtime 환경 결합을 강제한다.** real credential은 runtime production + allow flag + release approval + allowlist가 모두 없으면 broker 생성 또는 주문 permit 단계에서 차단한다. 조합 행렬 통합 테스트를 추가한다.
2. **계좌 원장을 다시 정의한다.** 전체 거래소 보유, 실제 USD 주문가능금액, 결제예정금액, 미체결 reserved cash를 공식 KIS fixture로 검증하고 그 전에는 `account_reconciled=False`로 둔다.
3. **실계좌 KILL_SWITCH를 즉시 활성화한 상태로 유지한다.** 위 두 Critical과 주문 원장 복구가 해결되고 모의 장애주입이 통과할 때까지 real credential 사용을 금지한다.

### P1 — 모의투자 승인 전

1. KIS 체결내역(TR_CCNL)을 구현해 `submitted/partially_filled/filled/cancelled/rejected`를 broker 원장으로 조정하고 fills를 append-only 저장한다.
2. intent↔broker order 보조키를 DB에 영속화하고 프로세스 재시작 후 주문 응답 유실을 조회로 복구한다. order POST network timeout은 `SubmissionStatusUnknown`으로 변환하되 자동 재POST하지 않는다.
3. 미체결 취소는 local strategy order에만 한정하고 취소 후 terminal 상태를 재조회한다. 수동/다른 전략 주문은 `needs_review`로 차단한다.
4. 공식 NYSE 캘린더로 D와 signal date를 분리하고 09:31 ET + 15분, 휴장/조기폐장, timezone을 구현한다. intent ID에는 실제 D를 사용한다.
5. live data quality는 종목 drop-and-continue를 금지한다. 예상 유니버스의 최근 결측/불량은 전체 주문을 차단하고, 상장폐지/심볼 변경만 승인된 point-in-time mapping으로 처리한다.
6. 프로세스 락과 stale lock 복구를 넣고 동시 실행·강제 종료 장애주입 테스트를 추가한다.

### P2 — 닫힌 운영 루프

1. 모든 경로에서 run을 `completed/blocked/failed/needs_review`로 종료하고 실제 data/config/universe hash, 시작/매도후/종료 snapshot, fills, notification status를 저장한다.
2. NAV history JSON을 제거하고 broker/DB의 전 거래일 확정 snapshot으로 일일수익을 계산한다. history 부재·손상은 buy block으로 fail-closed한다.
3. Telegram 등 외부 notifier와 별도 dead-man을 연결하고 notifier 실패를 non-zero exit 및 run 상태에 반영한다.
4. token, SQLite, exchange map, nav history, backup을 원자적으로 쓰고 `0600` 권한을 강제한다. DB integrity check와 일별 backup/복구 훈련을 추가한다.
5. 실제 best bid/ask, quote timestamp/age, 종목별 tick size를 사용하고 quote 누락은 해당 종목 drift가 아니라 계획 전체 재평가/차단 기준으로 명세한다.

### P3 — 전략·수익성 재승인

1. **운용 주기를 먼저 결정한다.** 주간 전략이면 추천 selection을 versioned manifest로 저장하고 리밸런서는 그 manifest만 소비하게 한다. 일일 전략이면 “주간 추천” 표현을 보고서 기능으로만 명확히 제한한다.
2. grade-B point-in-time 유니버스로 동일 기간을 재평가하고 SPY benchmark 누락을 보완한다. 현 JSON은 cash benchmark만 포함해 §7.1 승인 기준을 완전히 검증하지 못한다.
3. 실제 계좌 수수료율과 regular-session 체결 TCA로 5/10/15/25/30/40bp 격자를 재실행한다. turnover, fill ratio, cancel ratio, implementation shortfall을 함께 보고한다.
4. weekly cadence, selection hysteresis, no-trade band를 서로 분리해 walk-forward/holdout으로 검증한다. grade-C에서 고른 파라미터는 production에 활성화하지 않는다.
5. BUY_BLOCK을 유일한 승인 기본값으로 고정하고 equity_cap/daytime은 별도 feature flag·승인·실험 계좌로 격리한다.

### 출시 재개 최소 조건

- P0 전부 해결
- 주문 응답 유실, 부분체결, 취소 실패, 프로세스 강제종료, 동시 실행, 휴장/조기폐장 장애주입 통과
- 모의투자 20거래일 + grade-C 보완 60거래일 동안 치명 오류 0건, 설명 불가 포지션 차이 0건
- 실체결 all-in 비용이 사전 정한 손익분기 비용보다 낮다는 TCA 증거
- grade-B 기반 30bp 시나리오에서 장기 기대수익이 현금보다 높고 holdout MDD가 SPY보다 작음
- 이후에만 production dry-run 5거래일과 별도 승인된 소액 20거래일 진행

현재는 이 조건을 충족하지 않는다. 따라서 다음 실행 단계는 실주문이 아니라 **P0/P1 수정 → 장애주입 가능한 KIS mock/paper 통합 테스트 → grade-B·주간 cadence 재백테스트** 순서가 적절하다.
