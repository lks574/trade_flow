# 미국 시장 데이터 수집 전달 명세

- 작성일: 2026-07-21
- 전달 대상: 미국 주가·시장지표·유니버스 데이터 수집 담당자
- 사용처: Trade Flow 10년 백테스트, 모의투자 및 향후 실계좌 데이터 검증
- 우선순위: **이 문서의 필수 조건을 만족한 데이터만 canonical DB 변환 대상으로 사용한다.**

## 1. 요청 목적

기존 `tradeflow_us.db`는 2015년 이후의 데이터와 배당·분할 정보를 포함하지만 다음 이유로 현재 Trade Flow에 그대로 연결할 수 없다.

1. 가격이 배당까지 반영된 조정가격이라 배당 현금흐름을 별도로 반영하면 배당이 이중 계산된다.
2. 원본 OHLC와 분할만 반영한 OHLC를 구분할 수 없다.
3. 행별 데이터 출처와 수집시각이 없다.
4. 과거 지수 편입·제외 이력이 없어 생존 편향을 통제할 수 없다.
5. 수집 종료일 처리 때문에 최신 완료 거래일이 빠질 수 있다.

이번 요청의 목적은 위 문제를 해결한 **재현 가능하고 감사 가능한 원천 데이터셋**을 만드는 것이다.

## 2. 절대 준수사항

- 기존 파일 `/Users/kyungseok.lee/workspace/dev/TradeFlow/data/tradeflow_us.db`를 수정하거나 덮어쓰지 않는다.
- `auto_adjust=True`처럼 배당과 분할을 함께 반영한 OHLC를 원본 또는 split-adjusted OHLC로 저장하지 않는다.
- 배당 효과는 가격과 현금흐름 양쪽에 중복 반영하지 않는다.
- 공급자가 제공하는 `Adj Close`의 의미를 확인하지 않고 split-adjusted 가격으로 사용하지 않는다.
- 수집 시작일과 종료일을 로컬 달력 날짜로만 계산하지 않는다. 미국 거래소 캘린더와 `America/New_York` 시간대를 기준으로 최신 완료 세션을 결정한다.
- 실패한 종목을 조용히 제외하지 않는다. 실패 종목, 실패 구간, 오류 원인을 수집 결과에 기록한다.
- 현재 구성 종목을 과거 전체 기간에 속했다고 표시하지 않는다.
- 데이터 공급자가 KIS가 아니면 KIS 데이터라고 기록하지 않는다. 실제 공급자 이름을 저장한다.

## 3. 수집 범위

### 3.1 기간과 주기

| 항목 | 요구사항 |
|---|---|
| 주기 | 일봉 |
| 시작일 | 2015-01-02 또는 그 이전 |
| 종료일 | 수집 시점 기준 가장 최근에 완료된 미국 정규장 세션, 양 끝 포함 |
| 거래일 기준 | 미국 주식은 공식 미국 거래소 캘린더 |
| 세션 날짜 | `America/New_York` 기준 `YYYY-MM-DD` |
| 재수집 | 동일 키 upsert가 가능한 멱등 방식 |

공급자 API의 `end`가 배타적이면 최신 완료 세션의 다음 날짜를 요청 종료값으로 사용해야 한다. 수집 후 요청 종료일이 아니라 실제 저장된 `MAX(session_date)`를 검증한다.

### 3.2 주식 종목

최소한 기존 DB의 다음 76종목을 모두 수집한다. 종목을 추가하는 것은 가능하지만 누락하거나 임의 교체하면 안 된다.

```text
AAPL ABBV ABT ADBE ADI AMAT AMD AMGN AMZN AVGO
AXP BA BAC BLK BMY C CAT CMCSA COP COST
CRM CSCO CVX DE DHR DIS GE GILD GOOGL GS
HD HON IBM INTC INTU ISRG JNJ JPM KO LLY
LMT LOW LRCX MA MCD META MMM MRK MS MSFT
MU NFLX NKE NOW NVDA ORCL PEP PFE PG QCOM
RTX SBUX SCHW SLB T TGT TJX TMO TXN UNH
UNP V VZ WFC WMT XOM
```

추가로 벤치마크 및 레짐 계산에 필요한 `SPY`, `QQQ`도 동일한 주식/ETF 가격 계약으로 수집한다.

### 3.3 시장 컨텍스트

다음 시계열을 별도 시장지표 데이터로 수집한다.

