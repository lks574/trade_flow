"""KIS 해외주식(미국) OpenAPI 클라이언트 — 인증·잔고·시세.

의존성: requests(`live` extra). core는 의존성 0 원칙이라 지연 import한다.
엔드포인트/TR_ID 출처: github.com/koreainvestment/open-trading-api (해외주식).

- 인증:   POST /oauth2/tokenP (client_credentials) -> access_token (~24h)
- 잔고:   GET  /uapi/overseas-stock/v1/trading/inquire-balance  (mock VTTS3012R / real TTTS3012R)
- 시세:   GET  /uapi/overseas-price/v1/quotations/price         (HHDFS00000300, 모의/실전 공통)
- 주문:   POST /uapi/overseas-stock/v1/trading/order            (2b에서 구현)

주의: 거래용 거래소코드(NASD/NYSE/AMEX)와 시세용 거래소코드(NAS/NYS/AMS)가 다르다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from trade_flow.broker.credentials import KisConfigError, KisCredentials

# 거래소 코드 매핑: 시세(price) EXCD  vs  거래(trading) OVRS_EXCG_CD
PRICE_EXCHANGE = {"NASDAQ": "NAS", "NYSE": "NYS", "AMEX": "AMS"}
TRADING_EXCHANGE = {"NASDAQ": "NASD", "NYSE": "NYSE", "AMEX": "AMEX"}

# TR_ID (모의는 실전 코드 앞에 V)
TR_BALANCE = {"mock": "VTTS3012R", "real": "TTTS3012R"}
TR_PRESENT_BALANCE = {"mock": "VTRP6504R", "real": "CTRP6504R"}
TR_ORDER_BUY = {"mock": "VTTT1002U", "real": "TTTT1002U"}
TR_ORDER_SELL = {"mock": "VTTT1006U", "real": "TTTT1006U"}
TR_PRICE = "HHDFS00000300"  # 시세는 모의/실전 공통


@dataclass
class _CachedToken:
    token: str
    expiry: datetime
    environment: str


class KisApiError(RuntimeError):
    """KIS API가 오류를 반환했다(rt_cd != '0' 등)."""


def _raise_for_rt(data: dict[str, Any], context: str) -> None:
    if data.get("rt_cd") not in (None, "0"):
        raise KisApiError(f"{context} error: rt_cd={data.get('rt_cd')} msg={data.get('msg1')}")


def _is_rate_limited(data: dict[str, Any]) -> bool:
    message = f"{data.get('msg1', '')}{data.get('error_description', '')}"
    return "초당 거래건수" in message or data.get("error_code") == "EGW00201"


class KisClient:
    def __init__(
        self,
        credentials: KisCredentials,
        *,
        session: Any | None = None,
        token_cache_path: Path | None = None,
        timeout_seconds: float = 10.0,
        min_request_interval: float = 0.0,
    ) -> None:
        self._cred = credentials
        self._session = session
        self._timeout = timeout_seconds
        self._token_cache_path = token_cache_path or Path("data/kis_token.json")
        self._cached: _CachedToken | None = None
        # KIS는 초당 호출수를 제한한다(모의 ~2/s). 요청 간 최소 간격을 강제한다.
        self._min_interval = min_request_interval
        self._last_request = 0.0

    # --- 내부 HTTP ---
    def _get_session(self) -> Any:
        if self._session is None:
            import requests  # 지연 import (live extra)

            self._session = requests.Session()
        return self._session

    def _url(self, path: str) -> str:
        return f"{self._cred.base_url}{path}"

    def _throttle(self) -> None:
        if self._min_interval <= 0:
            return
        import time

        elapsed = time.monotonic() - self._last_request
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request = time.monotonic()

    def _get(self, path: str, tr_id: str, params: dict[str, str], context: str) -> dict[str, Any]:
        """GET + 스로틀 + rate-limit 1회 재시도."""
        import time

        data: dict[str, Any] = {}
        for attempt in range(2):
            self._throttle()
            response = self._get_session().get(
                self._url(path),
                headers=self._headers(tr_id),
                params=params,
                timeout=self._timeout,
            )
            data = response.json()
            if _is_rate_limited(data) and attempt == 0:
                time.sleep(1.0)
                continue
            break
        _raise_for_rt(data, context)
        return data

    # --- 토큰 ---
    def access_token(self) -> str:
        now = datetime.now(UTC)
        cached = self._cached
        if cached and cached.environment == self._cred.environment and cached.expiry > now:
            return cached.token
        cached = self._load_token_cache()
        if cached and cached.environment == self._cred.environment and cached.expiry > now:
            self._cached = cached
            return cached.token
        return self._issue_token()

    def _issue_token(self) -> str:
        self._throttle()
        response = self._get_session().post(
            self._url("/oauth2/tokenP"),
            json={
                "grant_type": "client_credentials",
                "appkey": self._cred.app_key,
                "appsecret": self._cred.app_secret,
            },
            timeout=self._timeout,
        )
        data = response.json()
        token = data.get("access_token")
        if not token:
            raise KisApiError(f"token issuance failed: {data}")
        expires_in = int(data.get("expires_in", 86400))
        expiry = datetime.now(UTC) + timedelta(seconds=max(0, expires_in - 60))
        self._cached = _CachedToken(token, expiry, self._cred.environment)
        self._save_token_cache(self._cached)
        return token

    def _load_token_cache(self) -> _CachedToken | None:
        try:
            raw = json.loads(self._token_cache_path.read_text())
        except (OSError, ValueError):
            return None
        try:
            return _CachedToken(
                raw["token"], datetime.fromisoformat(raw["expiry"]), raw["environment"]
            )
        except (KeyError, ValueError):
            return None

    def _save_token_cache(self, token: _CachedToken) -> None:
        try:
            self._token_cache_path.parent.mkdir(parents=True, exist_ok=True)
            self._token_cache_path.write_text(
                json.dumps(
                    {
                        "token": token.token,
                        "expiry": token.expiry.isoformat(),
                        "environment": token.environment,
                    }
                )
            )
        except OSError:
            pass  # 캐시 실패는 치명적이지 않음(다음에 재발급)

    def _headers(self, tr_id: str) -> dict[str, str]:
        return {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {self.access_token()}",
            "appkey": self._cred.app_key,
            "appsecret": self._cred.app_secret,
            "tr_id": tr_id,
        }

    # --- 조회 ---
    def inquire_balance_raw(
        self, exchange: str = "NASDAQ", currency: str = "USD"
    ) -> dict[str, Any]:
        """해외주식 잔고 원시 응답(output1=보유종목, output2=요약).

        필드 매핑(AccountSnapshot)은 실제 모의 응답으로 확정한다(2b).
        """
        ovrs_excg = TRADING_EXCHANGE.get(exchange, exchange)
        params = {
            "CANO": self._cred.account,
            "ACNT_PRDT_CD": self._cred.account_product,
            "OVRS_EXCG_CD": ovrs_excg,
            "TR_CRCY_CD": currency,
            "CTX_AREA_FK200": "",
            "CTX_AREA_NK200": "",
        }
        return self._get(
            "/uapi/overseas-stock/v1/trading/inquire-balance",
            TR_BALANCE[self._cred.environment],
            params,
            "inquire-balance",
        )

    def inquire_present_balance_raw(self, nation: str = "840") -> dict[str, Any]:
        """해외주식 체결기준 현재잔고(예수금 포함) 원시 응답. nation 840=미국."""
        params = {
            "CANO": self._cred.account,
            "ACNT_PRDT_CD": self._cred.account_product,
            "WCRC_FRCR_DVSN_CD": "02",  # 02=외화
            "NATN_CD": nation,
            "TR_MKET_CD": "00",
            "INQR_DVSN_CD": "00",
        }
        return self._get(
            "/uapi/overseas-stock/v1/trading/inquire-present-balance",
            TR_PRESENT_BALANCE[self._cred.environment],
            params,
            "inquire-present-balance",
        )

    def price_raw(self, symbol: str, exchange: str = "NASDAQ") -> dict[str, Any]:
        """해외주식 현재가 원시 응답."""
        excd = PRICE_EXCHANGE.get(exchange, exchange)
        params = {"AUTH": "", "EXCD": excd, "SYMB": symbol}
        return self._get(
            "/uapi/overseas-price/v1/quotations/price", TR_PRICE, params, "price"
        )


def build_client(
    token_cache_path: Path | None = None, min_request_interval: float = 0.6
) -> KisClient:
    """환경변수 자격증명으로 클라이언트 구성. 기본 스로틀 0.6s(모의 초당 제한 대응)."""
    return KisClient(
        KisCredentials.from_env(),
        token_cache_path=token_cache_path,
        min_request_interval=min_request_interval,
    )


__all__ = ["KisClient", "KisApiError", "KisConfigError", "build_client"]
