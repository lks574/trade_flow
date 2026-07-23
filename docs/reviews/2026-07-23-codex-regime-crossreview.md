# 레짐 오버레이 효과 분석 교차검증

## 종합 판정: AGREE-WITH-CAVEATS

1. 제공된 데이터와 코드에서 baseline 및 `combo(exit25/10)`의 2020·2022·전체 결과는 원문과 반올림 단위까지 재현되며, 현행 오버레이가 2020 구간에는 유리하고 지정한 2022 구간에는 불리했다는 관찰은 맞다.
2. `combo(exit25/10)`이 2020 방어를 유지하면서 2022 손실과 전체 MDD를 줄였다는 표 내 비교도 맞지만, 같은 두 사건으로 파라미터를 고르고 평가한 탐색 결과라 일반화나 프로덕션 기본값 채택의 근거로는 부족하다.
3. 원문은 grade-C·단일 realization·표본 부족·파라미터 민감성을 대체로 명시했으나, “2022만 예외”라는 표현과 생존편향이 상대 비교에서 상당 부분 상쇄된다는 뉘앙스는 증거보다 강하다.

## 방법론 검증

### 1. `regime_states=None` 기준선

- `run_backtest`는 `regime_states is None`이면 해당 일자의 상태를 `active=False, valid=True`로 만든다(`src/trade_flow/backtest/engine.py:273-276`). 비활성 상태에서 `adjust_weights_for_regime`은 전략 목표 비중을 그대로 돌려준다(`src/trade_flow/risk/regime.py:101-102`). 따라서 이는 **레짐 오버레이만 끈 올바른 대조군**이다.
- 다만 “항상 매수 허용”은 문자 그대로는 아니다. `apply_risk_policy`는 레짐과 별개로 손절을 먼저 적용하고(`src/trade_flow/risk/policy.py:39-46`), 일수익률이 한도를 넘게 하락하면 매수 증가를 막는다(`src/trade_flow/risk/policy.py:61-67`). 정확한 명칭은 “레짐 비활성, 나머지 리스크 정책 유지”이다.
- 상태는 당일 종가 NAV를 만든 뒤 계산되고(`src/trade_flow/backtest/engine.py:229-235,261-308`), 주문 목표는 `pending`에 저장되어(`src/trade_flow/backtest/engine.py:318-322`) 다음 세션 시가에 실행된다(`src/trade_flow/backtest/engine.py:212-227`). 현재 백테스트 경로 자체에는 당일 종가 신호를 당일 종가 체결에 쓰는 look-ahead가 없다.

### 2. 구간 지표 계산

- 두 스크립트는 `lo <= session_date <= hi`로 종가 NAV 포인트를 포함하고(`scratch_regime_research/regime_windows.py:33-34`, `scratch_regime_research/regime_reentry.py:75-76`), `NAV(hi)/NAV(lo)-1`로 총수익을 구한다(`regime_windows.py:37-38`, `regime_reentry.py:77-78`). MDD는 구간 첫 NAV에서 peak를 재설정한다(`regime_windows.py:39-42`, `regime_reentry.py:79-82`). Sharpe는 이 슬라이스 안의 연속 종가 수익률, 무위험수익률 0, 모집단 분산, 252일 연율화로 계산한다(`regime_windows.py:43-46`, `regime_reentry.py:83-86`). 수식 자체는 일관되고 재현 가능하다.
- 경계 해석에는 주의가 필요하다. 총수익과 Sharpe는 `lo` 직전 종가에서 `lo` 종가까지의 수익을 포함하지 않으므로 “양 끝 날짜의 종가 사이” 성과이지, 시작 거래일을 포함한 일별 성과가 아니다. MDD도 `lo` 이전 고점을 무시한다. 이벤트 시작일이 의도한 고점 종가인 2020 구간에는 자연스럽지만, 일반적인 달력 구간 성과와 레짐 활성 일수의 포함 정의를 맞추려면 시작일 직전 equity point를 기준 NAV로 써야 한다.
- 레짐 활성 일수는 상태가 주문에 반영되는 다음 거래일과 완전히 같은 개념이 아니다. 표의 활성 수는 해당 날짜의 상태 수(`scratch_regime_research/regime_windows.py:69-71`)이고, 그 상태는 다음 시가 주문에 반영된다. 특히 구간 마지막 날의 활성 상태는 구간 밖 체결에 영향을 줄 수 있다.

