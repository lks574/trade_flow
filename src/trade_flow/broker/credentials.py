"""KIS(한국투자증권) OpenAPI 자격증명. 시크릿은 환경변수로만 받는다(레포에 저장 금지).

필요 환경변수:
  KIS_APP_KEY          발급받은 앱 키
  KIS_APP_SECRET       발급받은 앱 시크릿
  KIS_ACCOUNT          계좌번호 앞 8자리(CANO)
  KIS_ACCOUNT_PRODUCT  계좌상품코드(ACNT_PRDT_CD), 기본 "01"
  KIS_ENV              "mock"(모의, 기본) 또는 "real"(실전)

로컬에서는 gitignore된 .env에 두고 셸에서 export하거나 python-dotenv 없이 직접 export한다.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass


class KisConfigError(RuntimeError):
    """자격증명/환경설정 오류."""


MOCK_BASE_URL = "https://openapivts.koreainvestment.com:29443"
REAL_BASE_URL = "https://openapi.koreainvestment.com:9443"


@dataclass(frozen=True)
class KisCredentials:
    app_key: str
    app_secret: str
    account: str
    account_product: str = "01"
    environment: str = "mock"

    def __post_init__(self) -> None:
        if self.environment not in {"mock", "real"}:
            raise KisConfigError("KIS_ENV must be 'mock' or 'real'")
        if not (self.app_key and self.app_secret and self.account):
            raise KisConfigError("KIS app key, secret, and account are required")

    @property
    def is_mock(self) -> bool:
        return self.environment == "mock"

    @property
    def base_url(self) -> str:
        return MOCK_BASE_URL if self.is_mock else REAL_BASE_URL

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> KisCredentials:
        source = os.environ if env is None else env
        missing = [
            name
            for name in ("KIS_APP_KEY", "KIS_APP_SECRET", "KIS_ACCOUNT")
            if not source.get(name)
        ]
        if missing:
            raise KisConfigError(
                f"missing KIS environment variables: {', '.join(missing)}. "
                "환경변수로 설정하세요(레포에 저장 금지)."
            )
        return cls(
            app_key=source["KIS_APP_KEY"],
            app_secret=source["KIS_APP_SECRET"],
            account=source["KIS_ACCOUNT"],
            account_product=source.get("KIS_ACCOUNT_PRODUCT", "01"),
            environment=source.get("KIS_ENV", "mock"),
        )
