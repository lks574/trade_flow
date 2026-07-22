"""US 시장 데이터 수집 (전달 명세 2026-07-21 준수).
raw OHLC + split-adjusted OHLC 분리, 배당 raw/canonical 분리, provenance 보존.
산출: tradeflow_us_raw_v1.db + _manifest.json + _validation.md + .sha256
공급자: yfinance. 기존 TradeFlow/data/tradeflow_us.db는 절대 건드리지 않음.
"""
import hashlib
import json
import sqlite3
import sys
import uuid
import warnings
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from zoneinfo import ZoneInfo

warnings.filterwarnings("ignore")
import pandas as pd
import yfinance as yf

OUT = Path("/Users/kyungseok.lee/workspace/dev/trade_flow/data")
STEM = "tradeflow_us_raw_v1"
DB = OUT / f"{STEM}.db"
SOURCE = "yfinance"
START = "2015-01-02"
SCALE = Decimal("0.000001")  # 6자리 양자화

STOCKS = ("AAPL ABBV ABT ADBE ADI AMAT AMD AMGN AMZN AVGO AXP BA BAC BLK BMY C CAT CMCSA COP COST "
          "CRM CSCO CVX DE DHR DIS GE GILD GOOGL GS HD HON IBM INTC INTU ISRG JNJ JPM KO LLY "
          "LMT LOW LRCX MA MCD META MMM MRK MS MSFT MU NFLX NKE NOW NVDA ORCL PEP PFE PG QCOM "
          "RTX SBUX SCHW SLB T TGT TJX TMO TXN UNH UNP V VZ WFC WMT XOM").split()
ETFS = ["SPY", "QQQ"]
CONTEXT = {  # canonical -> (provider, series_definition)
    "VIX": ("^VIX", "CBOE Volatility Index (spot index, no volume)"),
    "WTI": ("CL=F", "Yahoo Finance CL=F front-month WTI continuous. Roll/adjustment: "
                    "Yahoo proprietary front-month stitch, roll rule undocumented, no explicit "
                    "back-adjustment applied, negative prices preserved. GRADE-B for long regime use."),
    "TBILL_13W": ("^IRX", "US 13-week T-bill discount rate (^IRX), percent, may be near zero"),
}

SCHEMA = """
CREATE TABLE equity_daily_bars (
  symbol TEXT NOT NULL, provider_symbol TEXT NOT NULL, session_date TEXT NOT NULL,
  raw_open TEXT NOT NULL, raw_high TEXT NOT NULL, raw_low TEXT NOT NULL, raw_close TEXT NOT NULL,
  split_adjusted_open TEXT NOT NULL, split_adjusted_high TEXT NOT NULL,
  split_adjusted_low TEXT NOT NULL, split_adjusted_close TEXT NOT NULL,
  raw_volume INTEGER, split_adjusted_volume INTEGER,
  currency TEXT NOT NULL, source TEXT NOT NULL, fetched_at TEXT NOT NULL,
  collection_run_id TEXT NOT NULL,
  PRIMARY KEY (symbol, session_date, source));
CREATE TABLE corporate_actions (
  symbol TEXT NOT NULL, action_date TEXT NOT NULL, action_type TEXT NOT NULL,
  raw_cash_dividend TEXT, cash_dividend TEXT, dividend_currency TEXT, split_ratio TEXT,
  source TEXT NOT NULL, fetched_at TEXT NOT NULL, collection_run_id TEXT NOT NULL,
  PRIMARY KEY (symbol, action_date, action_type, source));
CREATE TABLE market_context_daily (
  symbol TEXT NOT NULL, provider_symbol TEXT NOT NULL, observation_date TEXT NOT NULL,
  open TEXT, high TEXT, low TEXT, close TEXT NOT NULL, volume INTEGER,
  series_definition TEXT NOT NULL, source TEXT NOT NULL, fetched_at TEXT NOT NULL,
  collection_run_id TEXT NOT NULL,
  PRIMARY KEY (symbol, observation_date, source));
CREATE TABLE universe_membership (
  index_name TEXT NOT NULL, symbol TEXT NOT NULL, valid_from TEXT NOT NULL,
  valid_to_exclusive TEXT, evidence_source TEXT NOT NULL, evidence_note TEXT,
  fetched_at TEXT NOT NULL, collection_run_id TEXT NOT NULL,
  PRIMARY KEY (index_name, symbol, valid_from));
CREATE TABLE collection_runs (
  collection_run_id TEXT PRIMARY KEY, started_at TEXT NOT NULL, completed_at TEXT,
  source TEXT NOT NULL, requested_start TEXT NOT NULL, requested_end TEXT NOT NULL,
  actual_min_date TEXT, actual_max_date TEXT, status TEXT NOT NULL,
  symbol_count INTEGER NOT NULL, row_count INTEGER NOT NULL,
  failed_symbols TEXT NOT NULL, error_summary TEXT, dataset_sha256 TEXT);
"""


