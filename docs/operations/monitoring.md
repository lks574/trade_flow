# 일일 모니터링과 주간 후보 탐색

## 목적

`monitor-daily`는 보유종목의 가격·거래량·추세·손절·중대 이벤트를 검토하고 진입 기준을
통과한 후보를 최대 3개까지 보고한다. `screen-weekly`는 전체 활성 유니버스에서 기준을
통과한 신규 후보를 최대 5개까지 찾고 기존 보유종목과 비교한다.

두 명령 모두 분석 리포트만 생성한다. `execution_authorized`는 항상 `false`이며 출력이
주문 의도나 주문 허가로 자동 변환되지 않는다.

## 운용 주기

- 미국 정규장 완료 후 매일 `monitor-daily`를 실행한다.
- 주 마지막 완료 세션 이후 `screen-weekly`를 실행한다.
- 휴일이나 주말 날짜를 `--as-of`로 주면 DB에서 그 날짜 이전의 최신 세션을 신호일로 쓴다.
- 손절이나 중대한 부정 이벤트는 일일 리포트에서 `exit` 검토 대상으로 표시한다.
- 데이터 결측은 자동 매도가 아니라 실행 실패 또는 `blocked`로 처리한다.

## 선행 조건

1. `trade-flow init-db`로 canonical DB를 초기화한다.
2. 동일한 `source`로 최소 201개 완료 세션의 검증된 가격을 `prices`에 적재한다.
3. 실행일에 활성인 종목을 유니버스 TOML에 등록한다.
4. 실제 계좌나 paper 계좌 스냅샷을 portfolio JSON 계약으로 변환한다.
5. 뉴스·공시·거시·지정학 이벤트를 events JSON 계약으로 정규화한다.

현재 저장소에는 실시간 뉴스 수집기가 없다. `events`는 공급자 어댑터가 생성해야 하며,
출처·시각·영향 방향·심각도·신뢰도를 보존해야 한다.

## Portfolio JSON

```json
{
  "positions": [
    {
      "symbol": "AAPL",
      "quantity": 10,
      "average_price": "210.00",
      "market_price": "215.00"
    }
  ]
}
```

수량은 양의 정수이며 가격은 Decimal로 해석할 문자열을 권장한다. 중복 심볼은 거부한다.

## Events JSON

```json
[
  {
    "event_id": "provider-stable-id",
    "published_at": "2026-07-21T12:00:00+00:00",
    "headline": "Material event",
    "source": "provider-name",
    "scope": "company",
    "direction": "negative",
    "severity": "high",
    "confidence": "0.90",
    "summary": "Normalized event summary",
    "affected_symbols": ["AAPL"]
  }
]
```

- `scope`: `company`, `sector`, `macro`, `geopolitical`, `global` 중 하나여야 한다.
- `direction`: `positive`, `negative`, `mixed`, `neutral` 중 하나다.
- `severity`: `low`, `medium`, `high`, `critical` 중 하나다.
- 시각은 UTC offset이 포함된 ISO 8601이어야 한다.
- `macro`, `geopolitical`, `global` 이벤트는 모든 보유종목에 적용한다.
- 회사·업종 이벤트는 영향 종목을 `affected_symbols`에 명시한다.

## 판정 규칙

일일 보유종목 판정 우선순위는 다음과 같다.

1. 최신 가격 결측: `blocked`
2. 고정 손절 도달: `exit`
3. 신뢰도 기준을 통과한 치명적 부정 이벤트: `exit` 검토
4. 신뢰도 기준을 통과한 고강도 부정 이벤트: `reduce`
5. 활성 유니버스 이탈 또는 SMA200 이탈: `reduce`
6. 대량거래를 동반한 일일 급락, 위험 레짐, 보유 순위 이탈: `watch`
7. 그 외: `hold`

신규 후보는 최소 진입점수를 통과하고 고강도 부정 이벤트가 없는 종목만 포함한다.
일일 후보는 현재 목표 비중에 포함된 종목 중 최대 3개다. 주간 후보는 전체 적격 종목 중
최대 5개다. 적격 종목이 부족하면 개수를 채우지 않는다.

주간 교체는 신규 후보가 최소 진입점수를 통과하고, 기존 보유종목이 `reduce`·`exit`이거나
보유 허용 순위 밖이며, 점수 차이가 설정된 최소 마진 이상일 때만 추천한다. 위험 레짐 중에는
후보를 관찰할 수 있지만 교체를 추천하지 않는다.

뉴스와 정세 이벤트는 보유종목의 `watch`·`reduce`·`exit` 검토와 후보 제외에만 사용한다.
리포트의 추천은 사용자가 검토할 의견이며 주문으로 변환되지 않는다. 모든 리포트는
`execution_authorized: false`를 명시한다.

## 출력 계약과 현재 보관 범위

일일 JSON의 최상위 필드는 `as_of`, `data_hash`, `config_hash`, `positions`,
`entry_candidates`, `material_events`, `alerts`, `execution_authorized`다. 주간 JSON은
`as_of`, 두 hash, `holdings`, `candidates`, `comparisons`, `material_events`, `alerts`,
`execution_authorized`를 포함한다. 명령은 JSON을 표준 출력으로 내보내므로 필요하면 파일로
보관할 수 있다.

```bash
mkdir -p reports

trade-flow monitor-daily \
  --db data/trade_flow.db \
  --config configs/strategy.toml \
  --universe configs/universe_main.toml \
  --portfolio configs/portfolio.example.json \
  --events configs/events.example.json \
  --source kis \
  --as-of 2026-07-21 \
  > reports/daily-$(date +%F).json

trade-flow screen-weekly \
  --db data/trade_flow.db \
  --config configs/strategy.toml \
  --universe configs/universe_main.toml \
  --portfolio configs/portfolio.example.json \
  --events configs/events.example.json \
  --source kis \
  --as-of 2026-07-21 \
  > reports/weekly-$(date +%F).json
```

현재 구현은 입력 JSON과 표준 출력 리포트까지만 지원한다. 리포트의 SQLite 누적 저장,
뉴스 공급자 자동 수집·중복 제거, Telegram 등 외부 채널 전송은 아직 구현하지 않았다.

## 설정

`configs/strategy.toml`의 `[monitoring]`에서 다음 값을 조정한다.

```toml
daily_candidate_limit = 3
weekly_candidate_limit = 5
hold_rank_limit = 10
minimum_entry_score = 0.75
replacement_score_margin = 0.10
large_move_fraction = 0.05
volume_spike_multiple = 2.0
material_event_confidence = 0.80
daily_event_lookback_days = 3
weekly_event_lookback_days = 7
```

값을 변경하면 config hash가 바뀐다. 백테스트 또는 paper 관찰 없이 운영 기준을 임의로
낮추지 않는다.
