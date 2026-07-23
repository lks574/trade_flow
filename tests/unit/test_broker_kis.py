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

    def post(self, url, headers=None, json=None, timeout=None):  # noqa: A002 - KIS API 형태
        self.post_calls.append((url, json))
        if url.endswith("/oauth2/tokenP"):
            return _FakeResponse(self.token_payload)
        return _FakeResponse({"rt_cd": "0", "output": {"ODNO": "1"}})

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


class _FakeClient:
    def __init__(self, present=None, balance=None, price_map=None, nccs=None) -> None:
        self._present = present or {}
        self._balance = balance or {}
        self._price_map = price_map or {}
        self._nccs = nccs or {"output": []}
        self._cred = type("C", (), {"environment": "mock", "account": "50198973"})()
        self.order_calls: list = []
        self.cancel_calls: list = []

    def inquire_present_balance_raw(self, nation="840"):
        return self._present

    def inquire_balance_raw(self, exchange="NASDAQ"):
        return self._balance

    def price_raw(self, symbol, exchange="NASDAQ"):
        return self._price_map[symbol]

    def order_raw(self, *, symbol, side, quantity, price, exchange="NASDAQ"):
        self.order_calls.append((symbol, side, quantity, price, exchange))
        return {"rt_cd": "0", "output": {"ODNO": "0000000123", "KRX_FWDG_ORD_ORGNO": "1234"}}

    def cancel_order_raw(self, *, symbol, org_order_no, quantity, exchange="NASDAQ"):
        self.cancel_calls.append((symbol, org_order_no, quantity, exchange))
        return {"rt_cd": "0", "output": {}}

    def inquire_nccs_raw(self, exchange="NASDAQ"):
        return self._nccs


def test_kis_broker_account_snapshot_usd_mapping() -> None:
    from decimal import Decimal

    from trade_flow.broker import KisBroker

    present = {
        "output2": [{"crcy_cd": "USD", "frst_bltn_exrt": "1480.9"}],
        "output3": {"tot_asst_amt": "148090"},  # / 1480.9 = 100 USD
    }
    balance = {
        "output1": [
            {"ovrs_pdno": "AAPL", "ovrs_cblc_qty": "2", "pchs_avg_pric": "25", "now_pric2": "30"}
        ]
    }
    broker = KisBroker(_FakeClient(present, balance, {}))
    snap = broker.account_snapshot()
    assert snap.nav == Decimal("100")
    assert snap.cash == Decimal("40")  # 100 - (2 * 30)
    assert snap.positions["AAPL"].quantity == 2
    assert snap.positions["AAPL"].market_price == Decimal("30")
    assert snap.account_hash == "kis-mock-50198973"


def test_kis_broker_quote_uses_last_for_bid_ask() -> None:
    from decimal import Decimal

    from trade_flow.broker import KisBroker

    broker = KisBroker(_FakeClient({}, {}, {"AAPL": {"output": {"last": "325.89"}}}))
    quote = broker.quote("AAPL")
    assert quote.bid == Decimal("325.89") and quote.ask == Decimal("325.89")


def test_is_rate_limited_detects_kis_message() -> None:
    from trade_flow.broker.kis import _is_rate_limited

    assert _is_rate_limited({"rt_cd": "1", "msg1": "초당 거래건수를 초과하였습니다."})
    assert _is_rate_limited({"error_code": "EGW00201"})
    assert not _is_rate_limited({"rt_cd": "0", "msg1": "정상처리 되었습니다."})


def _intent(side="buy", qty=1, price="100"):
    from datetime import date
    from decimal import Decimal

    from trade_flow.execution.models import OrderIntent

    return OrderIntent(
        intent_id=f"intent-{side}",
        trading_date=date(2026, 7, 23),
        symbol="AAPL",
        side=side,
        quantity=qty,
        limit_price=Decimal(price),
        rebalance_sequence=0,
    )


def test_kis_broker_submit_returns_broker_order_and_registers() -> None:
    from trade_flow.broker import KisBroker

    fake = _FakeClient()
    broker = KisBroker(fake)
    order = broker.submit(_intent(side="buy", qty=1, price="100"))
    assert order.broker_order_id == "0000000123"
    assert order.status == "submitted" and order.remaining_quantity == 1
    assert fake.order_calls == [("AAPL", "buy", 1, "100", "NASDAQ")]
    # 멱등성: 같은 실행에서 find_by_intent가 등록된 주문을 찾는다.
    found = broker.find_by_intent("intent-buy")
    assert found is not None and found.broker_order_id == "0000000123"


def test_kis_broker_cancel_uses_registered_context() -> None:
    from trade_flow.broker import KisBroker

    fake = _FakeClient()
    broker = KisBroker(fake)
    order = broker.submit(_intent(qty=3))
    cancelled = broker.cancel(order.broker_order_id)
    assert cancelled.status == "cancelled"
    assert fake.cancel_calls == [("AAPL", "0000000123", 3, "NASDAQ")]


def test_kis_broker_status_pending_vs_filled() -> None:
    from trade_flow.broker import KisBroker

    # 미체결에 남아있으면 submitted(부분), 없으면 filled.
    pending = _FakeClient(nccs={"output": [{"odno": "0000000123", "nccs_qty": "1"}]})
    broker = KisBroker(pending)
    broker.submit(_intent(qty=1))
    status = broker.find_by_intent("intent-buy")
    assert status.status == "submitted" and status.remaining_quantity == 1

    filled = _FakeClient(nccs={"output": []})
    broker2 = KisBroker(filled)
    broker2.submit(_intent(qty=1))
    status2 = broker2.find_by_intent("intent-buy")
    assert status2.status == "filled" and status2.filled_quantity == 1


def test_order_raw_daytime_session_uses_daytime_endpoint(tmp_path) -> None:
    session = _FakeSession(get_payloads=[])
    # post는 토큰 발급 + 주문 2회. 토큰 먼저 캐시해 주문 post만 검사.
    client = KisClient(_cred("mock"), session=session, token_cache_path=tmp_path / "t.json")
    client.access_token()
    client.order_raw(symbol="AAPL", side="buy", quantity=1, price="100", session="daytime")
    url, body = session.post_calls[-1]
    assert url.endswith("/uapi/overseas-stock/v1/trading/daytime-order")
    # 정규장 스위치 대조
    client.order_raw(symbol="AAPL", side="buy", quantity=1, price="100", session="regular")
    url2, _ = session.post_calls[-1]
    assert url2.endswith("/uapi/overseas-stock/v1/trading/order")
