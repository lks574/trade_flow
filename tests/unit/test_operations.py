from datetime import date
from decimal import Decimal

from trade_flow.operations import NavHistory


def test_nav_history_daily_return_and_record(tmp_path) -> None:
    hist = NavHistory(tmp_path / "nav.json")
    # 첫 기록 전엔 daily_return 0.
    assert hist.daily_return(Decimal("100"), on=date(2026, 7, 21)) == Decimal(0)
    hist.record(date(2026, 7, 20), Decimal("100"))
    hist.record(date(2026, 7, 21), Decimal("110"))
    # 7/22의 전 거래일(7/21=110) 대비 121 -> +10%.
    assert hist.daily_return(Decimal("121"), on=date(2026, 7, 22)) == Decimal("0.1")
    # 당일 재실행: on 미포함이라 7/21 기준 유지(7/22 값 무시).
    hist.record(date(2026, 7, 22), Decimal("121"))
    assert hist.daily_return(Decimal("121"), on=date(2026, 7, 22)) == Decimal("0.1")


def test_nav_history_last_before_ignores_same_and_future(tmp_path) -> None:
    hist = NavHistory(tmp_path / "nav.json")
    hist.record(date(2026, 7, 20), Decimal("100"))
    hist.record(date(2026, 7, 25), Decimal("200"))
    assert hist.last_before(date(2026, 7, 22)) == (date(2026, 7, 20), Decimal("100"))
    assert hist.last_before(date(2026, 7, 20)) is None  # 동일일 미포함


def test_nav_history_missing_file_is_empty(tmp_path) -> None:
    hist = NavHistory(tmp_path / "absent.json")
    assert hist.last_before(date(2026, 7, 22)) is None
    assert hist.daily_return(Decimal("100"), on=date(2026, 7, 22)) == Decimal(0)


def test_log_notifier_writes_line(tmp_path) -> None:
    from trade_flow.operations import LogNotifier, Notification

    log = tmp_path / "run.log"
    notifier = LogNotifier(log)
    result = notifier.send(Notification("rebalance_complete", "제출 5건", "info"))
    assert result.delivered
    content = log.read_text()
    assert "rebalance_complete" in content and "제출 5건" in content and "[info]" in content


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict:
        return self._payload


class _FakeSession:
    """kis 테스트와 같은 세션 주입 방식. 요청을 기록하고 준비된 응답/예외를 돌려준다."""

    def __init__(self, response: _FakeResponse | None = None, error: Exception | None = None):
        self._response = response
        self._error = error
        self.calls: list[tuple[str, dict]] = []

    def post(self, url: str, *, json: dict, timeout: float) -> _FakeResponse:
        self.calls.append((url, json))
        if self._error is not None:
            raise self._error
        assert self._response is not None
        return self._response


def test_telegram_notifier_from_env() -> None:
    from trade_flow.operations import TelegramNotifier

    assert TelegramNotifier.from_env({}) is None
    assert TelegramNotifier.from_env({"TELEGRAM_BOT_TOKEN": "t"}) is None  # chat_id 누락
    notifier = TelegramNotifier.from_env({"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "c"})
    assert notifier is not None


def test_telegram_notifier_sends_message() -> None:
    from trade_flow.operations import Notification, TelegramNotifier

    session = _FakeSession(_FakeResponse({"ok": True, "result": {"message_id": 42}}))
    notifier = TelegramNotifier("tok123", "chat9", session=session)
    result = notifier.send(Notification("rebalance_complete", "제출 5건", "info"))
    assert result.delivered and result.provider_message_id == "42"
    url, body = session.calls[0]
    assert url == "https://api.telegram.org/bottok123/sendMessage"
    assert body["chat_id"] == "chat9"
    assert "rebalance_complete" in body["text"] and "제출 5건" in body["text"]


def test_telegram_notifier_api_rejection() -> None:
    from trade_flow.operations import Notification, TelegramNotifier

    session = _FakeSession(_FakeResponse({"ok": False, "description": "chat not found"}, 400))
    notifier = TelegramNotifier("tok123", "chat9", session=session)
    result = notifier.send(Notification("s", "b", "error"))
    assert not result.delivered and "chat not found" in result.error_code


def test_telegram_notifier_network_error_redacts_token() -> None:
    from trade_flow.operations import Notification, TelegramNotifier

    session = _FakeSession(error=ConnectionError("POST /bottok123/sendMessage timed out"))
    notifier = TelegramNotifier("tok123", "chat9", session=session)
    result = notifier.send(Notification("s", "b", "critical"))
    assert not result.delivered
    assert "tok123" not in result.error_code and "***" in result.error_code


def test_fanout_notifier_aggregates_failures(tmp_path) -> None:
    from trade_flow.operations import (
        FanoutNotifier,
        LogNotifier,
        Notification,
        TelegramNotifier,
    )

    log = tmp_path / "run.log"
    failing = TelegramNotifier("tok", "chat", session=_FakeSession(error=ConnectionError("down")))
    fanout = FanoutNotifier(LogNotifier(log), failing)
    result = fanout.send(Notification("subject", "body", "info"))
    # 로그는 기록됐지만 텔레그램 실패 → 집계는 실패로 보고(실패 무시 금지).
    assert "subject" in log.read_text()
    assert not result.delivered and "down" in result.error_code

    good_session = _FakeSession(_FakeResponse({"ok": True, "result": {"message_id": 1}}))
    ok = TelegramNotifier("tok", "chat", session=good_session)
    assert FanoutNotifier(LogNotifier(log), ok).send(Notification("s", "b", "info")).delivered


def test_within_us_market_hours() -> None:
    from datetime import UTC, datetime

    from trade_flow.operations import within_us_market_hours

    # 2026-07-23은 목요일. 10:00 ET = 14:00 UTC -> 개장.
    assert within_us_market_hours(datetime(2026, 7, 23, 14, 0, tzinfo=UTC))
    # 08:00 ET = 12:00 UTC -> 개장 전.
    assert not within_us_market_hours(datetime(2026, 7, 23, 12, 0, tzinfo=UTC))
    # 17:00 ET = 21:00 UTC -> 폐장 후.
    assert not within_us_market_hours(datetime(2026, 7, 23, 21, 0, tzinfo=UTC))
    # 2026-07-25는 토요일 -> 시각 무관 폐장.
    assert not within_us_market_hours(datetime(2026, 7, 25, 14, 0, tzinfo=UTC))


def test_within_us_market_hours_requires_tz() -> None:
    from datetime import datetime

    import pytest

    from trade_flow.operations import within_us_market_hours

    with pytest.raises(ValueError, match="timezone-aware"):
        within_us_market_hours(datetime(2026, 7, 23, 14, 0))  # noqa: DTZ001
