"""KIS 모의투자 연결 smoke test (읽기전용).

환경변수(KIS_APP_KEY/KIS_APP_SECRET/KIS_ACCOUNT[/KIS_ACCOUNT_PRODUCT][/KIS_ENV])를
설정한 뒤 실행한다. 토큰 발급 + 잔고 + 시세(AAPL)를 조회해 원시 응답을 출력한다.
잔고 응답의 실제 필드명을 확인해 AccountSnapshot 매핑(2b)을 확정하기 위한 것이다.

사용:
  KIS_ENV=mock 로 모의 서버에 붙는다(기본). 실키 노출 금지 — 셸에서만 export.
  python scripts/kis_smoke.py [--symbol AAPL] [--exchange NASDAQ]
"""

from __future__ import annotations

import argparse
import json
import sys

from trade_flow.broker import KisConfigError, build_client


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default="AAPL")
    parser.add_argument("--exchange", default="NASDAQ")
    args = parser.parse_args(argv)

    try:
        client = build_client()
    except KisConfigError as error:
        print(f"[설정오류] {error}", file=sys.stderr)
        return 2

    env = client._cred.environment  # noqa: SLF001 - smoke test 편의
    print(f"환경: {env}  base={client._cred.base_url}")

    print("\n[1] 토큰 발급...")
    token = client.access_token()
    print(f"  access_token: {token[:12]}... (len {len(token)})")

    print("\n[2] 잔고 조회 (inquire-balance)...")
    balance = client.inquire_balance_raw(exchange=args.exchange)
    print("  rt_cd:", balance.get("rt_cd"), "msg:", balance.get("msg1"))
    print("  output1(보유종목) 개수:", len(balance.get("output1", []) or []))
    if balance.get("output1"):
        print("  output1[0] 키:", sorted(balance["output1"][0].keys()))
    print("  output2(요약) 키:", sorted((balance.get("output2") or {}).keys())
          if isinstance(balance.get("output2"), dict) else "리스트/기타")
    print("  output2 원본:", json.dumps(balance.get("output2"), ensure_ascii=False)[:800])

    print(f"\n[3] 시세 조회 (price) {args.symbol}@{args.exchange}...")
    price = client.price_raw(args.symbol, exchange=args.exchange)
    print("  rt_cd:", price.get("rt_cd"), "msg:", price.get("msg1"))
    output = price.get("output") or {}
    print("  output 키:", sorted(output.keys()))
    print("  last(현재가):", output.get("last"), "base(전일):", output.get("base"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
