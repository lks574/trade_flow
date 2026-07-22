# tradeflow_us_raw_v1 검증 결과 (명세 Section 7)

## 7.1 구조 및 무결성
- PRAGMA quick_check: `ok`
- equity_daily_bars: 226356행, PK 중복 0건
- corporate_actions: 3172행, PK 중복 0건
- market_context_daily: 8706행, PK 중복 0건
- universe_membership: 101행, PK 중복 0건
- 필수 OHLC NULL: 0건
- 실패 종목(collection_runs): {}

## 7.2 가격
- 비양수 raw_open: 0건
- 비양수 raw_close: 0건
- 비양수 split_adjusted_open: 0건
- 비양수 split_adjusted_close: 0건
- split-adjusted high < max(o,l,c): 0건
- split-adjusted low > min(o,h,c): 0건
- 음수 거래량: 0건
- 종목수 78, 전체 기간 2015-01-02 ~ 2026-07-20
- 최근 20 세션(SPY 기준) 누락 종목: 없음
- 분할 수동 검증(raw는 분할 전후 비율=split_ratio, split-adjusted는 연속):
  - AAPL 2020-08-31: 저장 split_ratio=4.0, raw 전/후 비=3.87(기대 4.0), split-adj 연속성 오차=3.3%
  - NVDA 2024-06-10: 저장 split_ratio=10.0, raw 전/후 비=9.93(기대 10.0), split-adj 연속성 오차=0.7%
  - AMZN 2022-06-06: 저장 split_ratio=20.0, raw 전/후 비=19.61(기대 20.0), split-adj 연속성 오차=2.0%
- 배당 검증(배당조정 미포함 + 배당 스케일이 가격 스케일과 일치):
  - AAPL 2026-05-11: raw배당=0.27, canonical=0.27, 배당계수=1.00 vs 가격계수=1.00 (일치해야 정상)
  - AAPL 2026-02-09: raw배당=0.26, canonical=0.26, 배당계수=1.00 vs 가격계수=1.00 (일치해야 정상)
  - AAPL 2025-11-10: raw배당=0.26, canonical=0.26, 배당계수=1.00 vs 가격계수=1.00 (일치해야 정상)

## 7.3 시장지표
- VIX: 2903행, 2015-01-02 ~ 2026-07-20
- WTI: 2902행, 2015-01-02 ~ 2026-07-20
- TBILL_13W: 2901행, 2015-01-02 ~ 2026-07-20
- WTI 0/음수 관측(삭제 안 함): 1건 예: [('2020-04-20', '-37.630001')]
- TBILL_13W 0/음수 관측(삭제 안 함): 7건 예: [('2020-03-19', '-0.028000'), ('2020-03-20', '-0.033000'), ('2020-03-23', '-0.040000')]
- VIX: SPY에만 있는 날 0, VIX에만 있는 날 1
- WTI: SPY에만 있는 날 2, WTI에만 있는 날 2
- TBILL_13W: SPY에만 있는 날 1, TBILL_13W에만 있는 날 0

## 7.4 유니버스
- universe_membership 101행, 출처 없는 행 0건
- 등급: GRADE-C (현재 S&P100 스냅샷만, 과거 편입/제외 이력 미확보). valid_from=수집일, valid_to_exclusive=NULL(현재 유효). 과거 PIT 이력은 미확보 구간으로 보고.

## 요약 / 한계
- raw OHLC와 split-adjusted OHLC 분리 저장, split-adjusted에 배당 미반영(§4.1 준수).
- 배당 raw/canonical 분리, 스케일이 가격 스케일과 일치(이중계산 방지).
- GRADE-B: WTI=Yahoo CL=F 근월 연속물(롤 규칙 비공개, 무조정, 음수 보존). GRADE-C: S&P100 PIT 이력 미확보(현재 스냅샷만).