| canonical symbol | 의미 | 공급자 심볼 예시 |
|---|---|---|
| `VIX` | CBOE 변동성 지수 | `^VIX` |
| `WTI` | WTI 근월물 또는 명시된 연속선물 | `CL=F` |
| `TBILL_13W` | 미국 13주 단기금리 | `^IRX` |

공급자 심볼은 예시와 달라도 되지만 canonical symbol과 실제 provider symbol의 매핑을 남겨야 한다. 시장지표는 주식과 달리 0 또는 음수가 실제로 존재할 수 있으므로 양수 가격 제약을 적용하지 않는다.

WTI는 반드시 다음을 설명해야 한다.

- 근월물 단순 연결인지, 조정된 연속선물인지
- 롤오버 규칙
- 가격 조정 방식
- 음수 가격 보존 여부

이 설명이 없으면 장기 레짐 백테스트용 WTI 데이터로 승인하지 않는다.

## 4. 가격 및 corporate action 계약

### 4.1 반드시 구분할 값

주식/ETF 각 일봉에는 아래 두 가격 계열이 모두 있어야 한다.

1. **Raw OHLC:** 해당 거래일 당시 실제 호가 단위의 OHLC. 배당조정과 분할조정을 적용하지 않은 값.
2. **Split-adjusted OHLC:** 분할만 반영해 하나의 주식 수량 기준으로 연결한 OHLC. 배당은 반영하지 않은 값.

`Adj Close`가 배당까지 반영된 total-return 계열이면 split-adjusted OHLC로 사용할 수 없다.

### 4.2 분할 비율

- `split_ratio = 분할 후 주식 수 / 분할 전 주식 수`
- 4대1 액면분할은 `4`
- 1대8 역분할은 `0.125`
- 분할이 없는 날은 corporate action 행을 만들지 않거나 `1`로 명확히 정규화한다. `0`을 “분할 없음”과 실제 비율 양쪽 의미로 혼용하지 않는다.
- 분할 기준일과 적용 시점을 문서화한다.

### 4.3 배당

- 배당은 가능한 경우 ex-dividend date 기준으로 저장한다.
- 통화와 주당 금액을 저장한다.
- `raw_cash_dividend`는 당시 실제 주식 1주 기준 금액을 보존한다.
- canonical `cash_dividend`는 split-adjusted 가격과 동일한 주식 수량 기준으로 환산한 주당 금액이어야 한다.
- 특별배당과 정기배당을 구분할 수 있으면 유형도 저장한다.
- split-adjusted OHLC에는 배당을 반영하지 않는다.

### 4.4 거래량

- 원본 공급자 거래량을 보존한다.
- split-adjusted 가격과 함께 사용할 거래량의 분할조정 여부를 명시한다.
- 거래량을 조정했다면 원본 거래량도 별도로 보존한다.
- 결측 거래량을 근거 없이 `0`으로 바꾸지 않는다. 실제 0과 결측을 구분한다.

## 5. 납품 스키마

SQLite를 권장하며 아래와 동등한 정보를 제공해야 한다. 테이블명은 달라도 되지만 필드 의미를 매핑한 문서를 함께 제공한다.

### 5.1 `equity_daily_bars`

```sql
CREATE TABLE equity_daily_bars (
    symbol                 TEXT NOT NULL,
    provider_symbol        TEXT NOT NULL,
    session_date           TEXT NOT NULL,
    raw_open               TEXT NOT NULL,
    raw_high               TEXT NOT NULL,
    raw_low                TEXT NOT NULL,
    raw_close              TEXT NOT NULL,
    split_adjusted_open    TEXT NOT NULL,
    split_adjusted_high    TEXT NOT NULL,
    split_adjusted_low     TEXT NOT NULL,
    split_adjusted_close   TEXT NOT NULL,
    raw_volume             INTEGER,
    split_adjusted_volume  INTEGER,
    currency               TEXT NOT NULL,
    source                 TEXT NOT NULL,
    fetched_at             TEXT NOT NULL,
    collection_run_id      TEXT NOT NULL,
    PRIMARY KEY (symbol, session_date, source)
);
```

가격을 SQLite `REAL`로 저장해도 되지만 canonical 변환 시 자릿수를 재현할 수 있도록 공급자 정밀도와 반올림 정책을 명시해야 한다. 가능하면 decimal 문자열을 권장한다.

