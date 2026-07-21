# Phase 1 구현 리뷰 대응

대상 피드백: `2026-07-21-phase1-review-feedback.md`

## 처리 결과

| 항목 | 상태 | 대응 |
|---|---|---|
| P1 실데이터 | DEFERRED | 사용자 데이터 추가 확보 후 adapter·calendar·유니버스 B·실제 승인 평가를 수행한다. `MarketDataProvider`와 `MarketCalendar` Protocol은 먼저 선언했다. |
| P2 일일 오케스트레이터 | PARTIAL | 매도→terminal 확인→계좌 재조회→실제 현금 기반 매수 2-pass `execute_rebalance`를 구현했다. 락·휴장·실행 지연·12단계 전체 조립은 Phase 2 착수 시 구현한다. README에 미구현 상태를 명시했다. |
| P3 공통 리스크 | DONE | `apply_risk_policy`를 추출해 백테스터와 rebalance가 동일하게 사용한다. 손절·레짐·일손실을 공통 적용한다. |
| P4 매도 후 재계산 | DONE | 매도 체결·취소 terminal 확인 후 account snapshot을 다시 조회하고 `rebalance_sequence=1` 매수를 계산한다. |
| P5-1 주문 이력 | DONE | `order_events`에 상태 전이를 append-only로 보존한다. 현재 상태의 error code가 정리돼도 unknown 이력은 남는다. |
| P5-2 보호 매도 | DONE | 일일손실 시 `apply_safety_filters`가 매수 의도만 제거해 매도-only permit 발급이 가능하다. |
| P5-3 레짐 B 매수 | DONE | EQUITY_CAP도 현재 종목별 비중을 상한으로 사용해 신규·증가 매수를 금지한다. |
| P5-4 writer | DONE | `FillRepository`, `SnapshotRepository`를 구현했다. |
| P5-5 운영 항목 | OPEN | 락, 백업, 파일 0600, 로그 보존은 일일 오케스트레이터와 함께 구현한다. |

## 재검증 영향

- 레짐 B 동작과 공통 리스크 추출은 수익률·회전율·MDD에 영향을 줄 수 있으므로 실데이터
  연결 후 Phase 1 전체 시나리오를 다시 실행한다.
- 매도 후 실제 현금 기반 매수는 주문 수량과 포지션 정합성에 영향을 주므로 Phase 2
  paper 검증 기간을 새로 시작해야 한다.
- 사용자 승인 항목인 레짐 A/B 선택과 production 자본 상한은 자동 확정하지 않았다.
