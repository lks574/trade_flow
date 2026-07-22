# 데이터 수집

백테스트용 데이터를 외부 소스(yfinance, 위키피디아)에서 가져와 SQLite DB에 적재한다.

## 설계 원칙

- **코어는 dependency-free**: `src/trade_flow`는 stdlib만 사용(재현성). 수집기는 `[collect]` optional-deps(yfinance, lxml)로 분리하고 `scripts/`에서 lazy import 한다.
- **멱등**: 모든 write는 `ON CONFLICT ... DO UPDATE` → 재실행 안전.
- **원본 + 분할조정 분리**: `prices`에 원본 OHLC와 split-adjusted OHLC를 함께 저장. 배당은 `cash_dividend`로 따로 두어 포트폴리오 현금흐름에 한 번만 반영(스펙 3.2). 분할조정 divisor는 `data/adjust.py:split_adjustment_divisors`(순수 함수, 테스트됨).

## 무엇을 쌓나

| 대상 | 테이블 | 소스 | 기간 |
|---|---|---|---|
| 미국주식 일봉 | `prices` | yfinance | 최소 10년 (종목당 ≥201거래일, 최근 20거래일 결측 0) |
| 레짐(VIX·WTI) 종가 | `market_context` | yfinance (`^VIX`, `CL=F`) | 가능한 최대(목표 30년) |
| 감정점수 | `sentiment` | Alpha Vantage | **Phase 2 — 아직 안 함** |

- 유니버스: 위키피디아 S&P500 현재 구성종목 → grade C(생존편향 있는 부트스트랩). PIT 유니버스(grade A/B)는 별도·후순위.
- `market_context`는 종가만 저장(`RegimeInput`이 close만 필요 → OHLCV는 dead column).

## 실행

```bash
pip install -e '.[collect]'

# 1. 유니버스 채우기: 위키피디아 S&P500 → configs/universe_main.toml
python scripts/refresh_universe.py

# 2. 일봉 + VIX/WTI 수집 → data/trade_flow.db
python scripts/collect.py                 # prices 10년 + regime max
python scripts/collect.py --years 15      # 기간 조절
python scripts/collect.py --skip-prices   # 레짐만
```

- `provider_symbol`은 yfinance 형식(예: `BRK.B` → `BRK-B`). `refresh_universe.py`가 자동 변환.
- `collect.py`는 백필용 `PriceRepository.save_bars`(품질 게이트 없는 원시 writer)를 사용. 신호일 품질 검증(`build_market_data_snapshot`)은 read-time에 캘린더와 함께 수행.

## 코드 위치

- 스키마: `src/trade_flow/db/schema.py` (`prices`, `market_context`, ...)
- 리포지토리: `db/prices.py`(`PriceRepository`), `db/market_context.py`(`MarketContextRepository` → `RegimeInput`)
- 분할조정: `src/trade_flow/data/adjust.py`
- 수집 스크립트: `scripts/refresh_universe.py`, `scripts/collect.py`