### 5.2 `corporate_actions`

```sql
CREATE TABLE corporate_actions (
    symbol                   TEXT NOT NULL,
    action_date              TEXT NOT NULL,
    action_type              TEXT NOT NULL,
    raw_cash_dividend        TEXT,
    cash_dividend            TEXT,
    dividend_currency        TEXT,
    split_ratio              TEXT,
    source                   TEXT NOT NULL,
    fetched_at               TEXT NOT NULL,
    collection_run_id        TEXT NOT NULL,
    PRIMARY KEY (symbol, action_date, action_type, source)
);
```

### 5.3 `market_context_daily`

```sql
CREATE TABLE market_context_daily (
    symbol             TEXT NOT NULL,
    provider_symbol    TEXT NOT NULL,
    observation_date   TEXT NOT NULL,
    open               TEXT,
    high               TEXT,
    low                TEXT,
    close              TEXT NOT NULL,
    volume             INTEGER,
    series_definition  TEXT NOT NULL,
    source             TEXT NOT NULL,
    fetched_at         TEXT NOT NULL,
    collection_run_id  TEXT NOT NULL,
    PRIMARY KEY (symbol, observation_date, source)
);
```

시장지표의 관측일을 억지로 SPY 거래일에 맞추지 않는다. Trade Flow adapter가 신호일 이전의 최신 유효 관측값을 선택한다.

### 5.4 `universe_membership`

```sql
CREATE TABLE universe_membership (
    index_name          TEXT NOT NULL,
    symbol              TEXT NOT NULL,
    valid_from          TEXT NOT NULL,
    valid_to_exclusive  TEXT,
    evidence_source     TEXT NOT NULL,
    evidence_note       TEXT,
    fetched_at          TEXT NOT NULL,
    collection_run_id   TEXT NOT NULL,
    PRIMARY KEY (index_name, symbol, valid_from)
);
```

- 대상은 우선 S&P 100급 메인 유니버스다.
- 공개 편입·제외 이력으로 근사 복원한 경우 누락 기간과 추정 규칙을 기록한다.
- `valid_to_exclusive IS NULL`은 현재도 유효함을 의미한다.
- 확인되지 않은 날짜를 임의로 생성하지 않는다.
- 완전한 공식 PIT가 아니어도 출처와 누락을 기록한 등급 B 근사 데이터면 된다.

### 5.5 `collection_runs`

```sql
CREATE TABLE collection_runs (
    collection_run_id  TEXT PRIMARY KEY,
    started_at         TEXT NOT NULL,
    completed_at       TEXT,
    source             TEXT NOT NULL,
    requested_start    TEXT NOT NULL,
    requested_end      TEXT NOT NULL,
    actual_min_date    TEXT,
    actual_max_date    TEXT,
    status             TEXT NOT NULL,
    symbol_count       INTEGER NOT NULL,
    row_count          INTEGER NOT NULL,
    failed_symbols     TEXT NOT NULL,
    error_summary      TEXT,
    dataset_sha256     TEXT
);
```

`fetched_at`, `started_at`, `completed_at`은 UTC offset이 포함된 ISO 8601 형식이어야 한다. 예: `2026-07-21T08:30:00+00:00`.

## 6. 데이터 정렬과 정밀도 정책

- 가격은 공급자 정밀도를 보존하되 모든 OHLC에 동일한 decimal scale 또는 명시된 양자화 정책을 적용한다.
- 양자화 후 반드시 `high >= max(open, low, close)` 및 `low <= min(open, high, close)`가 성립해야 한다.
- 실제 범위를 수정하는 임의 clipping은 금지한다. 부동소수점 오차만 제거하는 정규화 정책이어야 한다.
- 주식 가격은 모두 0보다 커야 한다.
- 거래량은 NULL 또는 0 이상이어야 하며 NULL과 실제 0을 구분한다.
- 시장지표에는 주식 가격의 양수 제약을 적용하지 않는다.
- 날짜와 시각은 naive datetime으로 저장하지 않는다.

## 7. 필수 검증

수집 담당자는 납품 전에 아래 검사를 실행하고 결과를 함께 전달한다.

### 7.1 구조 및 무결성

- SQLite `PRAGMA quick_check` 결과가 `ok`다.
- 모든 테이블의 PK 중복이 0건이다.
- 가격 종목이 종목 메타데이터와 모두 연결된다.
- 수집 성공으로 기록된 종목의 필수 OHLC NULL이 0건이다.
- 실패 종목은 `collection_runs.failed_symbols`에 모두 기록된다.

