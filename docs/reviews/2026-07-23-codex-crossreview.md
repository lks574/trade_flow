# 2026-07-23 turnover 스펙 개정안·최근 리팩터 교차검증

## 종합 판정: APPROVE-WITH-CHANGES

1. `cf98fb1`의 사전계산은 현재 운영 설정에서 `_raw_factors`의 모든 산술 순서와 prefix 상태를 보존하며, 추가 무작위 검증에서도 `Decimal.as_tuple()`까지 일치했다. 미래 바 참조도 없다.
2. hysteresis의 선정 로직과 band의 일반 재조정 억제 방향, 비용/turnover 및 스윕 수치는 재현된다. 다만 band가 양수인 리스크 축소 목표까지 억제하므로 제안서가 요구한 §3.4 우선순위와 현재 구현은 일치하지 않는다.
3. 제안서의 회전 금액 약 98% 귀속은 맞지만 “미세조정이 거래 건수의 ≈93%”는 틀리고, 494종목 비용 실험과 502종목 스윕이 섞여 있으며, 수익 급증을 생존편향의 *원인 증명*으로 단정한 표현도 완화해야 한다.

## 정확성 검증 결과

### 1. `precompute_factor_series`와 `_raw_factors`의 prefix 동치

**판정: 현재 설정에서는 bit-identical로 신뢰할 수 있다.**

- 두 경로는 모두 `split_adjusted_close`를 입력으로 쓴다(`src/trade_flow/backtest/precompute.py:63`, `src/trade_flow/strategy/signal.py:55`). 사전계산은 날짜순 정렬 후 처리하고(`precompute.py:58`), 엔진도 날짜순 세션을 순회해 심볼별 배열을 만든다(`engine.py:175-188`).
- SMA는 원본의 마지막 `period`개 합/나눗셈(`indicators.py:7-10`)과 사전계산의 동일 순서 슬라이스 합/나눗셈(`precompute.py:73-77`)이 같다. momentum도 원본의 `[-(days+1)]`(`signal.py:59`)과 인덱스 `i-days`(`precompute.py:78`)가 같은 바를 가리킨다.
- RSI 시드는 두 경로 모두 첫 `period`개 변화의 gain/loss 산술평균이다(`indicators.py:26-30`, `precompute.py:37-46`). 이후 Wilder 점화식 `(avg*(period-1)+new)/period`의 괄호와 연산 순서도 동일하다(`indicators.py:31-33`, `precompute.py:47-50`). 미래 변화 배열을 미리 만들어 둘 뿐, `out[i]` 계산에는 `i` 이후 변화가 들어가지 않는다.
- EMA는 첫 종가를 seed로 두고 `alpha*value + (1-alpha)*previous`를 앞에서부터 한 번 적용한다(`indicators.py:13-20`). MACD 원본도 fast/slow EMA 차의 EMA를 같은 방식으로 계산한다(`indicators.py:40-51`). 전체 배열 forward-pass의 인덱스 `i`와 `closes[:i+1]` 재계산의 마지막 값은 동일한 seed와 동일한 점화식 호출 수를 가지므로 prefix 동치다(`precompute.py:65-69,82`).
- 평균 거래대금은 두 경로 모두 각 바에서 `close * Decimal(volume)`을 먼저 계산한 뒤 최근 기간을 같은 순서로 합산하고 실제 슬라이스 길이로 나눈다(`signal.py:70-73`, `precompute.py:64,83-85`). 현재 설정은 `minimum_price_days=201`이고 모든 사용 기간보다 길어 음수 슬라이스나 부족 기간이 없다(`configs/strategy.toml:5-21`).
- `Decimal` quantize나 별도 반올림은 어느 경로에도 없다. 같은 context 아래 같은 피연산자와 괄호 순서를 쓰므로 중간 반올림 지점도 같다. 기존 테스트는 모든 201~300 prefix를 직접 비교한다(`tests/unit/test_precompute.py:45-61`). 추가로 precision 12/28/50, 무작위 10개 시계열씩 총 7,500개 적격 prefix를 비교했고 값뿐 아니라 각 `Decimal.as_tuple()`도 모두 일치했다.

**한계:** `StrategyConfig.__post_init__`는 기간이 양수이고 short/long 및 fast/slow 순서가 맞는지만 검사하며, `minimum_price_days`가 SMA/momentum/MACD/유동성 기간 이상인지는 보장하지 않는다(`src/trade_flow/domain/config.py:75-95`). 따라서 함수 docstring의 무조건적 동치 계약(`precompute.py:54-57`)은 임의의 유효 `StrategyConfig`까지 일반화하면 과하다. 현재 TOML에는 문제가 없지만 config invariant를 추가하는 편이 안전하다.

### 2. sub-snapshot `require_valid` 제거, 후상장 종목, look-ahead