### 3. 로컬 재진입 빌더와 프로덕션 빌더 대조

- 프로덕션은 정렬된 입력을 쓰고(`src/trade_flow/risk/regime.py:37`), 유효한 WTI 종가만 history에 추가하며(`src/trade_flow/risk/regime.py:45-55`), `N+1`번째 유효 관측부터 `history[-1]/history[-(N+1)]-1`의 20관측 수익률을 계산한다(`src/trade_flow/risk/regime.py:63-72`). 로컬 빌더도 같은 정렬 입력(`scratch_regime_research/regime_reentry.py:36`), 유효성/누적 조건(`regime_reentry.py:45-53`), WTI 인덱싱·엄격한 `>` 임계(`regime_reentry.py:54-58`)를 쓴다.
- 진입은 양쪽 모두 `VIX > 30 OR WTI > 30%`이고, invalid 데이터는 fail-closed로 즉시 active 및 streak 0이 된다(프로덕션 `src/trade_flow/risk/regime.py:57-76`, 로컬 `scratch_regime_research/regime_reentry.py:59-63`). 로컬의 변경점은 active 상태 해제 시 `VIX > exit_vix OR WTI trigger`를 위험 지속으로 보고 지정 일수만큼 연속 해제 신호를 요구하는 부분이다(`regime_reentry.py:60-70`). 실행에 영향을 주는 `active/valid/false_streak`는 baseline `(30,3)`에서 프로덕션과 동일하다.
- 독립 비교에서 2016-01-01~2026-07-21의 2,654개 regime input 날짜 모두에 대해 baseline 로컬 빌더와 프로덕션의 `(active, valid, false_streak)` 차이는 0건이었다.
- 단, 객체 전체가 bit-identical한 것은 아니다. 프로덕션은 `invalid_vix`, `invalid_wti`, `insufficient_wti_history`, `vix`, `wti` 이유를 기록하지만(`src/trade_flow/risk/regime.py:43-55,58-72,84-90`), 로컬은 모든 `reasons`를 빈 튜플로 만든다(`scratch_regime_research/regime_reentry.py:71`). 비교 기간에 프로덕션 reasons가 비어 있지 않은 날짜는 218개였다. 현재 엔진 성과에는 영향을 주지 않지만 감사·진단 메타데이터까지 “오직 해제 조건만 변경”한 것은 아니다.

## 결론 재현 결과

실행 명령:

```text
.venv/bin/python scratch_regime_research/regime_reentry.py
```

실행 데이터는 생존 종목 494개, 종료일 2026-07-21, 거래비용 15bp였다. 결과는 다음과 같다.

| 구성 | 2020 급락+회복 수익/MDD | 2022 베어 수익/MDD | 전체 총수익/MDD | active |
|---|---:|---:|---:|---:|
| 없음 | +32.8% / -39.4% | -25.3% / -37.1% | +379.9% / -55.2% | 0 |
| baseline(exit30/3) | +49.0% / -23.4% | -35.2% / -44.6% | +348.9% / -55.0% | 283 |
| combo(exit25/10) | +50.3% / -19.4% | -26.4% / -34.6% | +341.7% / -49.7% | 563 |
| exit22/5 | -19.0% / -19.4% | -27.3% / -35.4% | +168.8% / -58.9% | 537 |