### 7.2 가격

- 주식/ETF 가격의 비양수 값이 0건이다.
- `high < max(open, low, close)`가 0건이다.
- `low > min(open, high, close)`가 0건이다.
- 음수 거래량이 0건이다.
- 종목별 최소일, 최대일, 행 수를 출력한다.
- 최근 20개 미국 거래소 세션의 누락을 종목별로 출력한다.
- 알려진 분할 종목을 최소 3개 선정해 분할 전후 raw 가격, split-adjusted 가격, split ratio가 일관되는지 수동 검증한다.
- 알려진 배당 종목을 최소 3개 선정해 split-adjusted 가격에 배당조정이 들어가지 않았고 배당 현금흐름이 정확히 한 번만 계산되는지 검증한다.

### 7.3 시장지표

- VIX, WTI, 13주 단기금리의 최소일, 최대일, 행 수를 출력한다.
- WTI와 금리의 0·음수 관측값을 삭제하지 않고 별도 목록으로 출력한다.
- 각 지표와 SPY의 관측일 차이를 출력한다.
- 최신 주식 신호일 기준으로 사용할 수 있는 직전 관측값이 존재하는지 확인한다.

### 7.4 유니버스

- 기준일별 활성 종목에 유효기간 중복이 없어야 한다.
- 동일 종목의 편입·제외 구간이 역전되거나 겹치면 안 된다.
- 현재 스냅샷과 이력으로 복원한 현재 구성의 차이를 출력한다.
- 출처가 없는 편입·제외 행이 0건이어야 한다.
- 확인하지 못한 기간과 종목을 별도 보고한다.

## 8. 납품물

다음 파일을 한 세트로 전달한다.

1. 새 SQLite DB 파일. 기존 DB와 다른 이름을 사용한다.
2. 스키마 SQL 또는 테이블·컬럼 매핑 문서.
3. 수집 실행 manifest. 공급자, 기간, 성공·실패 종목, 행 수, 수집시각을 포함한다.
4. 데이터 검증 결과. Section 7의 모든 항목을 포함한다.
5. 데이터셋 SHA-256 체크섬.
6. 사용한 수집 코드의 commit hash 또는 고정된 버전 식별자.
7. 공급자 데이터의 조정 방식, WTI 연결 방식, 거래량 처리 방식 설명.

권장 파일명 예시는 다음과 같다.

```text
tradeflow_us_raw_v1.db
tradeflow_us_raw_v1_manifest.json
tradeflow_us_raw_v1_validation.md
tradeflow_us_raw_v1.sha256
```

## 9. 승인 조건

다음을 모두 만족하면 Trade Flow adapter 구현 단계로 넘긴다.

- 2015-01-02부터 최신 완료 거래일까지의 필수 종목 가격이 존재한다.
- raw OHLC와 split-adjusted OHLC가 분리되어 있다.
- split-adjusted OHLC에 배당조정이 포함되지 않는다.
- 배당 현금흐름의 주식 수량 기준이 split-adjusted 가격과 일치한다.
- 출처, provider symbol, 수집시각, run ID가 보존된다.
- 최근 20거래일 필수 종목 누락이 없다.
- 가격 중복, 실질적인 OHLC 역전, 음수 거래량이 없다.
- VIX와 WTI가 존재하고 지표 정의가 기록되어 있다.
- PIT 유니버스 이력의 출처와 누락 범위가 기록되어 있다.
- 검증 결과와 데이터셋 체크섬이 함께 전달된다.

## 10. 반려 조건

다음 중 하나라도 해당하면 승인용 데이터로 받지 않는다.

- 배당조정 가격과 배당 현금흐름을 동시에 제공하면서 이중 반영 방지 설명이 없다.
- raw와 split-adjusted 가격을 같은 값으로 복사했지만 그 근거가 없다.
- 공급자 또는 수집시각이 없다.
- 누락된 종목을 성공으로 처리했다.
- 최신 완료 거래일이 빠졌는데 최신 상태로 표시했다.
- 현재 종목 목록을 근거 없이 전체 과거 유니버스로 표시했다.
- WTI 연속선물 구성 방식을 설명하지 않았다.
- 기존 `tradeflow_us.db`를 덮어썼다.