**판정: 후상장 중단은 해소하고 미래 참조는 만들지 않았지만, “최상위 snapshot이 valid이므로 동등”이라는 설명은 불충분하다.**

- 엔진은 여전히 진입 시 최상위 snapshot을 fail-closed 검증한다(`engine.py:172`). 그러나 최상위 `missing_recent_bar` 검사는 `as_of` 기준 마지막 20개 세션만 본다(`src/trade_flow/data/market.py:190-201,218`). 과거 중간 결측은 최상위 snapshot에서 valid일 수 있지만, 예전 엔진의 해당 시점 sub-snapshot에서는 최근 20개 안에 들어 invalid였다.
- 이를 직접 재현했다. 230세션 중 한 종목의 196번째 바만 제거하자 최상위 snapshot은 valid였고, 201번째 세션 sub-snapshot은 `missing_recent_bar`로 invalid였지만, 새 엔진은 230세션을 끝까지 실행했다. 따라서 `engine.py:238-240`의 “최상위가 통과했으므로 유효 데이터에서는 결과 동일”은 “전 기간 무결성이 별도로 보장된 데이터”로 한정해야 한다.
- 반면 후상장 심볼은 `seen_count < minimum_price_days`일 때 정상적으로 `insufficient_history`가 되고(`engine.py:228-248`), 충분한 자체 이력이 쌓인 뒤만 factor가 나온다. 정적 현재 유니버스의 상장 전 세션을 결측으로 보아 전체 실행을 중단하던 블로커 C를 *운영상* 해소했다는 주장은 맞다. 다만 listing interval 기반 품질 검증으로 해결한 것이 아니라 rolling validation을 제거한 것이므로, 과거 실제 결측과 상장 전 부재를 구분하는 보완이 필요하다.
- look-ahead는 없다. 각 세션에서 당일까지 관측한 바 수를 증가시킨 뒤 `factor_series[symbol][count-1]`만 읽고(`engine.py:228-248`), 위 forward recurrence도 그 index 이전 입력만 사용한다. 신호로 만든 `pending`은 다음 세션 open에서 실행된다(`engine.py:205-219,301-303`).

## 구현·제안 일치 여부

### 3. 두 레버

#### `selection_hysteresis`

- `_select_ranked`는 `ranked[:count+hysteresis]` 안의 보유 종목을 먼저 유지하고 나머지를 전체 순위의 상위 미유지 종목으로 채운다(`src/trade_flow/strategy/signal.py:90-102`). 이는 제안서의 “상위 N+버퍼 이내 유지, 남는 자리 신규 상위로 채움”(`docs/reviews/2026-07-23-turnover-spec-amendment-proposal.md:69-72`)과 일치한다.
- `ranked` 자체가 `raw`에 남은 적격 종목만 포함하므로 장기 SMA 하회/이력 부족 종목은 유지 후보가 아니다(`signal.py:124,147-164`; `engine.py:243-252`).
- 손절은 선정 단계에서 제외되는 것은 아니지만, 뒤의 공통 리스크 정책이 해당 보유 종목의 최종 목표를 0으로 덮어쓴다(`src/trade_flow/risk/policy.py:39-46`). 따라서 최종 주문 관점에서는 hysteresis보다 손절이 우선한다.
- `selection_hysteresis <= 0`은 즉시 기존 `ranked[:count]`를 반환한다(`signal.py:96-97`). 기본값 0은 실제 no-op이다. 다만 음수도 조용히 no-op이므로 입력 검증은 추가하는 편이 낫다.

#### `rebalance_band`

- 현재 수량과 목표 비중이 모두 양수인 종목만 검사하고, open 기준 현재 비중과 목표의 절대 차이가 `<= band`이면 현재 수량을 유지한다(`src/trade_flow/backtest/engine.py:84-95`). 신규 진입(현재 0)과 완전 청산/손절(목표 0)은 우회하므로 제안서 `:73-75`의 핵심 동작과 일치한다.
- `rebalance_band=0`이면 분기 자체가 실행되지 않아 기존 수량 계산/매도 우선/매수 로직이 그대로다(`engine.py:74-84,96-156`). 명시적 0과 기본값은 no-op이다. 음수도 조용히 비활성화된다.
- 그러나 “보유·선정 유지 종목의 일반 재조정만”이라는 의미를 엔진은 판별하지 못한다. band에는 최종 `target_weights`와 수량만 전달되고 리스크 사유가 전달되지 않는다(`engine.py:59-69,208-217`). 그 결과 현재 비중 26%, 리스크 축소 목표 25%, band 2%인 재현에서 매도 주문이 0건이었다. 목표 0인 손절만 예외라는 현재 구현은 §3.4의 모든 축소 매도를 보호하지 못한다.

