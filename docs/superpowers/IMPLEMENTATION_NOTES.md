# Trade Flow 구현 특이사항 및 체크사항

이 문서는 구현 중 발견한 제약, 추후 확인할 사항, 사용자 승인이 필요한 결정을 한곳에
누적한다. 완료된 구현의 기준은 `specs/2026-07-21-trade-flow-tech-spec.md`이며, 이 문서는
기준 명세를 대체하지 않는다.

## 상태 표기

- `OPEN`: 구현 또는 사용자 확인이 필요하다.
- `DEFERRED`: 현재 Phase를 막지 않고 이후 처리한다.
- `DECISION`: 백테스트 결과나 사용자 승인이 필요하다.
- `DONE`: 확인 또는 처리가 끝났다.

## 데이터

| 상태 | 항목 | 내용 | 다음 확인 시점 |
|---|---|---|---|
| DEFERRED | 미국 장기 시세 | 사용자가 추가 데이터를 확보할 예정이다. 확보 전까지 외부 실데이터 백테스트는 실행하지 않는다. | Phase 1 통합 실행 전 |
| DEFERRED | 기존 `/TradeFlow/data/us.db` | KIS 원천이 아니라 yfinance `auto_adjust=True`로 수집된 2016-01-04~2024-01-05 NASDAQ-100 현재 구성 데이터다. 개발 참고용으로만 사용한다. | 데이터 import 시 |
| DEFERRED | 유니버스 B | 공개 편입·제외 이력과 출처를 포함한 point-in-time 유니버스가 필요하다. 현재 설정은 빈 등급 C bootstrap이다. | Phase 1 승인 전 |
| OPEN | 필수 시장 입력 | SPY, VIX, WTI, 원본 OHLCV, split-adjusted OHLC, 현금배당이 필요하다. | 데이터 수령 시 |
| DONE | 품질 경계 | 미래 봉, 중복 키, 최근 거래일 결측, OHLC 역전, 음수 거래량·배당을 canonical snapshot에서 검사한다. | 2026-07-21 |

## 전략 및 검증

| 상태 | 항목 | 내용 | 다음 확인 시점 |
|---|---|---|---|
| DECISION | 위험 레짐 정책 | A는 신규 매수 중단, B는 주식 노출 50% 축소다. 동일 조건 백테스트 후 사용자가 최종 승인한다. | Phase 1 결과 검토 |
| DECISION | 감정점수 | 주문 가중치는 0이다. 최소 60거래일 shadow 관찰 후 별도 승인한다. | Phase 2 이후 |
| OPEN | 성공률·기대수익 | 실데이터 holdout 결과 전에는 추정값을 운영 근거로 사용하지 않는다. | Phase 1 결과 검토 |

## 운영 및 출시

| 상태 | 항목 | 내용 | 다음 확인 시점 |
|---|---|---|---|
| OPEN | KIS 해외주식 모의 지원 | 주문·정정·취소·체결조회 TR과 idempotency 대조 필드를 공식 문서와 sandbox에서 확인해야 한다. | Phase 2 착수 시 |
| OPEN | 알림 dead-man 채널 | Telegram 실패 자체를 감지할 외부 채널은 사용자 결정이 필요하다. | Phase 2 운영 준비 |
| OPEN | 실계좌 자본 상한 | dry-run과 모의투자 승인 뒤 사용자가 별도로 정한다. | Phase 3 승인 시 |

## 구현 Phase 기록

### 구현 Phase 1 — 기반과 데이터 계약

- Python 3.12 패키지, Ruff, pytest 개발 기준을 구성했다.
- 전략 설정을 TOML로 분리하고 설정 불변식과 결정적 해시를 구현했다.
- 실행 manifest와 SQLite 초기 스키마를 구현했다.
- canonical `DailyBar`, 데이터 품질 보고서, snapshot 해시를 구현했다.
- 유니버스 A/B/C와 심볼 유효기간, 기간 중첩 검사를 구현했다.
- 검증을 통과한 snapshot만 저장하는 `PriceRepository`를 구현했다.