def q(x):
    return str(Decimal(str(x)).quantize(SCALE, rounding=ROUND_HALF_UP))


def cum_future_split(dates, splits):
    """각 날짜별 '그 날짜 이후'에 발생한 분할비율의 누적곱."""
    ev = [(d, float(r)) for d, r in splits.items() if float(r) > 0]
    out = {}
    for d in dates:
        f = 1.0
        for sd, r in ev:
            if sd.date() > d:
                f *= r
        out[d] = f
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    if DB.exists():
        print(f"이미 존재: {DB} — 덮어쓰지 않음. 다른 이름 사용 또는 수동 삭제 필요", file=sys.stderr)
        return 1
    run_id = "run_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8]
    started = datetime.now(timezone.utc).isoformat()
    ny_today = datetime.now(ZoneInfo("America/New_York")).date()
    req_end = ny_today.isoformat()  # 요청 종료(오늘 NY). 실제 저장 MAX로 검증

    conn = sqlite3.connect(DB)
    conn.executescript(SCHEMA)
    fetched = datetime.now(timezone.utc).isoformat()
    failed = {}

    def fetched_now():
        return datetime.now(timezone.utc).isoformat()

    # ---- 주식/ETF ----
    bar_rows, act_rows = [], []
    equities = STOCKS + ETFS
    for i, sym in enumerate(equities, 1):
        try:
            df = yf.download(sym, start=START, end=req_end, auto_adjust=False,
                             progress=False, actions=False)
            if isinstance(df.columns, pd.MultiIndex):
                df = df.xs(sym, axis=1, level=1)
            df = df.dropna(subset=["Open", "High", "Low", "Close"])
            if df.empty:
                failed[sym] = "empty price"
                continue
            tk = yf.Ticker(sym)
            splits = tk.splits
            divs = tk.dividends
            fac = cum_future_split([d.date() for d in df.index], splits)
            fa = fetched_now()
            for ts, r in df.iterrows():
                d = ts.date()
                f = fac[d]
                so, sh, sl, sc = float(r["Open"]), float(r["High"]), float(r["Low"]), float(r["Close"])
                vol = int(r["Volume"]) if pd.notna(r["Volume"]) else None
                bar_rows.append((
                    sym, sym, d.isoformat(),
                    q(so * f), q(sh * f), q(sl * f), q(sc * f),   # raw = split-adj * 미래분할계수
                    q(so), q(sh), q(sl), q(sc),                   # split-adjusted (yfinance)
                    vol,                                          # raw volume (as-reported)
                    int(round(vol * f)) if vol is not None else None,  # split-adjusted volume
                    "USD", SOURCE, fa, run_id))
            # 분할 이벤트
            for sd, rr in splits.items():
                if float(rr) > 0 and sd.date() >= df.index[0].date():
                    act_rows.append((sym, sd.date().isoformat(), "split", None, None, None,
                                     q(rr), SOURCE, fa, run_id))
            # 배당: yfinance=split-adjusted(canonical). raw = *미래분할계수
            for dd, vv in divs.items():
                d = dd.date()
                if d < df.index[0].date():
                    continue
                f = fac.get(d, 1.0)
                canonical = float(vv)
                act_rows.append((sym, d.isoformat(), "dividend",
                                 q(canonical * f), q(canonical), "USD", None,
                                 SOURCE, fa, run_id))
        except Exception as e:
            failed[sym] = str(e)[:100]
        if i % 20 == 0:
            print(f"  ...equity {i}/{len(equities)}")
    conn.executemany(f"INSERT OR REPLACE INTO equity_daily_bars VALUES ({','.join(['?']*17)})", bar_rows)
    conn.executemany(f"INSERT OR REPLACE INTO corporate_actions VALUES ({','.join(['?']*10)})", act_rows)
    print(f"주식/ETF: {len(equities)-len(failed)}종목 {len(bar_rows)}행, corp actions {len(act_rows)}")

    # ---- 시장 컨텍스트 ----
    ctx_rows = []
    for canon, (prov, desc) in CONTEXT.items():
        try:
            df = yf.download(prov, start=START, end=req_end, auto_adjust=False, progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df = df.xs(prov, axis=1, level=1)
            df = df.dropna(subset=["Close"])
            fa = fetched_now()
            for ts, r in df.iterrows():
                v = r.get("Volume")
                ctx_rows.append((canon, prov, ts.date().isoformat(),
                                 q(r["Open"]) if pd.notna(r.get("Open")) else None,
                                 q(r["High"]) if pd.notna(r.get("High")) else None,
                                 q(r["Low"]) if pd.notna(r.get("Low")) else None,
                                 q(r["Close"]),
                                 int(v) if pd.notna(v) and v > 0 else None,
                                 desc, SOURCE, fa, run_id))
        except Exception as e:
            failed[canon] = str(e)[:100]
    conn.executemany(f"INSERT OR REPLACE INTO market_context_daily VALUES ({','.join(['?']*12)})", ctx_rows)
    print(f"컨텍스트: {len(ctx_rows)}행")

    # ---- 유니버스(grade-B: S&P100 현재 스냅샷 + 출처 기록) ----
    mem_rows = []
    try:
        import httpx
        html = httpx.get("https://en.wikipedia.org/wiki/S%26P_100",
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=30,
                         follow_redirects=True).text
        for tbl in pd.read_html(html):
            if "Symbol" in tbl.columns:
                fa = fetched_now()
                for s in tbl["Symbol"].tolist():
                    mem_rows.append(("SP100", str(s).replace(".", "-").strip(),
                                     ny_today.isoformat(), None,
                                     "wikipedia S&P 100 current snapshot",
                                     "GRADE-C: current snapshot only; historical entry dates not established",
                                     fa, run_id))
                break
    except Exception as e:
        failed["SP100_universe"] = str(e)[:100]
    conn.executemany(f"INSERT OR REPLACE INTO universe_membership VALUES ({','.join(['?']*8)})", mem_rows)
    print(f"유니버스: {len(mem_rows)}행 (grade-C 현재 스냅샷)")

    # ---- collection_runs ----
    amin = conn.execute("SELECT MIN(session_date) FROM equity_daily_bars").fetchone()[0]
    amax = conn.execute("SELECT MAX(session_date) FROM equity_daily_bars").fetchone()[0]
    total = len(bar_rows) + len(act_rows) + len(ctx_rows) + len(mem_rows)
    status = "ok" if not failed else "ok_with_failures"
    conn.execute("INSERT INTO collection_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 (run_id, started, datetime.now(timezone.utc).isoformat(), SOURCE, START, req_end,
                  amin, amax, status, len(equities) + len(CONTEXT), total,
                  json.dumps(failed, ensure_ascii=False), None, None))
    conn.commit()

    # ---- SHA256 + manifest ----
    conn.close()
    sha = hashlib.sha256(DB.read_bytes()).hexdigest()
    conn = sqlite3.connect(DB)
    conn.execute("UPDATE collection_runs SET dataset_sha256=? WHERE collection_run_id=?", (sha, run_id))
    conn.commit()
    conn.close()
    (OUT / f"{STEM}.sha256").write_text(f"{sha}  {STEM}.db\n")
    manifest = {
        "collection_run_id": run_id, "source": SOURCE, "started_at": started,
        "requested_start": START, "requested_end": req_end,
        "actual_min_date": amin, "actual_max_date": amax,
        "equity_symbols": equities, "context": {k: v[0] for k, v in CONTEXT.items()},
        "row_counts": {"equity_daily_bars": len(bar_rows), "corporate_actions": len(act_rows),
                       "market_context_daily": len(ctx_rows), "universe_membership": len(mem_rows)},
        "failed_symbols": failed, "dataset_sha256": sha,
        "adjustment_notes": {
            "split_adjusted_ohlc": "yfinance auto_adjust=False Open/High/Low/Close (split-adjusted, no dividend)",
            "raw_ohlc": "split_adjusted * cumulative future split factor (reconstructed as-traded)",
            "raw_volume": "yfinance as-reported volume", "split_adjusted_volume": "raw_volume * cum future split factor",
            "cash_dividend": "yfinance dividends (split-adjusted, canonical)",
            "raw_cash_dividend": "cash_dividend * cum future split factor",
            "wti": CONTEXT["WTI"][1], "universe": "GRADE-C current snapshot only"},
    }
    (OUT / f"{STEM}_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    print(f"\n완료: {DB}\nSHA256: {sha}\n기간: {amin} ~ {amax}, 실패: {failed or '없음'}")


if __name__ == "__main__":
    sys.exit(main())
