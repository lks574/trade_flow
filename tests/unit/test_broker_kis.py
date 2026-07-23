import pytest

from trade_flow.broker import KisClient, KisConfigError, KisCredentials
from trade_flow.broker.credentials import MOCK_BASE_URL, REAL_BASE_URL
from trade_flow.broker.kis import KisApiError


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def json(self) -> dict:
        return self._payload


class _FakeSession:
    """네트워크 없이 KIS 응답을 흉내낸다. post/get 호출을 기록한다."""

    def __init__(self, *, token_payload=None, get_payloads=None) -> None:
        self.token_payload = token_payload or {"access_token": "tok-123", "expires_in": 86400}
        self.get_payloads = list(get_payloads or [])
        self.post_calls: list[tuple] = []
        self.get_calls: list[tuple] = []

    def post(self, url, json=None, timeout=None):  # noqa: A002 - KIS API 형태
        self.post_calls.append((url, json))
        return _FakeResponse(self.token_payload)

    def get(self, url, headers=None, params=None, timeout=None):
        self.get_calls.append((url, headers, params))
        payload = self.get_payloads.pop(0) if self.get_payloads else {"rt_cd": "0"}
        return _FakeResponse(payload)


def _cred(env: str = "mock") -> KisCredentials:
    return KisCredentials(
        app_key="key", app_secret="secret", account="12345678", environment=env
    )


def test_credentials_from_env_requires_selected_env_vars() -> None:
    with pytest.raises(KisConfigError):
        KisCredentials.from_env({"KIS_ENV": "mock", "KIS_MOCK_APP_KEY": "k"})  # secret/account 누락


def test_credentials_selects_env_by_prefix_and_base_url() -> None:
    both = {
        "KIS_MOCK_APP_KEY": "mk",
        "KIS_MOCK_APP_SECRET": "ms",
        "KIS_MOCK_ACCOUNT": "50000000",
        "KIS_REAL_APP_KEY": "rk",
        "KIS_REAL_APP_SECRET": "rs",
        "KIS_REAL_ACCOUNT": "60000000",
    }
    mock = KisCredentials.from_env({**both, "KIS_ENV": "mock"})
    assert mock.is_mock and mock.base_url == MOCK_BASE_URL
    assert mock.app_key == "mk" and mock.account == "50000000"
    real = KisCredentials.from_env({**both, "KIS_ENV": "real"})
    assert not real.is_mock and real.base_url == REAL_BASE_URL
    assert real.app_key == "rk" and real.account == "60000000"


def test_credentials_default_env_is_mock() -> None:
    cred = KisCredentials.from_env(
        {"KIS_MOCK_APP_KEY": "k", "KIS_MOCK_APP_SECRET": "s", "KIS_MOCK_ACCOUNT": "1"}
    )
    assert cred.is_mock


def test_access_token_issues_once_and_caches(tmp_path) -> None:
    session = _FakeSession()
    client = KisClient(_cred(), session=session, token_cache_path=tmp_path / "tok.json")
    assert client.access_token() == "tok-123"
    assert client.access_token() == "tok-123"
    # 두 번째 호출은 캐시 사용 -> 토큰 발급(post)은 1회만.
    assert len(session.post_calls) == 1
    assert session.post_calls[0][0].endswith("/oauth2/tokenP")


def test_token_cache_file_reused_by_new_client(tmp_path) -> None:
    cache = tmp_path / "tok.json"
    first = KisClient(_cred(), session=_FakeSession(), token_cache_path=cache)
    first.access_token()
    # 새 클라이언트(새 세션)는 파일 캐시를 재사용 -> post 호출 0.
    fresh_session = _FakeSession()
    second = KisClient(_cred(), session=fresh_session, token_cache_path=cache)
    assert second.access_token() == "tok-123"
    assert len(fresh_session.post_calls) == 0


def test_mock_uses_v_prefixed_balance_tr_id(tmp_path) -> None:
    session = _FakeSession(get_payloads=[{"rt_cd": "0", "output1": [], "output2": {}}])
    client = KisClient(_cred("mock"), session=session, token_cache_path=tmp_path / "t.json")
    client.inquire_balance_raw(exchange="NASDAQ")
    url, headers, params = session.get_calls[0]
    assert url.endswith("/uapi/overseas-stock/v1/trading/inquire-balance")
    assert headers["tr_id"] == "VTTS3012R"  # 모의 접두사 V
    assert params["OVRS_EXCG_CD"] == "NASD"  # 거래용 거래소코드


def test_price_uses_price_exchange_code(tmp_path) -> None:
    session = _FakeSession(get_payloads=[{"rt_cd": "0", "output": {"last": "150.0"}}])
    client = KisClient(_cred(), session=session, token_cache_path=tmp_path / "t.json")
    client.price_raw("AAPL", exchange="NASDAQ")
    url, headers, params = session.get_calls[0]
    assert url.endswith("/uapi/overseas-price/v1/quotations/price")
    assert headers["tr_id"] == "HHDFS00000300"
    assert params["EXCD"] == "NAS" and params["SYMB"] == "AAPL"  # 시세용 거래소코드


def test_api_error_raises(tmp_path) -> None:
    session = _FakeSession(get_payloads=[{"rt_cd": "1", "msg1": "오류"}])
    client = KisClient(_cred(), session=session, token_cache_path=tmp_path / "t.json")
    with pytest.raises(KisApiError):
        client.inquire_balance_raw()


def test_present_balance_uses_v_prefixed_tr_id(tmp_path) -> None:
    session = _FakeSession(get_payloads=[{"rt_cd": "0", "output2": [], "output3": {}}])
    client = KisClient(_cred("mock"), session=session, token_cache_path=tmp_path / "t.json")
    client.inquire_present_balance_raw(nation="840")
    url, headers, params = session.get_calls[0]
    assert url.endswith("/uapi/overseas-stock/v1/trading/inquire-present-balance")
    assert headers["tr_id"] == "VTRP6504R"  # 모의
    assert params["NATN_CD"] == "840" and params["WCRC_FRCR_DVSN_CD"] == "02"
