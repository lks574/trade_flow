# 데이터 수집 구조

> 백테스트용 일봉 데이터를 3개 외부 소스에서 가져와 SQLite DB에 적재하는 방식. 이 방식을 메인으로 사용한다.

## 전체 구조

```
외부 소스 → collector(fetch) → storage/db.py(upsert) → SQLite → 전략/백테스트/리포트
```

- 모든 소스가 동일한 `daily_price` 스키마(`storage/db.py:5`)로 저장 → 백테스트·전략·리포트는 DB만 읽음.
- 모든 write는 `db.upsert_prices` 등 `ON CONFLICT DO UPDATE`로 멱등 → 재실행해도 안전.

## 1. 한국 주식 — 실운영 (pykrx)

- **소스**: pykrx → KRX(한국거래소) 공식 데이터
- **흐름**: `scripts/collect.py` → `collector/update.py:run()` → `collector/krx.py`
- `krx.fetch_day(d)` (`krx.py:35`): 하루치를 KOSPI·KOSDAQ 각각
  - `stock.get_market_ohlcv(ymd, market=...)` — 시/고/저/종가·거래량·거래대금
  - `stock.get_market_cap(ymd, market=...)` — 시가총액
  - `with_retry`로 3회 재시도 + `DELAY_SEC=1.0` 지연 (KRX 레이트리밋 회피)
- `update.run()` (`update.py:71`) 오케스트레이션:
  - `missing_dates()`로 마지막 적재일+1 ~ 오늘의 평일만 계산 → 증분 수집
  - `--backfill`이면 `backfill_years`(기본 10년) 전체 적재
  - `detect_jumps()` + `_fix_corporate_action()`: 종가 전일 대비 50%↑ 점프 시 액면분할/배당 의심 → `fetch_ticker_history(adjusted=True)`로 수정주가 전체 이력 재적재
  - `count_gate()`: 종목 수가 최근 평균의 80% 미만이면 "suspect" 경고
- **자동 실행**: launchd, 평일 16:30 (`collect.py:1` 주석)

## 2. 한국 주식 — 실험용 임시 (yfinance)

- **소스**: yfinance → Yahoo Finance
- **흐름**: `scripts/collect_kr_yf.py` → `data/kr.db`
- **존재 이유**: pykrx가 KRX 로그인 필수로 바뀔 때 임시 대체 (`collect_kr_yf.py:3` 주석)
- 대형주 ~120종목 하드코딩, `005930.KS` 형식으로 조회
- **한계**: 현재 상장주만 → 생존편향, `marcap=0` 저장 (백테스트 시 `MIN_MARCAP=0` 필요)

## 3. 미국 주식 (yfinance + 위키피디아)

- **흐름**: `scripts/collect_us.py` → `collector/us.py` → `data/tradeflow_us.db` (별도 DB)
- **유니버스** (`refresh_us_universe.py`): 위키피디아 S&P500/100 페이지를 httpx로 받아 `pd.read_html` 파싱 → `data/us_universe.txt`. 편입/편출 이력도 best-effort로 `index_membership` 테이블에
- **가격/배당/분할** (`us.py:61 fetch_prices`): `yf.download` 수정주가 OHLCV + `yf.Ticker(t).actions`로 배당·분할
- **시장 컨텍스트** (`us.py:86 fetch_context`): SPY, QQQ, ^VIX, CL=F, ^IRX → `market_context` 테이블
  - `_sub()` (`us.py:48`): VIX·금리는 volume이 항상 NaN → 종가 기준으로만 dropna (전 행 삭제 방지)

## 진입점

```bash
python scripts/collect.py [--backfill]        # 한국(운영)
python scripts/refresh_us_universe.py         # 미국 유니버스 갱신 (collect_us 전)
python scripts/collect_us.py [--backfill]     # 미국
python scripts/collect_kr_yf.py               # 한국 실험
```

## 요약표

| 항목 | KR(운영) | KR(실험) | US |
|---|---|---|---|
| 소스 | pykrx→KRX | yfinance | yfinance + 위키피디아 |
| DB | `data/tradeflow.db` | `data/kr.db` | `data/tradeflow_us.db` |
| 수정주가 | 점프 감지 시 사후 보정 | download 시 auto_adjust | download 시 auto_adjust |
| 유니버스 | 전 종목 자동 등장 | 하드코딩 120개 | 위키피디아 파싱 |