원문과의 차이는 표시 자릿수뿐이다(`+379.9%→+380%`, `+348.9%→+349%`, `+341.7%→+342%`, `+168.8%→+169%`). 따라서 다음 좁은 결론은 재현된다.

- 현행 baseline은 없음 대비 2020 급락+회복에서 수익을 16.2%p 높이고 MDD를 16.0%p 줄였지만, 2022 지정 창에서는 수익을 9.9%p 낮추고 MDD를 7.5%p 키웠다.
- combo는 baseline 대비 2020 수익을 1.3%p 높이고 MDD를 4.0%p 줄였으며, 2022 수익을 8.8%p, MDD를 10.0%p 개선했다. 전체 MDD도 5.3%p 개선되었다. 반면 전체 총수익은 baseline보다 7.2%p 낮으므로 “전체적으로 우월”이 아니라 **선택 구간과 전체 MDD의 개선**으로 한정해야 한다.
- exit22/5는 2020 수익이 baseline +49.0%에서 -19.0%로 무너졌고 전체 MDD도 -58.9%로 악화했다. 재진입 지연의 tradeoff 및 파라미터 민감성 주장은 강하게 지지된다.
- 다구간 표에서 2018 Q4, 2020 두 정의, 2020 전체, 2025~26은 오버레이가 없음보다 나았고 2022의 두 겹치는 정의만 나빴다(`docs/reviews/2026-07-23-regime-overlay-effectiveness.md:15-25`). 따라서 “검사한 표에서는 2022만 예외”라는 정정은 타당하다. 그러나 선택된 7개 창 중 독립적인 사건은 더 적고, 두 2020 창과 두 2022 창은 중복되므로 “모든 또는 대부분의 다른 레짐 사건에서도 유효”로 확대할 수는 없다.

## 발견한 오류·과장·과최적화 위험

### High — combo 선택은 인샘플 파라미터 탐색이다

6개 변형을 2020·2022·전체 동일 realization에서 비교하고 그중 목표에 가장 맞는 combo를 선택했다(`scratch_regime_research/regime_reentry.py:90-102,106-121`). 별도 holdout, walk-forward, 파라미터 안정성 면, 다중 비교 보정이 없다. 원문이 이를 “잠정”, “파라미터 민감”, “grade-B 전제”라고 제한한 점은 적절하지만(`docs/reviews/2026-07-23-regime-overlay-effectiveness.md:65-70`), 현재 수치로 `25/10` 자체를 프로덕션 기본값으로 정하면 과최적화 위험이 높다.

### Medium — “2022에만 역효과”는 검증 범위를 넘어선다

표는 선정된 스트레스 창에서는 주장을 지지하지만 2016~2026의 모든 레짐 episode를 사건 단위로 열거·검정하지 않았다. “검사한 창 중 2022만 역효과”가 정확한 표현이다. 또한 “약세에 줄인 뒤 더 높게 재진입” 같은 메커니즘 설명(`docs/reviews/2026-07-23-regime-overlay-effectiveness.md:27-34`)은 총수익/MDD 표만으로 직접 검증되지 않았으며, 체결·현금비중·재진입 가격의 event study가 필요하다.

### Medium — 생존편향은 상대 비교에서도 완전히 상쇄되지 않는다

유니버스는 현재 S&P 500 스냅샷임이 명시돼 있다(`configs/universe_main.toml:1-2`). 동일 유니버스 비교가 공통 오차를 줄이는 것은 맞지만, 오버레이 효과는 당시 선택 종목, 파산·퇴출 종목, 회복 탄력과 상호작용하므로 생존편향이 차분에서 자동 소거되지는 않는다. 특히 2020 V자 회복 참여와 재진입 비용 추정에는 영향을 줄 수 있다. 원문의 grade-B 이전 확정 금지 권고는 맞지만, “상대 결론은 견고”는 “절대 성과보다 덜 취약” 정도로 낮춰야 한다(`docs/reviews/2026-07-23-regime-overlay-effectiveness.md:36-40`).

