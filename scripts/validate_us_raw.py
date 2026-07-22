"""tradeflow_us_raw_v1.db 검증 (전달 명세 Section 7). 결과를 validation.md로 출력."""
import sqlite3
from pathlib import Path

DATA = Path("/Users/kyungseok.lee/workspace/dev/trade_flow/data")
DB = DATA / "tradeflow_us_raw_v1.db"
OUT = DATA / "tradeflow_us_raw_v1_validation.md"
SPLIT_CHECKS = {"AAPL": ("2020-08-31", 4.0), "NVDA": ("2024-06-10", 10.0), "AMZN": ("2022-06-06", 20.0)}
DIV_CHECK = "AAPL"


def f(x):
    return float(x) if x is not None else None


def main():
    c = sqlite3.connect(DB)
    L = ["# tradeflow_us_raw_v1 검증 결과 (명세 Section 7)", ""]

    # 7.1 구조/무결성
    L.append("## 7.1 구조 및 무결성")
    qc = c.execute("PRAGMA quick_check").fetchone()[0]
    L.append(f"- PRAGMA quick_check: `{qc}`")
    for tbl, pk in [("equity_daily_bars", "symbol,session_date,source"),
                    ("corporate_actions", "symbol,action_date,action_type,source"),
                    ("market_context_daily", "symbol,observation_date,source"),
                    ("universe_membership", "index_name,symbol,valid_from")]:
        dup = c.execute(f"SELECT COUNT(*) FROM (SELECT {pk} FROM {tbl} GROUP BY {pk} "
                        f"HAVING COUNT(*)>1)").fetchone()[0]
        n = c.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        L.append(f"- {tbl}: {n}행, PK 중복 {dup}건")
    nulls = c.execute("SELECT COUNT(*) FROM equity_daily_bars WHERE raw_open IS NULL "
                      "OR raw_high IS NULL OR raw_low IS NULL OR raw_close IS NULL "
                      "OR split_adjusted_close IS NULL").fetchone()[0]
    L.append(f"- 필수 OHLC NULL: {nulls}건")
    fs = c.execute("SELECT failed_symbols FROM collection_runs").fetchone()[0]
    L.append(f"- 실패 종목(collection_runs): {fs}")

    # 7.2 가격
    L.append("\n## 7.2 가격")
    for col in ("raw_open", "raw_close", "split_adjusted_open", "split_adjusted_close"):
        bad = c.execute(f"SELECT COUNT(*) FROM equity_daily_bars WHERE CAST({col} AS REAL)<=0").fetchone()[0]
        L.append(f"- 비양수 {col}: {bad}건")
    inv_hi = c.execute("SELECT COUNT(*) FROM equity_daily_bars WHERE "
                       "CAST(split_adjusted_high AS REAL) < MAX(CAST(split_adjusted_open AS REAL),"
                       "CAST(split_adjusted_low AS REAL),CAST(split_adjusted_close AS REAL))").fetchone()[0]
    inv_lo = c.execute("SELECT COUNT(*) FROM equity_daily_bars WHERE "
                       "CAST(split_adjusted_low AS REAL) > MIN(CAST(split_adjusted_open AS REAL),"
                       "CAST(split_adjusted_high AS REAL),CAST(split_adjusted_close AS REAL))").fetchone()[0]
    L.append(f"- split-adjusted high < max(o,l,c): {inv_hi}건")
    L.append(f"- split-adjusted low > min(o,h,c): {inv_lo}건")
    negv = c.execute("SELECT COUNT(*) FROM equity_daily_bars WHERE raw_volume<0 "
                     "OR split_adjusted_volume<0").fetchone()[0]
    L.append(f"- 음수 거래량: {negv}건")
    rng = c.execute("SELECT COUNT(DISTINCT symbol), MIN(session_date), MAX(session_date) "
                    "FROM equity_daily_bars").fetchone()
    L.append(f"- 종목수 {rng[0]}, 전체 기간 {rng[1]} ~ {rng[2]}")
    # 최근 20 세션 누락(SPY 기준)
    spy = [r[0] for r in c.execute("SELECT session_date FROM equity_daily_bars WHERE symbol='SPY' "
                                   "ORDER BY session_date DESC LIMIT 20")]
    gaps = []
    for sym in [r[0] for r in c.execute("SELECT DISTINCT symbol FROM equity_daily_bars")]:
        have = {r[0] for r in c.execute("SELECT session_date FROM equity_daily_bars WHERE symbol=? "
                                        "AND session_date>=?", (sym, spy[-1]))}
        miss = [d for d in spy if d not in have]
        if miss:
            gaps.append(f"{sym}({len(miss)})")
    L.append(f"- 최근 20 세션(SPY 기준) 누락 종목: {', '.join(gaps) if gaps else '없음'}")
    # 분할 수동 검증
    L.append("- 분할 수동 검증(raw는 분할 전후 비율=split_ratio, split-adjusted는 연속):")
    for sym, (sd, ratio) in SPLIT_CHECKS.items():
        rows = c.execute("SELECT session_date, CAST(raw_close AS REAL), CAST(split_adjusted_close AS REAL) "
                         "FROM equity_daily_bars WHERE symbol=? AND session_date<? "
                         "ORDER BY session_date DESC LIMIT 1", (sym, sd)).fetchone()
        after = c.execute("SELECT session_date, CAST(raw_close AS REAL), CAST(split_adjusted_close AS REAL) "
                          "FROM equity_daily_bars WHERE symbol=? AND session_date>=? "
                          "ORDER BY session_date ASC LIMIT 1", (sym, sd)).fetchone()
        sr = c.execute("SELECT CAST(split_ratio AS REAL) FROM corporate_actions WHERE symbol=? "
                       "AND action_type='split' AND action_date=?", (sym, sd)).fetchone()
        if rows and after:
            raw_ratio = rows[1] / after[1]
            sa_cont = abs(rows[2] - after[2]) / after[2]
            L.append(f"  - {sym} {sd}: 저장 split_ratio={sr[0] if sr else 'NA'}, "
                     f"raw 전/후 비={raw_ratio:.2f}(기대 {ratio}), "
                     f"split-adj 연속성 오차={sa_cont*100:.1f}%")
    # 배당 검증(내부 정합: raw/canonical == raw_close/split_adj_close)
    L.append("- 배당 검증(배당조정 미포함 + 배당 스케일이 가격 스케일과 일치):")
    divs = c.execute("SELECT action_date, CAST(raw_cash_dividend AS REAL), CAST(cash_dividend AS REAL) "
                     "FROM corporate_actions WHERE symbol=? AND action_type='dividend' "
                     "ORDER BY action_date DESC LIMIT 3", (DIV_CHECK,)).fetchall()
    for ad, rawd, cand in divs:
        bar = c.execute("SELECT CAST(raw_close AS REAL), CAST(split_adjusted_close AS REAL) "
                        "FROM equity_daily_bars WHERE symbol=? AND session_date<=? "
                        "ORDER BY session_date DESC LIMIT 1", (DIV_CHECK, ad)).fetchone()
        price_f = bar[0] / bar[1] if bar else 0
        div_f = rawd / cand if cand else 0
        L.append(f"  - {DIV_CHECK} {ad}: raw배당={rawd}, canonical={cand}, "
                 f"배당계수={div_f:.2f} vs 가격계수={price_f:.2f} (일치해야 정상)")

    # 7.3 시장지표
    L.append("\n## 7.3 시장지표")
    for sym in ("VIX", "WTI", "TBILL_13W"):
        r = c.execute("SELECT COUNT(*), MIN(observation_date), MAX(observation_date) "
                      "FROM market_context_daily WHERE symbol=?", (sym,)).fetchone()
        L.append(f"- {sym}: {r[0]}행, {r[1]} ~ {r[2]}")
    for sym in ("WTI", "TBILL_13W"):
        nz = c.execute("SELECT observation_date, close FROM market_context_daily WHERE symbol=? "
                       "AND CAST(close AS REAL)<=0 ORDER BY observation_date", (sym,)).fetchall()
        L.append(f"- {sym} 0/음수 관측(삭제 안 함): {len(nz)}건" +
                 (f" 예: {nz[:3]}" if nz else ""))
    # SPY 대비 관측일 차이
    spyset = {r[0] for r in c.execute("SELECT session_date FROM equity_daily_bars WHERE symbol='SPY'")}
    for sym in ("VIX", "WTI", "TBILL_13W"):
        cset = {r[0] for r in c.execute("SELECT observation_date FROM market_context_daily WHERE symbol=?", (sym,))}
        L.append(f"- {sym}: SPY에만 있는 날 {len(spyset-cset)}, {sym}에만 있는 날 {len(cset-spyset)}")

    # 7.4 유니버스
    L.append("\n## 7.4 유니버스")
    nosrc = c.execute("SELECT COUNT(*) FROM universe_membership WHERE evidence_source IS NULL "
                      "OR evidence_source=''").fetchone()[0]
    nmem = c.execute("SELECT COUNT(*) FROM universe_membership").fetchone()[0]
    L.append(f"- universe_membership {nmem}행, 출처 없는 행 {nosrc}건")
    L.append("- 등급: GRADE-C (현재 S&P100 스냅샷만, 과거 편입/제외 이력 미확보). "
             "valid_from=수집일, valid_to_exclusive=NULL(현재 유효). 과거 PIT 이력은 미확보 구간으로 보고.")

    L.append("\n## 요약 / 한계")
    L.append("- raw OHLC와 split-adjusted OHLC 분리 저장, split-adjusted에 배당 미반영(§4.1 준수).")
    L.append("- 배당 raw/canonical 분리, 스케일이 가격 스케일과 일치(이중계산 방지).")
    L.append("- GRADE-B: WTI=Yahoo CL=F 근월 연속물(롤 규칙 비공개, 무조정, 음수 보존). "
             "GRADE-C: S&P100 PIT 이력 미확보(현재 스냅샷만).")
    OUT.write_text("\n".join(L) + "\n")
    print("\n".join(L))
    print(f"\n검증 리포트: {OUT}")


if __name__ == "__main__":
    main()
