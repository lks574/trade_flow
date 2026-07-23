"""KIS(한국투자증권) OpenAPI 자격증명. 시크릿은 환경변수로만 받는다(레포에 저장 금지).

모의(mock)와 실전(real)은 앱키·시크릿·계좌가 서로 다르므로 둘 다 등록해두고
KIS_ENV로 선택한다. 각 환경은 접두사(KIS_MOCK_ / KIS_REAL_)로 구분한다.

환경변수:
  KIS_ENV                     "mock"(기본) 또는 "real" — 어느 자격증명을 쓸지 선택
  KIS_MOCK_APP_KEY            모의 앱 키
  KIS_MOCK_APP_SECRET         모의 앱 시크릿
  KIS_MOCK_ACCOUNT            모의 계좌번호 앞 8자리(CANO)
  KIS_MOCK_ACCOUNT_PRODUCT    모의 계좌상품코드, 기본 "01"
  KIS_REAL_APP_KEY / _SECRET / _ACCOUNT / _ACCOUNT_PRODUCT   실전용(동일 구조)

선택된 환경의 세 값(APP_KEY/APP_SECRET/ACCOUNT)이 없으면 오류. 로컬에서는 gitignore된
.env에 두 세트를 모두 두고, KIS_ENV로 전환한다.
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
        environment = source.get("KIS_ENV", "mock")
        if environment not in {"mock", "real"}:
            raise KisConfigError("KIS_ENV must be 'mock' or 'real'")
        prefix = "KIS_MOCK_" if environment == "mock" else "KIS_REAL_"
        app_key = source.get(f"{prefix}APP_KEY")
        app_secret = source.get(f"{prefix}APP_SECRET")
        account = source.get(f"{prefix}ACCOUNT")
        missing = [
            f"{prefix}{name}"
            for name, value in (
                ("APP_KEY", app_key),
                ("APP_SECRET", app_secret),
                ("ACCOUNT", account),
            )
            if not value
        ]
        if missing:
            raise KisConfigError(
                f"missing KIS environment variables for {environment}: {', '.join(missing)}. "
                "환경변수로 설정하세요(레포에 저장 금지)."
            )
        return cls(
            app_key=app_key,
            app_secret=app_secret,
            account=account,
            account_product=source.get(f"{prefix}ACCOUNT_PRODUCT", "01"),
            environment=environment,
        )