### 4. 제안서 결론과 정량 근거

- 비용 민감도 표는 저장 산출물과 일치한다. BUY_BLOCK의 5/15/30bp는 각각 CAGR 0.3300/0.1775/-0.0221, MDD -0.4328/-0.5500/-0.7874, turnover 1112.94/1121.38/1142.09다(`backtests/gradeC_full_evaluate.json:458-466,488-496,518-526`). 30bp 손실 전환 주장은 맞다.
- `turnover = traded_notional / average_nav` 정의(`src/trade_flow/validation/metrics.py:71-79`)이므로 30bp 비용의 단순 규모는 `1142.09 × 0.003 = 3.426` average-NAV다. 제안서의 “NAV 약 3.4배”는 이 의미라면 맞지만, 초기 NAV나 최종 NAV 대비 누적 비용으로 읽히지 않도록 분모를 명시해야 한다.
- 전체 quick baseline을 동일 데이터로 재실행하고 포지션이 0↔양수로 바뀌는 진입/완전청산을 rotation, 양수↔양수 수량 변경을 micro로 분류했다. rotation notional은 97.6738%, micro는 2.3262%로 제안서의 약 98%/2% 귀속을 정확히 뒷받침한다. 따라서 “금액은 로테이션이 지배”한다는 결론은 타당하다.
- 같은 분류에서 건수는 rotation 6,401건, micro 7,121건으로 micro 비중이 **52.66%**였다. 제안서의 “건수로 미세 재조정이 ≈93%”(`proposal.md:33`)는 동일한 금액 분류와 양립하지 않으며 수정해야 한다.
- band 0/1/2/3% 재실행 결과 turnover 1124.38/1110.27/1105.87/1105.03, 거래수 13,522/6,921/6,550/6,474로 표(`proposal.md:39-46`)를 재현했다. hysteresis buffer 0/5/15/45도 turnover 1124.38/693.30/611.76/549.87, 거래수 13,522/12,456/12,208/12,038로 표(`proposal.md:50-57`)를 재현했다.
- 다만 비용 표의 저장 산출물은 최신일을 보존하는 evaluate 경로(`scripts/backtest.py:70-76,212-214`)에서 494종목을 사용한 반면, 위 스윕은 최종 불량일을 cap한 2026-07-20, 502종목으로 재현된다. 제안서가 모두 “494종목”인 하나의 모집단처럼 서술한 것은 재현성 메타데이터 오류다.
- top-10의 CAGR 49.14%와 top-50의 18.97%도 재현된다. 현재 유니버스가 명시적으로 “current snapshot, survivorship-biased”다(`configs/universe_main.toml:1-2`)라는 점에서 생존편향 오염을 강하게 의심하고 grade-B PIT 전 튜닝을 보류하는 결론은 합리적이다. 그러나 비단조 수익 변화만으로 급증의 원인이 생존편향이라고 증명되지는 않는다. “생존편향 아티팩트다”(`proposal.md:63`)는 “생존편향과 파라미터 민감도가 섞여 있어 진짜 edge로 해석할 수 없다”로 완화해야 한다.

### 5. Codex 리뷰 포인트 3개에 대한 답

1. **hysteresis × 손절:** 최종 목표 관점에서 충돌 없다. 적격성 상실 종목은 `raw`/순위에서 빠지고, 손절 종목은 이후 `apply_risk_policy`가 목표 0으로 덮는다(`signal.py:147-164`, `risk/policy.py:39-46`). 다만 스펙 문언은 “선정에서 제외”보다 “최종 리스크 목표가 hysteresis를 우선한다”가 실제 파이프라인을 더 정확히 설명한다.
2. **band × §3.4 리스크:** 부분 충돌한다. 목표 0인 손절/청산은 보호되지만, 비중 상한·EQUITY_CAP·BUY_BLOCK·일일손실 정책이 만든 **양수인 축소 목표**는 band 안에서 억제될 수 있다. `apply_risk_policy`는 이런 축소를 양수 `min(...)`으로 만든다(`risk/policy.py:48-67`; `risk/regime.py:94-119`). 리스크 축소는 band보다 우선하도록 사유 또는 pre-risk 목표를 band 로직에 전달해야 한다.
3. **drift·주문 가능 현금:** 백테스트 band는 `OrderPlan.drift`를 생성하지 않는다. 프로덕션 planner도 아직 band/hysteresis 파라미터가 없고 drift는 quote/현금 부족만 기록한다(`src/trade_flow/execution/planner.py:40-60,111-148`). 따라서 “이미 엔진에 구현”은 연구 백테스트에만 해당한다. 현금 안전성은 매도 후 실제 account를 재조회해 매수를 다시 계획하고(`src/trade_flow/execution/rebalance.py:97-143`), planner가 실제 cash에서 buffer/fee를 차감해 affordability를 제한하므로 유지된다(`planner.py:111-145`). 다만 band로 매도를 생략하면 예상 매수 일부가 현금 제한될 수 있으므로 `within_rebalance_band`, `cash_limited_quantity`를 최종 drift에 함께 남기는 정책을 명시해야 한다.