### Medium — 구간 경계와 파라미터 효과의 비단조성

시작일 수익 제외·구간 첫 NAV에서 MDD 재설정 때문에 날짜 라벨을 달리 잡으면 수치가 달라질 수 있다. 또한 exit22/5가 2020 회복을 거의 전부 놓치지만 더 긴 combo exit25/10은 오히려 성과가 좋다는 비단조 결과는 단순히 “엄격할수록 늦게 재진입”하는 안정적 관계가 아니라 전략 리밸런싱 경로와 특정 날짜에 매우 민감함을 보여준다.

### Low — active는 주식 거래 세션 수와 항상 같지 않다

regime input은 VIX와 WTI 날짜의 합집합으로 만들어진다(`src/trade_flow/db/market_context.py:70-77`). 전체 2,654개 context 날짜 중 가격 거래일은 2,513개였고, baseline active 283일 중 36일은 주식 가격 세션이 아니었다. 따라서 전체 `active=283`은 엔진에서 실제 신호를 만든 주식 세션 수(247)가 아니다. 해제 streak도 WTI만 열린 날짜 등에 증가할 수 있으므로 프로덕션 의미가 “주식 거래일 3일 확인”인지 “시장 컨텍스트 관측 3회 확인”인지 명시해야 한다. 선택된 과거 창의 표 수치는 그대로 재현되지만 운영 정의와 진단 지표에는 차이가 있다.

### Low — 프로토타입의 진단 정보 누락

로컬 빌더는 reasons를 보존하지 않는다. 성과 비교에는 무관하지만, 향후 프로덕션 구현과 회귀 테스트에서는 active 상태뿐 아니라 valid, streak, reasons까지 기존 기본값에서 동일해야 한다.

## 프로덕션 도입 시 권고

1. 현재 증거로는 방향성 실험만 승인하고 `exit25/10`을 기본값으로 확정하지 않는다. `exit_vix_threshold=regime_vix_threshold`, `exit_confirmation_days=3`을 기존 동작 보존 기본값으로 추가하고, 프로덕션 빌더의 기존 출력이 `active/valid/false_streak/reasons`까지 동일한 회귀 테스트를 둔다.
2. 의사결정 시점을 고정한다. VIX·WTI의 해당 일자 최종값이 실제로 이용 가능해진 뒤 상태를 계산하고 다음 거래일 시가에만 반영한다. 수정 후에도 `signal_date < execution_date` 불변식을 테스트해 look-ahead를 막는다.
3. exit streak의 달력을 명세한다. 주식 거래 세션 기준이라면 NYSE 세션에 상태를 정렬하고, WTI-only 날짜가 확인 일수를 앞당기지 않게 한다. 결측은 현재처럼 fail-closed로 처리하되 휴장과 진짜 결측을 구분한다.
4. grade-B point-in-time 유니버스로 2018·2020·2022·2025 외 모든 독립 active episode를 사전 정의해 event study를 수행한다. 각 episode에서 방어, 회복 지연, 현금비중, turnover, 매매비용, 재진입 가격을 함께 보고한다.
5. 파라미터는 `(exit_vix, exit_days)` 격자 전체의 안정성 면을 보고 선택하고, 시간순 walk-forward/holdout과 block bootstrap을 사용한다. 2020·2022를 튜닝에 썼다면 최종 검증에서는 제외하거나, 최소한 해당 결과를 인샘플이라고 명시한다.
6. 정책 판단은 수익/MDD 둘만으로 하지 않는다. 전체 CAGR·Sharpe·Calmar, 최악 episode, underwater duration, active 비율, 거래비용 민감도를 사전 합의한 목적함수로 평가한다. combo는 현재 표에서 전체 총수익을 소폭 희생해 MDD를 개선한 선택이므로 그 tradeoff를 명시적으로 승인받아야 한다.