## 발견한 버그/오류/과장

| 심각도 | 발견 사항 | 근거와 영향 |
|---|---|---|
| **High** | band가 §3.4의 양수 리스크 축소 목표를 억제한다 | `engine.py:84-95`는 `target_weight > 0`인 모든 목표에 band를 적용한다. `risk/policy.py:48-67`, `risk/regime.py:94-119`의 상한/레짐/일손실 축소가 무시될 수 있다. |
| **Med** | rolling 품질 검증 제거를 최상위 valid와 동치라고 설명했다 | `market.py:190-201`은 마지막 20세션만 검사한다. 과거 결측을 가진 top-level-valid snapshot이 새 엔진에서 통과하는 반례를 재현했다. |
| **Med** | 미세조정 거래 건수 ≈93%가 틀렸다 | 동일한 rotation/micro 분류로 7,121/13,522 = 52.66%다. 금액 비중 2.326%는 맞다. |
| **Med** | 생존편향을 수익 급증의 확정 원인으로 단정했다 | 데이터가 생존편향됐다는 사실(`universe_main.toml:1-2`)은 오염 가능성을 입증하지만, PIT 대조군 없이 인과 원인을 분리할 수 없다. |
| **Low** | 494종목 비용 표와 502종목 스윕을 동일 모집단처럼 서술했다 | evaluate와 quick의 `cap_final` 정책이 다르다(`scripts/backtest.py:70-76,212-214`). 결과별 end/date, symbol count, hashes가 필요하다. |
| **Low** | 범용 config에서 precompute 계약이 과도하다 | config는 `minimum_price_days >= max(required periods)`를 검증하지 않는다(`domain/config.py:75-95`). 현재 설정에서는 문제없다. |
| **Low** | 음수 band/hysteresis가 오류 대신 no-op이다 | `engine.py:84`, `signal.py:96`. 잘못된 실험 인자를 숨길 수 있다. |
| **Low** | 스펙 변경과 프로덕션 구현 상태가 혼동될 수 있다 | 토글은 backtest 경로에만 있고 `execution/planner.py:40-50`에는 없다. drift 정책도 미정이다. |

## 권고 수정사항

1. 스펙에 우선순위를 명시한다: **손절·전략 청산·비중 상한·레짐/일손실에 의한 모든 축소 주문 > no-trade band > 일반 재조정**. 엔진에는 risk reason 또는 pre/post-risk target을 전달해 리스크 축소 여부를 판별하도록 한다.
2. band가 생략한 차이는 `within_rebalance_band` drift로 기록하고, 매도 생략 후 실제 cash로 재계산되어 축소된 매수는 기존 `cash_limited_quantity`와 함께 보존하도록 프로덕션 planner 계약을 추가한다.
3. 과거 전 구간의 bar 결측을 listing interval과 대조하는 사전 품질 검증을 추가한다. 상장 전 부재는 허용하되 상장 후 임의 결측은 fail-closed 또는 명시적 exclusion으로 처리한다.
4. 제안서의 거래 건수 93%를 52.7%로 고치고, 각 표에 `as_of/end`, symbol count, `data_hash`, `config_hash`, 실행 인자를 기록한 sweep JSON을 저장한다. 494종목 evaluate와 502종목 quick 결과는 별도 모집단으로 표시한다.
5. 생존편향 문구를 인과 단정에서 “오염되어 해석 불가”로 낮추되, grade-B PIT 이전 파라미터 확정 금지 결론은 유지한다.
6. `StrategyConfig`에 필요한 최소 이력 invariant를, 러너에 `rebalance_band >= 0` 및 `selection_hysteresis >= 0` 검증을 추가한다. precompute 회귀 테스트에는 다양한 Decimal precision/가격 경로와 `Decimal.as_tuple()` 비교를 보강한다.

## 실행 검증

- `.venv/bin/python -m pytest -q tests/unit/test_precompute.py tests/unit/test_backtest.py tests/unit/test_signal.py tests/unit/test_risk_policy.py tests/unit/test_rebalance.py` → **12 passed**
- full-universe quick 재현: baseline 및 band 1/2/3%, hysteresis 5/15/45를 독립 재실행했고 위 표의 turnover·거래수·CAGR을 확인했다.
- 별도 반례 실행: top-level-valid/rolling-invalid 과거 결측 snapshot, band가 양수 리스크 축소를 막는 수량 예제를 각각 재현했다.
